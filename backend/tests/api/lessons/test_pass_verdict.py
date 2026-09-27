"""«Сдал / не сдал» over HTTP (I5 E38, Q-E9b-3 variant г).

* the lesson's `pass_criteria` is recorded in every card's `SESSION_CREATED.pass_criteria`, and
  the lesson report, the session report and the lesson CSV («Итог») judge the scored card by it;
  an unscored (ABORTED) card has no verdict;
* a session created without recorded criteria — the shape of every session created before this
  epic — is judged by the defaults (70 %, no failed-rule limit, a critical error fails);
* varying the criteria changes the verdict only: the same actions under two different criteria
  store the same score rows and the same checksum, and each rescores `identical_to_stored`; reading
  every verdict-bearing path moves no score row;
* the statistics and the rating carry `pass_count` / `pass_rate`, and their CSVs parse back to
  the same numbers;
* all three criteria off (or a value out of range) is `422 VALIDATION_ERROR` and creates nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from app.application.sessions import create_session as create_session_module
from app.domain.common.ids import ScenarioVersionId
from app.domain.events.types import EventType

from tests.api.conftest import auth
from tests.api.lessons.conftest import Lessons, plan_entry
from tests.api.lessons.test_reports_statistics import (
    _complete_dds_card,
    _get,
    _number,
    _parse_csv,
)

pytestmark = pytest.mark.integration

LENIENT = {"min_score_percent": 0, "max_failed_rules": None, "fail_on_critical": False}
"""Passes any scored card with a positive maximum."""
STRICT = {"min_score_percent": 100, "max_failed_rules": 0, "fail_on_critical": True}
"""Passes only a perfect card."""
DEFAULTS = {"min_score_percent": 70, "max_failed_rules": None, "fail_on_critical": True}


async def _ended_lesson(
    lessons: Lessons,
    version_id: ScenarioVersionId,
    criteria: dict[str, Any] | None,
    *,
    with_aborted_card: bool = False,
) -> tuple[str, str, list[str]]:
    """A lesson whose first card is completed and scored (and, optionally, a second card aborted
    before it arrived). Returns `(lesson_id, first_session_id, every_session_id)`."""
    plan = [plan_entry(1, version_id)]
    if with_aborted_card:
        plan.append(plan_entry(2, version_id, offset_ms=10**9))
    extra = {} if criteria is None else {"pass_criteria": criteria}
    detail = await lessons.created(plan, **extra)
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    session_ids = [card["session_id"] for card in detail["sessions"]]
    await _complete_dds_card(lessons, session_ids[0])
    for other in session_ids[1:]:
        aborted = await lessons.client.post(
            f"/api/v1/sessions/{other}/abort", headers=lessons.instructor, json={"reason": "x"}
        )
        assert aborted.status_code == 200, aborted.text
    assert (await lessons.tick(lesson_id)).completed
    return lesson_id, session_ids[0], session_ids


async def _lesson_report(lessons: Lessons, lesson_id: str) -> dict[str, Any]:
    response = await lessons.client.get(
        f"/api/v1/lessons/{lesson_id}/report", headers=lessons.instructor
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _session_report(lessons: Lessons, session_id: str) -> dict[str, Any]:
    response = await lessons.client.get(f"/api/v1/reports/{session_id}", headers=lessons.instructor)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _recorded(lessons: Lessons, session_id: str) -> dict[str, Any]:
    created = next(
        e for e in await lessons.events(session_id) if e["event_type"] == "SESSION_CREATED"
    )
    payload: dict[str, Any] = created["payload"]
    return payload


def _expected(card: dict[str, Any], criteria: dict[str, Any]) -> dict[str, Any]:
    """The verdict the stored numbers give under `criteria` — computed here from the report's own
    numbers, independently of `pass_verdict`."""
    score = card["score"]
    percent = min(100.0, max(0.0, 100 * score["total_points"] / score["total_max_points"]))
    failed: list[str] = []
    if criteria["min_score_percent"] is not None and percent < criteria["min_score_percent"]:
        failed.append("MIN_SCORE_PERCENT")
    if (
        criteria["max_failed_rules"] is not None
        and card["failed_rule_count"] > criteria["max_failed_rules"]
    ):
        failed.append("MAX_FAILED_RULES")
    if criteria["fail_on_critical"] and card["critical_error_count"] > 0:
        failed.append("CRITICAL_ERRORS")
    return {
        "passed": not failed,
        "failed_criteria": failed,
        "criteria": criteria,
        "score_percent": pytest.approx(percent),
        "failed_rule_count": card["failed_rule_count"],
        "critical_error_count": card["critical_error_count"],
    }


async def _score_rows(unit_of_work: Any, session_id: str) -> list[tuple[Any, ...]]:
    async with unit_of_work() as uow:
        rows = (
            await uow.session.execute(
                sa.text(
                    "SELECT rule_id, points_awarded, max_points, passed, critical_failure "
                    "FROM score_results WHERE session_id = :s ORDER BY rule_id"
                ),
                {"s": session_id},
            )
        ).all()
        await uow.commit()
    return [tuple(row) for row in rows]


async def _all_score_rows(unit_of_work: Any) -> list[tuple[Any, ...]]:
    async with unit_of_work() as uow:
        rows = (
            await uow.session.execute(
                sa.text("SELECT id, points_awarded, computed_at FROM score_results ORDER BY id")
            )
        ).all()
        await uow.commit()
    return [tuple(row) for row in rows]


# ---------------------------------------------------------------------------------------------
# Recorded on every card; the reports judge by it
# ---------------------------------------------------------------------------------------------


async def test_the_lesson_criteria_are_recorded_on_every_card_and_judge_its_reports(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    lesson_id, first, session_ids = await _ended_lesson(
        lessons, demo_version_id, LENIENT, with_aborted_card=True
    )
    for session_id in session_ids:
        assert (await _recorded(lessons, session_id))["pass_criteria"] == LENIENT

    report = await _lesson_report(lessons, lesson_id)
    scored, unscored = report["cards"]
    assert scored["pass_verdict"] == _expected(scored, LENIENT)
    assert scored["pass_verdict"]["passed"] is True
    assert unscored["score"] is None and unscored["pass_verdict"] is None, "no verdict («—»)"

    # The session report's header reads the same verdict.
    assert (await _session_report(lessons, first))["pass_verdict"] == scored["pass_verdict"]

    # «Итог» in the CSV, parsed back: «Сдал» on every row of the scored card, empty when unscored.
    rows = _parse_csv(
        await lessons.client.get(
            f"/api/v1/lessons/{lesson_id}/report.csv", headers=lessons.instructor
        )
    )
    scored_rows = [row for row in rows if row["Сессия"] == scored["session_id"]]
    assert scored_rows and {row["Итог"] for row in scored_rows} == {"Сдал"}
    [aborted_row] = [row for row in rows if row["Сессия"] == unscored["session_id"]]
    assert aborted_row["Итог"] == ""


async def test_a_session_created_without_recorded_criteria_is_judged_by_the_defaults(
    lessons: Lessons,
    demo_version_id: ScenarioVersionId,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The log shape of every session created before I5 E38: no `pass_criteria` key at all."""
    original = create_session_module.create_session

    def without_pass_criteria(**kwargs: Any) -> Any:
        session, events = original(**kwargs)
        stripped = [
            event.model_copy(
                update={"payload": {k: v for k, v in event.payload.items() if k != "pass_criteria"}}
            )
            if event.event_type is EventType.SESSION_CREATED
            else event
            for event in events
        ]
        return session, stripped

    monkeypatch.setattr(create_session_module, "create_session", without_pass_criteria)
    lesson_id, first, _ = await _ended_lesson(lessons, demo_version_id, STRICT)
    monkeypatch.undo()

    assert "pass_criteria" not in await _recorded(lessons, first)
    [card] = (await _lesson_report(lessons, lesson_id))["cards"]
    assert card["pass_verdict"] == _expected(card, DEFAULTS)
    assert (await _session_report(lessons, first))["pass_verdict"]["criteria"] == DEFAULTS


# ---------------------------------------------------------------------------------------------
# The verdict never moves a score (INV 9/10)
# ---------------------------------------------------------------------------------------------


async def test_varying_the_criteria_changes_the_verdict_never_the_score(
    lessons: Lessons, demo_version_id: ScenarioVersionId, unit_of_work: Any
) -> None:
    lenient_lesson, lenient, _ = await _ended_lesson(lessons, demo_version_id, LENIENT)
    strict_lesson, strict, _ = await _ended_lesson(lessons, demo_version_id, STRICT)

    # Same actions, different criteria: the very same stored score rows and checksum.
    lenient_rows = await _score_rows(unit_of_work, lenient)
    assert lenient_rows
    assert await _score_rows(unit_of_work, strict) == lenient_rows
    lenient_report = await _session_report(lessons, lenient)
    strict_report = await _session_report(lessons, strict)
    for key in ("total_points", "total_max_points", "by_category"):
        assert lenient_report["score_report"][key] == strict_report["score_report"][key]
    assert lenient_report["score_report"]["checksum"] == strict_report["score_report"]["checksum"]

    # Only the verdict differs.
    [lenient_card] = (await _lesson_report(lessons, lenient_lesson))["cards"]
    [strict_card] = (await _lesson_report(lessons, strict_lesson))["cards"]
    assert lenient_card["pass_verdict"] == _expected(lenient_card, LENIENT)
    assert strict_card["pass_verdict"] == _expected(strict_card, STRICT)
    assert lenient_card["pass_verdict"]["passed"] is True
    assert strict_card["pass_verdict"]["passed"] is False, "the demo run is not a perfect card"
    strict_csv = _parse_csv(
        await lessons.client.get(
            f"/api/v1/lessons/{strict_lesson}/report.csv", headers=lessons.instructor
        )
    )
    assert {row["Итог"] for row in strict_csv if row["Сессия"] == strict} == {"Не сдал"}

    # Every verdict-bearing read moves no score row; each session still rescores identically.
    before = await _all_score_rows(unit_of_work)
    token = lessons.tokens["instructor1"]
    for url in (
        f"/api/v1/lessons/{lenient_lesson}/report",
        f"/api/v1/lessons/{strict_lesson}/report.csv",
        f"/api/v1/reports/{strict}",
        "/api/v1/statistics",
        "/api/v1/statistics.csv",
        "/api/v1/statistics/rating",
        "/api/v1/statistics/rating.csv",
    ):
        response = await _get(lessons.client, url, token)
        assert response.status_code == 200, (url, response.text)
    assert await _all_score_rows(unit_of_work) == before
    for session_id in (lenient, strict):
        rescored = await lessons.client.post(
            f"/api/v1/reports/{session_id}/rescore",
            headers=lessons.instructor,
            json={"persist": False},
        )
        assert rescored.status_code == 200, rescored.text
        outcome = rescored.json()
        assert outcome["identical_to_stored"] is True
        assert outcome["stored_checksum"] == outcome["recomputed_checksum"]
        assert outcome["differences"] == []
    assert await _all_score_rows(unit_of_work) == before

    # The statistics and the rating count one pass out of two, and their CSVs say the same.
    trainee2 = str(lessons.users["trainee2"])
    rows = {
        row["trainee_user_id"]: row
        for row in (await _get(lessons.client, "/api/v1/statistics", token)).json()["rows"]
    }
    assert (rows[trainee2]["session_count"], rows[trainee2]["pass_count"]) == (2, 1)
    assert rows[trainee2]["pass_rate"] == pytest.approx(50.0)
    line = {
        row["Идентификатор"]: row
        for row in _parse_csv(await _get(lessons.client, "/api/v1/statistics.csv", token))
    }[trainee2]
    assert int(line["Сдано"]) == 1 and _number(line["Доля сдачи, %"]) == 50.0

    rating = (await _get(lessons.client, "/api/v1/statistics/rating", token)).json()["rows"]
    [ranked] = [row for row in rating if row["trainee_user_id"] == trainee2]
    assert (ranked["pass_count"], ranked["pass_rate"]) == (1, pytest.approx(50.0))
    rating_line = {
        row["Идентификатор"]: row
        for row in _parse_csv(await _get(lessons.client, "/api/v1/statistics/rating.csv", token))
    }[trainee2]
    assert int(rating_line["Сдано"]) == 1 and _number(rating_line["Доля сдачи, %"]) == 50.0


# ---------------------------------------------------------------------------------------------
# Refusals and the single session
# ---------------------------------------------------------------------------------------------


def _session_body(lessons: Lessons, version_id: ScenarioVersionId, **extra: Any) -> dict[str, Any]:
    return {
        "scenario_version_id": str(version_id),
        "session_mode": "SINGLE_ROLE",
        "participants": [{"user_id": str(lessons.users["trainee2"]), "assigned_role_type": "DDS"}],
        "variants": {"card_source": "GENERATED_CARD"},
        **extra,
    }


async def test_a_single_session_records_its_criteria_or_the_defaults(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    given = {"min_score_percent": None, "max_failed_rules": 2}  # fail_on_critical omitted → true
    created = await lessons.client.post(
        "/api/v1/sessions",
        headers=lessons.instructor,
        json=_session_body(lessons, demo_version_id, pass_criteria=given),
    )
    assert created.status_code == 201, created.text
    assert (await _recorded(lessons, created.json()["id"]))["pass_criteria"] == {
        "min_score_percent": None,
        "max_failed_rules": 2,
        "fail_on_critical": True,
    }

    plain = await lessons.client.post(
        "/api/v1/sessions", headers=lessons.instructor, json=_session_body(lessons, demo_version_id)
    )
    assert plain.status_code == 201, plain.text
    assert (await _recorded(lessons, plain.json()["id"]))["pass_criteria"] == DEFAULTS


@pytest.mark.parametrize(
    "criteria",
    [
        {"min_score_percent": None, "max_failed_rules": None, "fail_on_critical": False},
        {"min_score_percent": 101},
        {"max_failed_rules": -1},
        {"min_score_percent": 70, "pass_mark": 3},
    ],
)
async def test_invalid_criteria_are_422_and_create_nothing(
    lessons: Lessons, demo_version_id: ScenarioVersionId, criteria: dict[str, Any]
) -> None:
    async def totals() -> tuple[int, int]:
        sessions = await lessons.client.get("/api/v1/sessions", headers=lessons.instructor)
        listed = await lessons.client.get("/api/v1/lessons", headers=lessons.instructor)
        return sessions.json()["total"], listed.json()["total"]

    before = await totals()
    single = await lessons.client.post(
        "/api/v1/sessions",
        headers=lessons.instructor,
        json=_session_body(lessons, demo_version_id, pass_criteria=criteria),
    )
    assert single.status_code == 422, single.text
    assert single.json()["code"] == "VALIDATION_ERROR"
    lesson = await lessons.create([plan_entry(1, demo_version_id)], pass_criteria=criteria)
    assert lesson.status_code == 422, lesson.text
    assert lesson.json()["code"] == "VALIDATION_ERROR"
    assert await totals() == before


async def test_a_trainee_reads_the_verdict_of_their_released_card(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    """The verdict is part of the report a trainee may read — same numbers as the instructor's."""
    lesson_id, first, _ = await _ended_lesson(lessons, demo_version_id, LENIENT)
    released = await lessons.client.post(
        f"/api/v1/instructor/lessons/{lesson_id}/report/release", headers=lessons.instructor
    )
    assert released.status_code == 200, released.text
    mine = await lessons.client.get(
        f"/api/v1/reports/{first}", headers=auth(lessons.tokens["trainee2"])
    )
    assert mine.status_code == 200, mine.text
    assert mine.json()["pass_verdict"] == (await _session_report(lessons, first))["pass_verdict"]
