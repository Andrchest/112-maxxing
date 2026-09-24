"""Lessons over HTTP (I3 E4a; HLD 70 §70.3, §70.4.6, D15; `i3-openapi-delta.yaml`).

* `createLesson` creates every card's session at once, each `READY` and pointing back at its
  lesson — or, when one entry is refused, nothing at all, with `createSession`'s own refusal
  naming the position;
* the `LessonRunner` starts cards by arrival — each `ArrivalKind` is shown **denied** just before
  its condition holds and **allowed** once it does — as the instructor who created the lesson,
  recording `SESSION_STARTED.lesson_arrival`;
* a lesson completes when every card is terminal, aborts every running card when aborted, and is
  re-adopted from PostgreSQL after a restart;
* the lesson report lists the N card reports and sums them by weight; the release marks the cards
  `CHECKED` where the projection allows it;
* `listMyIncidents` carries the materialised status and the deadlines, and a trainee sees a card
  only once it has arrived.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from app.api.container import Container
from app.application.lessons.lesson_runner import LessonRunner
from app.application.testing.fakes import InMemoryRunnerLock
from app.domain.common.ids import LessonId, ScenarioVersionId
from app.domain.events.types import EventType

from tests.api.conftest import auth
from tests.api.handoff.conftest import (
    OperatorFlow,
    fill_card,
    prepare_handoff,
    raw_role_chain_version,
)
from tests.api.lessons.conftest import (
    CALLER_VOICE,
    GENERATED_CARD,
    SHORT_ACCEPT_MS,
    Lessons,
    plan_entry,
)

pytestmark = pytest.mark.integration


async def _count(unit_of_work: Any, table: str) -> int:
    async with unit_of_work() as uow:
        value = (await uow.session.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one()
        await uow.commit()
    return int(value)


# ---------------------------------------------------------------------------------------------
# createLesson
# ---------------------------------------------------------------------------------------------


async def test_create_lesson_creates_every_card_ready_with_its_lesson(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await lessons.created(
        [
            plan_entry(1, demo_version_id, offset_ms=0),
            plan_entry(2, demo_version_id, offset_ms=60_000),
            plan_entry(3, demo_version_id, kind="AFTER_PREVIOUS_SESSION", weight=2.0),
        ]
    )
    assert detail["state"] == "CREATED"
    assert [card["position"] for card in detail["sessions"]] == [1, 2, 3]
    assert {card["state"] for card in detail["sessions"]} == {"READY"}
    assert {card["card_status"] for card in detail["sessions"]} == {"REGISTERED"}
    assert len({card["display_number"] for card in detail["sessions"]}) == 3
    assert detail["scenario_plan"][2]["weight"] == 2.0
    assert detail["sessions"][0]["variants"]["card_source"] == "GENERATED_CARD"

    first = detail["sessions"][0]["session_id"]
    session = (
        await lessons.client.get(f"/api/v1/sessions/{first}", headers=lessons.instructor)
    ).json()
    assert session["lesson_id"] == detail["lesson_id"]
    assert session["lesson_position"] == 1
    created = (await lessons.events(first))[0]
    assert created["payload"]["lesson_id"] == detail["lesson_id"]
    assert created["payload"]["lesson_position"] == 1
    assert created["payload"]["timers"] == {
        "accept_within_ms": 30_000,
        "fill_within_ms": 180_000,
        "not_completed_after_ms": 172_800_000,
    }

    listed = await lessons.client.get(
        "/api/v1/lessons", headers=lessons.instructor, params={"scope": "ALL"}
    )
    assert listed.status_code == 200, listed.text
    [item] = listed.json()["items"]
    assert item["card_count"] == 3 and item["state"] == "CREATED"


async def test_a_refused_entry_rolls_the_whole_lesson_back_and_names_its_position(
    lessons: Lessons, demo_version_id: ScenarioVersionId, unit_of_work: Any
) -> None:
    before = await _count(unit_of_work, "simulation_sessions")
    response = await lessons.create(
        [
            plan_entry(1, demo_version_id),
            # I3 E5a implemented MEMO_STATUSES; brigade call ON stays unimplemented until E6.
            plan_entry(2, demo_version_id, variants={"dds_brigade_call": "ON"}),
        ]
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "VARIANT_NOT_AVAILABLE"
    assert "position 2" in response.json()["detail"]
    assert await _count(unit_of_work, "simulation_sessions") == before
    assert await _count(unit_of_work, "lessons") == 0


async def test_a_trainee_may_not_create_or_list_all_lessons(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    body = {
        "title_ru": "x",
        "session_mode": "SINGLE_ROLE",
        "participants": [{"user_id": str(lessons.users["trainee2"]), "assigned_role_type": "DDS"}],
        "scenario_plan": [plan_entry(1, demo_version_id)],
    }
    trainee = auth(lessons.tokens["trainee2"])
    assert (
        await lessons.client.post("/api/v1/lessons", headers=trainee, json=body)
    ).status_code == 403
    listed = await lessons.client.get("/api/v1/lessons", headers=trainee, params={"scope": "ALL"})
    assert listed.status_code == 403


# ---------------------------------------------------------------------------------------------
# Arrivals — allow and deny per kind
# ---------------------------------------------------------------------------------------------


async def test_at_offset_denies_before_and_allows_at_its_offset(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await lessons.created(
        [
            plan_entry(1, demo_version_id, offset_ms=0),
            plan_entry(2, demo_version_id, offset_ms=60_000),
        ]
    )
    lesson_id = detail["lesson_id"]
    started = await lessons.start(lesson_id)
    assert started["state"] == "ACTIVE"
    assert [card["state"] for card in started["sessions"]] == ["ACTIVE", "READY"], (
        "startLesson ticks once: the card due at 0 arrives with the response"
    )

    await lessons.at(lesson_id, 59_999)
    assert await lessons.states(lesson_id) == ["ACTIVE", "READY"]
    result = await lessons.at(lesson_id, 60_000)
    assert len(result.started) == 1
    assert await lessons.states(lesson_id) == ["ACTIVE", "ACTIVE"]

    second = (await lessons.get(lesson_id))["sessions"][1]
    assert second["started_at_lesson_offset_ms"] == 60_000
    started_event = next(
        e
        for e in await lessons.events(second["session_id"])
        if e["event_type"] == "SESSION_STARTED"
    )
    assert started_event["payload"]["lesson_arrival"] == {
        "kind": "AT_OFFSET",
        "due_offset_ms": 60_000,
        "fired_offset_ms": 60_000,
    }
    assert started_event["actor_type"] == "INSTRUCTOR"


async def test_after_previous_session_denies_while_it_runs_and_allows_after_its_delay(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await lessons.created(
        [
            plan_entry(1, demo_version_id),
            plan_entry(2, demo_version_id, kind="AFTER_PREVIOUS_SESSION", delay_ms=5_000),
        ]
    )
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    await lessons.at(lesson_id, 120_000)
    assert await lessons.states(lesson_id) == ["ACTIVE", "READY"], "card 1 still runs"

    first = detail["sessions"][0]["session_id"]
    aborted = await lessons.client.post(
        f"/api/v1/sessions/{first}/abort", headers=lessons.instructor, json={"reason": "тест"}
    )
    assert aborted.status_code == 200, aborted.text
    await lessons.at(lesson_id, 124_999)
    assert await lessons.states(lesson_id) == ["ABORTED", "READY"], "the delay has not passed"
    await lessons.at(lesson_id, 125_000)
    assert await lessons.states(lesson_id) == ["ABORTED", "ACTIVE"]


async def test_after_previous_112_stage_denies_until_the_handoff_and_allows_after_it(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    """Card 1 is a real 112 call (`CALLER_VOICE`, `MULTI_TRAINEE`); card 2 arrives when card 1's
    OPERATOR_112 stage reaches `HANDED_OFF` — not before, whatever the clock says."""
    trainee1, trainee2 = lessons.users["trainee1"], lessons.users["trainee2"]
    detail = await lessons.created(
        [
            plan_entry(1, demo_version_id, variants=CALLER_VOICE),
            plan_entry(
                2,
                demo_version_id,
                kind="AFTER_PREVIOUS_112_STAGE",
                variants=GENERATED_CARD,
                participants=[trainee2],
            ),
        ],
        session_mode="MULTI_TRAINEE",
        participants=[
            {"user_id": str(trainee1), "assigned_role_type": "OPERATOR_112"},
            {"user_id": str(trainee2), "assigned_role_type": "DDS"},
        ],
    )
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    await lessons.at(lesson_id, 30_000)
    assert await lessons.states(lesson_id) == ["ACTIVE", "READY"]

    flow = OperatorFlow(
        client=lessons.client,
        container=lessons.container,
        session_id=UUID(detail["sessions"][0]["session_id"]),
        operator_token=lessons.tokens["trainee1"],
        dds_token=lessons.tokens["trainee2"],
        instructor_token=lessons.tokens["instructor1"],
        operator_user_id=trainee1,
        dds_user_id=trainee2,
    )
    assert await flow.advance_call_flow() is True
    assert (await flow.post("/operator/call/answer")).status_code == 200
    await flow.append_asr(EventType.ASR_FINAL, "Горит квартира")
    assert await flow.advance_call_flow() is True
    await fill_card(flow)
    await prepare_handoff(flow, "FIRE_RESCUE")
    await lessons.tick(lesson_id)
    assert await lessons.states(lesson_id) == ["ACTIVE", "READY"], "prepared, not handed off"

    assert (await flow.post("/operator/handoff", json={})).status_code == 201
    await lessons.tick(lesson_id)
    assert await lessons.states(lesson_id) == ["ACTIVE", "ACTIVE"]


# ---------------------------------------------------------------------------------------------
# Completion, abort, re-adoption
# ---------------------------------------------------------------------------------------------


async def test_the_lesson_completes_once_every_card_is_terminal(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await lessons.created([plan_entry(1, demo_version_id)])
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    result = await lessons.tick(lesson_id)
    assert not result.completed
    session_id = detail["sessions"][0]["session_id"]
    await lessons.client.post(
        f"/api/v1/sessions/{session_id}/abort", headers=lessons.instructor, json={"reason": "x"}
    )
    result = await lessons.tick(lesson_id)
    assert result.completed and result.finished
    lesson = await lessons.get(lesson_id)
    assert lesson["state"] == "COMPLETED"
    assert lesson["completed_at"] is not None


async def test_abort_lesson_aborts_every_running_and_waiting_card(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await lessons.created(
        [plan_entry(1, demo_version_id), plan_entry(2, demo_version_id, offset_ms=600_000)]
    )
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    response = await lessons.client.post(
        f"/api/v1/lessons/{lesson_id}/abort", headers=lessons.instructor, json={"reason": "конец"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "ABORTED"
    assert [card["state"] for card in response.json()["sessions"]] == ["ABORTED", "ABORTED"]
    for card in response.json()["sessions"]:
        assert "SESSION_ABORTED" in [
            e["event_type"] for e in await lessons.events(card["session_id"])
        ]

    again = await lessons.client.post(
        f"/api/v1/lessons/{lesson_id}/abort", headers=lessons.instructor, json={"reason": "x"}
    )
    assert again.status_code == 409
    assert again.json()["code"] == "INVALID_TRANSITION"
    assert (await lessons.tick(lesson_id)).finished


async def test_another_instructor_may_not_start_the_lesson_but_an_admin_may(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await lessons.created([plan_entry(1, demo_version_id)])
    admin = auth(lessons.tokens["admin1"])
    response = await lessons.client.post(
        f"/api/v1/lessons/{detail['lesson_id']}/start", headers=admin
    )
    assert response.status_code == 200, response.text


async def test_the_runner_re_adopts_every_active_lesson_after_a_restart(
    lessons: Lessons, demo_version_id: ScenarioVersionId, container: Container
) -> None:
    """A second `LessonRunner` — a restarted backend — adopts the ACTIVE lesson from PostgreSQL
    and starts its card when it falls due, with its own lock."""
    detail = await lessons.created(
        [plan_entry(1, demo_version_id), plan_entry(2, demo_version_id, offset_ms=5_000)]
    )
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    lock = InMemoryRunnerLock()
    restarted = LessonRunner(
        container.unit_of_work,
        container.start_session(),
        lock,
        lessons.clock,
        instance_id="restarted",
        tick_ms=10,
        lock_ttl_s=30,
        lock_refresh_s=10,
    )
    try:
        adopted = await restarted.start()
        assert adopted == [LessonId(UUID(lesson_id))]
        assert restarted.adopted == frozenset(adopted)
        lessons.clock.advance_ms(5_000)
        for _ in range(200):
            if await lessons.states(lesson_id) == ["ACTIVE", "ACTIVE"]:
                break
            await asyncio.sleep(0.01)
        assert await lessons.states(lesson_id) == ["ACTIVE", "ACTIVE"]
        assert lock.owners == {LessonId(UUID(lesson_id)): "restarted"}
    finally:
        await restarted.stop()
    assert lock.owners == {}, "stop() releases every lock it holds"


# ---------------------------------------------------------------------------------------------
# Card status, the incident list, the report and its release
# ---------------------------------------------------------------------------------------------


async def test_a_queued_card_times_and_turns_not_notified(
    lessons: Lessons, short_timers_version_id: ScenarioVersionId
) -> None:
    """Owner fact: timing runs for queued cards too — nobody opened it, the 3 s still ran out."""
    detail = await lessons.created([plan_entry(1, short_timers_version_id)])
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    session_id = detail["sessions"][0]["session_id"]
    assert (await lessons.get(lesson_id))["sessions"][0]["card_status"] == "WORKED"

    lessons.clock.advance_ms(SHORT_ACCEPT_MS)
    await lessons.tick_session(session_id)
    assert (await lessons.get(lesson_id))["sessions"][0]["card_status"] == "NOT_NOTIFIED"
    changes = [
        e for e in await lessons.events(session_id) if e["event_type"] == "DDS_CARD_STATUS_CHANGED"
    ]
    assert [c["payload"]["new_status"] for c in changes] == ["WORKED", "NOT_NOTIFIED"]
    assert changes[1]["monotonic_offset_ms"] == SHORT_ACCEPT_MS
    assert changes[1]["actor_type"] == "SIMULATION"
    assert changes[1]["payload"]["deadline_offset_ms"] == SHORT_ACCEPT_MS


async def test_the_incident_list_shows_arrived_cards_with_status_and_deadlines(
    lessons: Lessons, short_timers_version_id: ScenarioVersionId
) -> None:
    detail = await lessons.created(
        [
            plan_entry(1, short_timers_version_id),
            plan_entry(2, short_timers_version_id, offset_ms=60_000),
        ]
    )
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    trainee = auth(lessons.tokens["trainee2"])
    response = await lessons.client.get(
        "/api/v1/incidents", headers=trainee, params={"lesson_id": lesson_id}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1, "the waiting card has not arrived for the trainee"
    [row] = body["items"]
    assert row["session_id"] == detail["sessions"][0]["session_id"]
    assert row["card_status"] == "WORKED"
    assert row["my_role_type"] == "DDS"
    assert row["accept_deadline_offset_ms"] == SHORT_ACCEPT_MS
    assert row["fill_deadline_offset_ms"] is None, "GENERATED_CARD: no call, no fill timer"
    assert row["not_completed_deadline_offset_ms"] == 600_000
    assert row["address_line_ru"], "the ДДС row reads the prefab snapshot's address"
    assert row["display_number"] == detail["sessions"][0]["display_number"]

    instructor = await lessons.client.get(
        "/api/v1/incidents", headers=lessons.instructor, params={"lesson_id": lesson_id}
    )
    assert instructor.json()["total"] == 2
    filtered = await lessons.client.get(
        "/api/v1/incidents",
        headers=trainee,
        params={"card_status": "NOT_NOTIFIED", "lesson_id": lesson_id},
    )
    assert filtered.json()["total"] == 0
    searched = await lessons.client.get(
        "/api/v1/incidents", headers=trainee, params={"q": str(row["display_number"])}
    )
    assert [item["session_id"] for item in searched.json()["items"]] == [row["session_id"]]


async def _complete_dds_card(lessons: Lessons, session_id: str) -> None:
    """The shortest road through the demo's DDS stage to a closed, scored session."""
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

    await post("/dds/acknowledge")
    await post("/dds/resources/selection/open")
    await to(300_000)
    board = (await lessons.client.get(f"{base}/dds/resources", headers=headers)).json()["items"]
    engine = next(item for item in board if item["callsign"] == "АЦ-1")
    await post("/dds/resources/select", {"resource_id": engine["resource_id"]})
    await post("/dds/resources/dispatch", {"note_ru": None})
    await to(560_000)
    await post("/dds/close", {"closure_reason": "RESOLVED"})


async def test_the_lesson_report_lists_the_card_reports_and_sums_them_by_weight(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await lessons.created(
        [
            plan_entry(1, demo_version_id, weight=2.5),
            plan_entry(2, demo_version_id, offset_ms=10**9),
        ]
    )
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    not_ready = await lessons.client.get(
        f"/api/v1/lessons/{lesson_id}/report", headers=lessons.instructor
    )
    assert not_ready.status_code == 409
    assert not_ready.json()["code"] == "REPORT_NOT_READY"

    first = detail["sessions"][0]["session_id"]
    await _complete_dds_card(lessons, first)
    second = detail["sessions"][1]["session_id"]
    await lessons.client.post(
        f"/api/v1/sessions/{second}/abort", headers=lessons.instructor, json={"reason": "x"}
    )
    assert (await lessons.tick(lesson_id)).completed
    card = (await lessons.get(lesson_id))["sessions"][0]
    assert card["card_status"] == "COMPLETED", "every leg closed RESOLVED (§70.4.6)"

    response = await lessons.client.get(
        f"/api/v1/lessons/{lesson_id}/report", headers=lessons.instructor
    )
    assert response.status_code == 200, response.text
    report = response.json()
    [reported] = report["cards"]
    assert reported["position"] == 1 and reported["weight"] == 2.5
    score = reported["score"]
    assert report["weighted_total"] == pytest.approx(2.5 * score["total_points"])
    assert report["weighted_max"] == pytest.approx(2.5 * score["total_max_points"])

    released = await lessons.client.post(
        f"/api/v1/instructor/lessons/{lesson_id}/report/release", headers=lessons.instructor
    )
    assert released.status_code == 200, released.text
    assert released.json()["report_released_at"] is not None
    assert released.json()["sessions"][0]["card_status"] == "COMPLETED", (
        "COMPLETED outranks CHECKED (A-5): the release does not lower it"
    )
    assert [e["event_type"] for e in await lessons.events(first)][-11] == "SESSION_COMPLETED", (
        "the release appends nothing to the closed log"
    )


async def test_releasing_a_worked_card_marks_it_checked_without_an_event(
    lessons: Lessons, unit_of_work: Any
) -> None:
    """A chain that ends at the 112 desk completes `WORKED`; the release makes it `CHECKED`."""
    trainee1 = lessons.users["trainee1"]
    version_id = await raw_role_chain_version(
        unit_of_work, "lesson-operator-only", ["OPERATOR_112"]
    )
    detail = await lessons.created(
        [plan_entry(1, version_id, variants=CALLER_VOICE)],
        participants=[{"user_id": str(trainee1), "assigned_role_type": "OPERATOR_112"}],
    )
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    flow = OperatorFlow(
        client=lessons.client,
        container=lessons.container,
        session_id=UUID(detail["sessions"][0]["session_id"]),
        operator_token=lessons.tokens["trainee1"],
        dds_token=lessons.tokens["trainee2"],
        instructor_token=lessons.tokens["instructor1"],
        operator_user_id=trainee1,
        dds_user_id=lessons.users["trainee2"],
    )
    assert await flow.advance_call_flow() is True
    assert (await flow.post("/operator/call/answer")).status_code == 200
    await flow.append_asr(EventType.ASR_FINAL, "Горит квартира")
    assert await flow.advance_call_flow() is True
    await fill_card(flow)
    await prepare_handoff(flow, "FIRE_RESCUE")
    assert (await flow.post("/operator/handoff", json={})).status_code == 201
    assert (
        await flow.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200
    assert (await flow.post("/operator/stage/complete")).status_code == 200
    assert (await lessons.tick(lesson_id)).completed
    session_id = detail["sessions"][0]["session_id"]
    assert (await lessons.get(lesson_id))["sessions"][0]["card_status"] == "WORKED"
    before = len(await lessons.events(session_id))

    released = await lessons.client.post(
        f"/api/v1/instructor/lessons/{lesson_id}/report/release", headers=lessons.instructor
    )
    assert released.status_code == 200, released.text
    assert released.json()["sessions"][0]["card_status"] == "CHECKED"
    assert len(await lessons.events(session_id)) == before


# ---------------------------------------------------------------------------------------------
# I3 E5b — lesson participants carry the ДДС service binding (HLD 70 §70.4.5)
# ---------------------------------------------------------------------------------------------


async def test_lesson_participants_bind_dds_trainees_to_services_on_every_card(
    lessons: Lessons, unit_of_work: Any, demo_version_id: ScenarioVersionId
) -> None:
    """`LessonParticipant.assigned_service_id` reaches every card's `session_participants`, and
    each card's legs are played by the bound trainee or by the script."""
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug("street-rubbish-fire")
        assert stored is not None
        version = await uow.scenarios.find_version(stored.scenario_id, 1)
        assert version is not None
        await uow.commit()
    one, two = lessons.users["trainee1"], lessons.users["trainee2"]
    participants = [
        {"user_id": str(one), "assigned_role_type": "DDS", "assigned_service_id": "FIRE_RESCUE"},
        {"user_id": str(two), "assigned_role_type": "DDS", "assigned_service_id": "TSODD"},
    ]
    created = await lessons.created(
        [
            plan_entry(1, version.scenario_version_id),
            plan_entry(2, version.scenario_version_id, offset_ms=60_000),
        ],
        session_mode="MULTI_TRAINEE",
        participants=participants,
    )
    detail = await lessons.get(created["lesson_id"])
    assert [(item["user_id"], item["assigned_service_id"]) for item in detail["participants"]] == [
        (str(one), "FIRE_RESCUE"),
        (str(two), "TSODD"),
    ]

    session_ids = [card["session_id"] for card in detail["sessions"]]
    async with unit_of_work() as uow:
        rows = (
            await uow.session.execute(
                sa.text(
                    "SELECT session_id, user_id, assigned_service_id FROM session_participants "
                    "WHERE session_id = ANY(:ids)"
                ),
                {"ids": [UUID(item) for item in session_ids]},
            )
        ).all()
        await uow.commit()
    bindings = {(str(row.session_id), str(row.user_id), row.assigned_service_id) for row in rows}
    assert bindings == {
        (session_id, str(user), service)
        for session_id in session_ids
        for user, service in ((one, "FIRE_RESCUE"), (two, "TSODD"))
    }

    await lessons.start(created["lesson_id"])
    await lessons.tick(created["lesson_id"])
    first = session_ids[0]
    response = await lessons.client.get(
        f"/api/v1/sessions/{first}/dds/legs", headers=auth(lessons.tokens["trainee2"])
    )
    assert response.status_code == 200, response.text
    legs = {leg["service_type"]: leg for leg in response.json()}
    assert legs["FIRE_RESCUE"]["bound_user_id"] == str(one)
    assert legs["TSODD"]["bound_user_id"] == str(two)
    assert legs["TSODD"]["is_mine"] is True and legs["FIRE_RESCUE"]["is_mine"] is False
    others = set(legs) - {"FIRE_RESCUE", "TSODD"}
    assert others and {legs[service]["responder"] for service in others} == {"SCRIPTED"}
