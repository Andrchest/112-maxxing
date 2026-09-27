"""Reports, statistics, CSV and the trainee's history over HTTP (I4 E33, HLD 71 §71.10).

* the lesson report's scored card carries its `norms` against the session's **recorded** timers
  (a plan entry's 45 s override, not the scenario's 30 s), plus its stored counters; an unscored
  card has none;
* `getLessonReportCsv` and `getTraineeStatisticsCsv` parse back to the JSON's numbers (UTF-8 with
  BOM, `;`, Russian headers, decimal comma);
* no report path re-scores (D11): with the evaluator made to raise, every E33 read still answers
  and the stored rows are untouched;
* a TRAINEE asking for someone else's statistics gets `403`;
* ТЗ ¶165: the statistics over 1000 seeded sessions answer in 30 s or less.
"""

from __future__ import annotations

import codecs
import csv
import io
import time
from statistics import fmean
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from app.domain.common.ids import ScenarioVersionId
from app.domain.scoring import engine

from tests.api.conftest import auth
from tests.api.lessons.conftest import Lessons, plan_entry

pytestmark = pytest.mark.integration

OVERRIDDEN_ACCEPT_MS = 45_000
ACCEPT_AFTER_MS = 12_000


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


async def _complete_dds_card(lessons: Lessons, session_id: str) -> None:
    """The demo's DDS stage to a closed, scored session, accepted 12 s after it arrived.

    Copied from `test_lessons.py` (not imported, so this module does not depend on another test
    module's private helper), with the acknowledgement moved to a known offset.
    """
    base = f"/api/v1/sessions/{session_id}"
    headers = auth(lessons.tokens["trainee2"])

    async def post(suffix: str, json: Any = None) -> Any:
        response = await lessons.client.post(f"{base}{suffix}", headers=headers, json=json)
        assert response.status_code in (200, 201), response.text
        return response.json()

    async def to(offset_ms: int) -> None:
        detail = (await lessons.client.get(base, headers=headers)).json()
        lessons.clock.advance_ms(offset_ms - int(detail["monotonic_offset_ms"]))
        await lessons.tick_session(session_id)

    await to(ACCEPT_AFTER_MS)
    await post("/dds/acknowledge")
    await post("/dds/resources/selection/open")
    await to(300_000)
    board = (await lessons.client.get(f"{base}/dds/resources", headers=headers)).json()["items"]
    engine_row = next(item for item in board if item["callsign"] == "АЦ-1")
    await post("/dds/resources/select", {"resource_id": engine_row["resource_id"]})
    await post("/dds/resources/dispatch", {"note_ru": None})
    await to(560_000)
    await post("/dds/close", {"closure_reason": "RESOLVED"})


async def _ended_lesson(lessons: Lessons, version_id: ScenarioVersionId) -> tuple[str, str]:
    """A lesson of two cards: the first (accept timer overridden to 45 s) completed and scored,
    the second aborted before it arrived. Returns `(lesson_id, first_session_id)`."""
    overridden = plan_entry(1, version_id)
    overridden["timers"] = {"accept_within_ms": OVERRIDDEN_ACCEPT_MS}
    detail = await lessons.created([overridden, plan_entry(2, version_id, offset_ms=10**9)])
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    first, second = (card["session_id"] for card in detail["sessions"])
    await _complete_dds_card(lessons, first)
    aborted = await lessons.client.post(
        f"/api/v1/sessions/{second}/abort", headers=lessons.instructor, json={"reason": "x"}
    )
    assert aborted.status_code == 200, aborted.text
    assert (await lessons.tick(lesson_id)).completed
    return lesson_id, first


async def _get(client: httpx.AsyncClient, url: str, token: str, **params: Any) -> httpx.Response:
    return await client.get(url, headers=auth(token), params=params or None)


def _parse_csv(response: httpx.Response) -> list[dict[str, str]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith(codecs.BOM_UTF8), "UTF-8 with BOM"
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))


def _number(cell: str) -> float | None:
    return None if cell == "" else float(cell.replace(",", "."))


async def _accept_legs(lessons: Lessons, session_id: str) -> list[tuple[int, dict[str, Any]]]:
    """Each leg's `HANDOFF_RECEIVED` offset and payload, from the log."""
    return [
        (int(event["monotonic_offset_ms"]), event["payload"])
        for event in await lessons.events(session_id)
        if event["event_type"] == "HANDOFF_RECEIVED"
    ]


# ---------------------------------------------------------------------------------------------
# The lesson report and its CSV
# ---------------------------------------------------------------------------------------------


async def test_a_scored_card_carries_its_norms_against_the_recorded_timers(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    lesson_id, first = await _ended_lesson(lessons, demo_version_id)
    response = await lessons.client.get(
        f"/api/v1/lessons/{lesson_id}/report", headers=lessons.instructor
    )
    assert response.status_code == 200, response.text
    scored, unscored = response.json()["cards"]

    events = await lessons.events(first)
    acknowledged = next(e for e in events if e["event_type"] == "DDS_ACKNOWLEDGED")
    legs = await _accept_legs(lessons, first)
    assert legs, "the prefab handoff notifies at least one service"
    created = next(e for e in events if e["event_type"] == "SESSION_CREATED")
    recorded_fill_ms = created["payload"]["timers"]["fill_within_ms"]
    # A ДДС-only card (GENERATED_CARD) has no 112 desk: no FILL norm (Q-E9b-2). Every leg now
    # carries both ACCEPT and DDS_FILL (I5 E36, Q-E9b-2): same measured moment, the 3-minute limit.
    assert [norm["kind"] for norm in scored["norms"]] == ["ACCEPT", "DDS_FILL"] * len(legs)
    accept_norms = [n for n in scored["norms"] if n["kind"] == "ACCEPT"]
    dds_fill_norms = [n for n in scored["norms"] if n["kind"] == "DDS_FILL"]
    for norm, (received_ms, payload) in zip(accept_norms, legs, strict=True):
        measured = int(acknowledged["monotonic_offset_ms"]) - received_ms
        assert norm == {
            "kind": "ACCEPT",
            "service_id": payload["service_type"],
            "measured_ms": measured,
            "norm_ms": OVERRIDDEN_ACCEPT_MS,  # the recorded override, not the scenario's 30 s
            "deviation_ms": measured - OVERRIDDEN_ACCEPT_MS,
        }
    for norm, (received_ms, payload) in zip(dds_fill_norms, legs, strict=True):
        measured = int(acknowledged["monotonic_offset_ms"]) - received_ms
        assert norm == {
            "kind": "DDS_FILL",
            "service_id": payload["service_type"],
            "measured_ms": measured,
            "norm_ms": recorded_fill_ms,
            "deviation_ms": measured - recorded_fill_ms,
        }
    assert created["payload"]["timers"]["accept_within_ms"] == OVERRIDDEN_ACCEPT_MS

    # (I5 E36, Q-E12-1) two reaction times per leg, delivery as the start.
    assert len(scored["reaction_times"]) == len(legs)
    for reaction, (received_ms, payload) in zip(scored["reaction_times"], legs, strict=True):
        assert reaction["service_id"] == payload["service_type"]
        expected = int(acknowledged["monotonic_offset_ms"]) - received_ms
        assert reaction["to_first_status_ms"] == expected
        assert reaction["to_open_ms"] is None, "the memo mode never opens a card here"

    # (I5 E36, Q-E12-3) the login of the ДДС suffix's sole player.
    assert scored["workstation"] == "trainee2"

    results = scored["score"]["results"]
    assert scored["failed_rule_count"] == sum(1 for r in results if not r["passed"])
    assert scored["critical_error_count"] == len(scored["score"]["critical_errors"])
    assert unscored["score"] is None
    assert unscored["norms"] == []
    assert unscored["reaction_times"] == []
    assert unscored["workstation"] == ""
    assert unscored["failed_rule_count"] is None and unscored["critical_error_count"] is None


async def test_the_lesson_report_csv_parses_back_to_the_same_numbers(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    lesson_id, _ = await _ended_lesson(lessons, demo_version_id)
    report = (
        await lessons.client.get(f"/api/v1/lessons/{lesson_id}/report", headers=lessons.instructor)
    ).json()
    response = await lessons.client.get(
        f"/api/v1/lessons/{lesson_id}/report.csv", headers=lessons.instructor
    )
    assert "attachment" in response.headers["content-disposition"]
    rows = _parse_csv(response)
    assert list(rows[0]) == [
        "Позиция",
        "Сессия",
        "Рабочее место",
        "Состояние",
        "Вес",
        "Баллы",
        "Максимум баллов",
        "Нарушено правил",
        "Критических ошибок",
        "Итог",  # (I5 E38, Q-E9b-3)
        "Норматив",
        "Служба",
        "Время, мс",
        "Норма, мс",
        "Отклонение от нормы, мс",
    ]

    scored, unscored = report["cards"]
    *card_rows, total = rows
    scored_rows = [row for row in card_rows if row["Сессия"] == scored["session_id"]]
    # (I5 E36) one row per norm (ACCEPT + DDS_FILL per leg), plus two reaction rows per leg.
    assert len(scored_rows) == len(scored["norms"]) + 2 * len(scored["reaction_times"])
    norm_rows = scored_rows[: len(scored["norms"])]
    reaction_rows = scored_rows[len(scored["norms"]) :]
    for row in scored_rows:
        assert int(row["Позиция"]) == scored["position"]
        assert row["Рабочее место"] == scored["workstation"] == "trainee2"
        assert _number(row["Вес"]) == scored["weight"]
        assert _number(row["Баллы"]) == scored["score"]["total_points"]
        assert _number(row["Максимум баллов"]) == scored["score"]["total_max_points"]
        assert int(row["Нарушено правил"]) == scored["failed_rule_count"]
        assert int(row["Критических ошибок"]) == scored["critical_error_count"]
    for row, norm in zip(norm_rows, scored["norms"], strict=True):
        assert (
            row["Норматив"]
            == {
                "ACCEPT": "Принятие решения службой",
                "DDS_FILL": "Заполнение карточки ДДС (3 мин)",
            }[norm["kind"]]
        )
        assert row["Служба"] != ""
        assert _number(row["Время, мс"]) == norm["measured_ms"]
        assert _number(row["Норма, мс"]) == norm["norm_ms"]
        assert _number(row["Отклонение от нормы, мс"]) == norm["deviation_ms"]
    # (I5 E36, Q-E12-1) the reaction-time rows: no norm, no deviation.
    reaction_labels = ("Время реакции: открытие карточки", "Время реакции: первый статус")
    for row in reaction_rows:
        assert row["Норматив"] in reaction_labels
        assert row["Норма, мс"] == "" and row["Отклонение от нормы, мс"] == ""
    [aborted_row] = [row for row in card_rows if row["Сессия"] == unscored["session_id"]]
    assert aborted_row["Состояние"] == "Прервано"
    assert aborted_row["Баллы"] == "" and aborted_row["Норматив"] == ""
    assert aborted_row["Рабочее место"] == ""
    assert aborted_row["Итог"] == "", "(I5 E38) an unscored card has no verdict"
    assert _number(total["Баллы"]) == report["weighted_total"]
    assert _number(total["Максимум баллов"]) == report["weighted_max"]


# ---------------------------------------------------------------------------------------------
# Statistics, their CSV and the trainee's history
# ---------------------------------------------------------------------------------------------


async def test_the_statistics_are_the_stored_numbers_and_their_csv_round_trips(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    lesson_id, first = await _ended_lesson(lessons, demo_version_id)
    card = (
        await lessons.client.get(f"/api/v1/lessons/{lesson_id}/report", headers=lessons.instructor)
    ).json()["cards"][0]
    trainee2 = str(lessons.users["trainee2"])
    trainee1 = str(lessons.users["trainee1"])

    response = await _get(lessons.client, "/api/v1/statistics", lessons.tokens["instructor1"])
    assert response.status_code == 200, response.text
    rows = {row["trainee_user_id"]: row for row in response.json()["rows"]}
    assert {trainee1, trainee2} <= set(rows)

    row = rows[trainee2]
    score = card["score"]
    assert row["session_count"] == 1 and row["lesson_count"] == 1
    # The stored totals, as a percent within the contract's 0…100 (a penalty total reads 0 %).
    percent = 100 * score["total_points"] / score["total_max_points"]
    assert row["average_percent"] == pytest.approx(min(100.0, max(0.0, percent)))
    failed: dict[str, int] = {}
    for result in score["results"]:
        if not result["passed"]:
            failed[result["category"]] = failed.get(result["category"], 0) + 1
    assert row["failed_rules_by_category"] == failed
    accept_norms = [n for n in card["norms"] if n["kind"] == "ACCEPT"]
    legs = await _accept_legs(lessons, first)
    played = [
        norm["deviation_ms"]
        for norm, (_, payload) in zip(accept_norms, legs, strict=True)
        if payload.get("responder") != "SCRIPTED"
    ]
    assert row["accept_deviation_ms_avg"] == pytest.approx(fmean(played))
    assert row["fill_deviation_ms_avg"] is None, "trainee2 filled no 112 card"
    # (I5 E36, Q-E12-1) the reaction-time averages, over the same played legs.
    played_status = [
        reaction["to_first_status_ms"]
        for reaction, (_, payload) in zip(card["reaction_times"], legs, strict=True)
        if payload.get("responder") != "SCRIPTED"
    ]
    assert row["reaction_to_status_ms_avg"] == pytest.approx(fmean(played_status))
    assert row["reaction_to_open_ms_avg"] is None, "no leg was ever opened in this flow"
    assert rows[trainee1]["session_count"] == 0
    assert rows[trainee1]["average_percent"] is None

    one = await _get(
        lessons.client, "/api/v1/statistics", lessons.tokens["instructor1"], trainee_id=trainee2
    )
    assert one.json()["rows"] == [row]

    csv_rows = _parse_csv(
        await _get(lessons.client, "/api/v1/statistics.csv", lessons.tokens["instructor1"])
    )
    by_id = {line["Идентификатор"]: line for line in csv_rows}
    assert set(by_id) == set(rows)
    line = by_id[trainee2]
    assert line["Обучаемый"] == row["display_name_ru"]
    assert line["Рабочее место"] == "trainee2"  # (I5 E36, Q-E12-3)
    assert int(line["Сессий"]) == row["session_count"]
    assert int(line["Занятий"]) == row["lesson_count"]
    assert _number(line["Средний процент"]) == row["average_percent"]
    assert (
        _number(line["Среднее отклонение принятия решения, мс"]) == row["accept_deviation_ms_avg"]
    )
    assert _number(line["Среднее отклонение заполнения карточки, мс"]) is None
    assert _number(line["Среднее время реакции: открытие карточки, мс"]) is None
    assert (
        _number(line["Среднее время реакции: первый статус, мс"])
        == (row["reaction_to_status_ms_avg"])
    )
    labelled = {key: int(value) for key, value in line.items() if key.startswith("Нарушено")}
    assert sum(labelled.values()) == sum(failed.values())


async def test_a_trainee_gets_403_for_someone_else_and_only_themselves_otherwise(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    await _ended_lesson(lessons, demo_version_id)
    trainee1 = str(lessons.users["trainee1"])
    trainee2 = str(lessons.users["trainee2"])
    token = lessons.tokens["trainee2"]

    for path in ("/api/v1/statistics", "/api/v1/statistics.csv"):
        other = await _get(lessons.client, path, token, trainee_id=trainee1)
        assert other.status_code == 403, other.text
        assert other.json()["code"] == "FORBIDDEN_FOR_ROLE"

    own = await _get(lessons.client, "/api/v1/statistics", token)
    assert own.status_code == 200, own.text
    assert [row["trainee_user_id"] for row in own.json()["rows"]] == [trainee2]
    explicit = await _get(lessons.client, "/api/v1/statistics", token, trainee_id=trainee2)
    assert explicit.json() == own.json()


async def test_my_history_lists_own_sessions_with_score_and_date(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    lesson_id, first = await _ended_lesson(lessons, demo_version_id)
    token = lessons.tokens["trainee2"]
    history = await _get(lessons.client, "/api/v1/me/history", token)
    assert history.status_code == 200, history.text
    body = history.json()
    [session] = body["sessions"]
    assert session["session_id"] == first and session["lesson_id"] == lesson_id
    assert session["completed_at"] is not None and session["scenario_title_ru"]
    own = (await _get(lessons.client, "/api/v1/statistics", token)).json()["rows"][0]
    assert body["statistics"] == own
    assert session["score_percent"] == pytest.approx(own["average_percent"])
    assert session["failed_rule_count"] == sum(own["failed_rules_by_category"].values())

    other = (await _get(lessons.client, "/api/v1/me/history", lessons.tokens["trainee1"])).json()
    assert other["sessions"] == [] and other["statistics"]["session_count"] == 0


async def test_an_unknown_trainee_or_group_is_404(lessons: Lessons) -> None:
    token = lessons.tokens["instructor1"]
    unknown = "00000000-0000-4000-8000-000000000001"
    for params in ({"trainee_id": unknown}, {"group_id": unknown}):
        response = await _get(lessons.client, "/api/v1/statistics", token, **params)
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------------------------
# D11: no report path re-scores
# ---------------------------------------------------------------------------------------------


async def test_no_report_or_statistics_path_recomputes_a_score(
    lessons: Lessons,
    demo_version_id: ScenarioVersionId,
    unit_of_work: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lesson_id, _ = await _ended_lesson(lessons, demo_version_id)

    async def stored() -> list[Any]:
        async with unit_of_work() as uow:
            rows = (
                await uow.session.execute(
                    sa.text("SELECT id, points_awarded, computed_at FROM score_results ORDER BY id")
                )
            ).all()
            await uow.commit()
        return [tuple(row) for row in rows]

    before = await stored()
    assert before

    def refuse(*_: Any, **__: Any) -> Any:
        raise AssertionError("a report path evaluated a scoring rule")

    monkeypatch.setattr(engine, "_one_rule", refuse)
    token = lessons.tokens["instructor1"]
    for url in (
        f"/api/v1/lessons/{lesson_id}/report",
        f"/api/v1/lessons/{lesson_id}/report.csv",
        "/api/v1/statistics",
        "/api/v1/statistics.csv",
    ):
        response = await _get(lessons.client, url, token)
        assert response.status_code == 200, (url, response.text)
    history = await _get(lessons.client, "/api/v1/me/history", lessons.tokens["trainee2"])
    assert history.status_code == 200, history.text
    assert await stored() == before


# ---------------------------------------------------------------------------------------------
# ТЗ ¶165 REQ-2142: an analytic report in 30 s or less
# ---------------------------------------------------------------------------------------------

SEEDED_SESSIONS = 1000
REPORT_BUDGET_S = 30.0


async def test_statistics_over_1000_seeded_sessions_answer_within_30_seconds(
    lessons: Lessons, demo_version_id: ScenarioVersionId, unit_of_work: Any
) -> None:
    """¶165 on seeded data (71 §71.15: real class volume cannot be reproduced here).

    One real scored card is cloned 999 times — the session row, its participants, its stored
    results and its log — so every clone is a complete, scored session the reader treats exactly
    like the original; the clones are spread one minute apart in `completed_at`.
    """
    _, first = await _ended_lesson(lessons, demo_version_id)
    clones = SEEDED_SESSIONS - 1
    async with unit_of_work() as uow:
        connection = uow.session
        await connection.execute(
            sa.text(
                "CREATE TEMP TABLE e33_clone_map ON COMMIT DROP AS "
                "SELECT gen_random_uuid() AS new_id, n FROM generate_series(1, :count) AS n"
            ),
            {"count": clones},
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO simulation_sessions (id, scenario_version_id, session_mode, state,
                    session_seed, time_scale, created_by_user_id, next_seq_no, started_at,
                    paused_total_ms, completed_at, created_at, variants)
                SELECT m.new_id, s.scenario_version_id, s.session_mode, s.state, s.session_seed,
                    s.time_scale, s.created_by_user_id, s.next_seq_no, s.started_at,
                    s.paused_total_ms, s.completed_at - make_interval(mins => m.n), s.created_at,
                    s.variants
                FROM simulation_sessions s CROSS JOIN e33_clone_map m WHERE s.id = :source
                """
            ),
            {"source": first},
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO session_participants (session_id, user_id, assigned_role_type,
                    assigned_service_id)
                SELECT m.new_id, p.user_id, p.assigned_role_type, p.assigned_service_id
                FROM session_participants p CROSS JOIN e33_clone_map m WHERE p.session_id = :source
                """
            ),
            {"source": first},
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO score_results (session_id, scenario_version_id, rule_id,
                    evaluator_type, category, points_awarded, max_points, passed, critical_failure)
                SELECT m.new_id, r.scenario_version_id, r.rule_id, r.evaluator_type, r.category,
                    r.points_awarded, r.max_points, r.passed, r.critical_failure
                FROM score_results r CROSS JOIN e33_clone_map m WHERE r.session_id = :source
                """
            ),
            {"source": first},
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO session_events (session_id, seq_no, event_type, timestamp_utc,
                    monotonic_offset_ms, actor_type, actor_id, correlation_id, payload)
                SELECT m.new_id, e.seq_no, e.event_type, e.timestamp_utc, e.monotonic_offset_ms,
                    e.actor_type, e.actor_id, e.correlation_id, e.payload
                FROM session_events e CROSS JOIN e33_clone_map m WHERE e.session_id = :source
                """
            ),
            {"source": first},
        )
        await uow.commit()

    started = time.perf_counter()
    response = await _get(lessons.client, "/api/v1/statistics", lessons.tokens["instructor1"])
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, response.text
    [row] = [
        row
        for row in response.json()["rows"]
        if row["trainee_user_id"] == str(lessons.users["trainee2"])
    ]
    assert row["session_count"] == SEEDED_SESSIONS
    assert elapsed <= REPORT_BUDGET_S, f"getTraineeStatistics took {elapsed:.1f} s"
