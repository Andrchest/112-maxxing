"""The simulated clock across a role transition (E17 ruling R1; SPEC §13, §39; HLD D7, §20.3).

`20-db-schema.md` §20.3 says `"started_at" + "paused_total_ms" is what sim time is recomputed
from`, and R1 gave `paused_total_ms` its one writer: `finish_role_transition` banks the wall-clock
length of the `ROLE_TRANSITION` interval. **Simulated time does not run during a hand-over.** Four
consequences, one test each:

1. the pause is banked and the clock freezes — `paused_total_ms` is exactly the interval, the
   `role_transition_started_offset_ms` stamp is cleared, and the DDS stage opens at the offset the
   112 stage ended at;
2. the world engine applies nothing while the session is paused, however long the pause is;
3. offsets never decrease across the transition, and the first DDS-stage event carries the
   transition-start offset rather than one hand-over later;
4. **two runs whose hand-over pauses differ produce the same offsets** (D7 determinism rule 5 /
   INV 7) — this is the point of the ruling: the length of a trainee's coffee break must not move
   a scenario ETA or a DEADLINE scoring rule, and test 4 proves both halves at once by comparing
   the whole `(event_type, monotonic_offset_ms)` stream of an 11-second hand-over with that of a
   seven-minute one.

The `FakeClock` is the container's, the one the Unit of Work stamps events with, so "advance the
clock by N ms" here is exactly "the hand-over took N ms" in production.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from app.api.container import Container
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import SessionId, UserId
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.handoff.conftest import OperatorFlow, fill_card, prepare_handoff
from tests.api.operator.conftest import _start_session

pytestmark = pytest.mark.integration

#: The demo scenario's `MULTI_TRAINEE` transition pause is ten seconds (§10.10); eleven is the
#: shortest hand-over the suite can drive, and seven minutes is a deliberately absurd one.
SHORT_PAUSE_MS = 11_000
LONG_PAUSE_MS = 420_000


# ---------------------------------------------------------------------------------------------
# Raw material
# ---------------------------------------------------------------------------------------------


async def _log(flow: OperatorFlow) -> list[dict[str, Any]]:
    """The session's whole log with offsets, as the instructor (unredacted) sees it."""
    response = await flow.get("/events", token=flow.instructor_token, params={"limit": 1000})
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


#: Payload keys that name *what* an event is about in scenario terms, most specific first. A
#: runtime `resource_id` is deliberately absent: `emergency_resources.id` is `gen_random_uuid()`
#: per session, so it is different in every run and cannot be part of a determinism assertion.
#: `callsign` is the scenario's own handle on a unit and is unique per scenario (§30.8 rule 15).
_STABLE_KEYS: tuple[str, ...] = (
    "callsign",
    "world_event_id",
    "fact_id",
    "field_path",
    "service_type",
    "role_type",
    "new_state",
)


def _stable_row(item: dict[str, Any]) -> tuple[str, int, str]:
    """One log row as `(event_type, offset, scenario-stable subject)`."""
    payload = item.get("payload") or {}
    subject = next(
        (str(payload[key]) for key in _STABLE_KEYS if isinstance(payload.get(key), str)), ""
    )
    return str(item["event_type"]), int(item["monotonic_offset_ms"]), subject


def _offset_of_pair(stream: list[tuple[str, int, str]], event_type: str) -> int:
    """The offset of the one `(event_type, offset)` pair of this type in a collected stream."""
    matches = [offset for name, offset, _subject in stream if name == event_type]
    assert len(matches) == 1, f"expected exactly one {event_type}, got {len(matches)}"
    return matches[0]


def _offset_of(log: list[dict[str, Any]], event_type: str) -> int:
    """The `monotonic_offset_ms` of the one event of this type."""
    matches = [item for item in log if item["event_type"] == event_type]
    assert len(matches) == 1, f"expected exactly one {event_type}, got {len(matches)}"
    return int(matches[0]["monotonic_offset_ms"])


async def _session_row(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork], session_id: UUID
) -> dict[str, Any]:
    """The `simulation_sessions` row, for the two columns the ruling is about."""
    async with uow_factory() as uow:
        result = await uow.session.execute(
            sa.text(
                "SELECT paused_total_ms, role_transition_started_offset_ms, state"
                " FROM simulation_sessions WHERE id = :id"
            ),
            {"id": session_id},
        )
        row = dict(result.one()._mapping)
        await uow.commit()
    return row


async def _stage_rows(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork], session_id: UUID
) -> list[dict[str, Any]]:
    async with uow_factory() as uow:
        result = await uow.session.execute(
            sa.text(
                "SELECT role_type, started_at_offset_ms FROM role_stages"
                " WHERE session_id = :id ORDER BY order_index"
            ),
            {"id": session_id},
        )
        rows = [dict(row._mapping) for row in result.all()]
        await uow.commit()
    return rows


# ---------------------------------------------------------------------------------------------
# 1-3: one hand-over, observed
# ---------------------------------------------------------------------------------------------


async def test_the_hand_over_pause_is_banked_and_the_dds_stage_opens_where_the_112_stage_ended(
    in_transition: OperatorFlow,
    clock: FakeClock,
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """R1: `finish_role_transition` is the one writer of `paused_total_ms`."""
    started_ms = _offset_of(await _log(in_transition), "ROLE_TRANSITION_STARTED")
    paused = await _session_row(uow_factory, in_transition.session_id)
    assert paused["state"] == "ROLE_TRANSITION"
    assert paused["paused_total_ms"] == 0
    assert paused["role_transition_started_offset_ms"] == started_ms

    clock.advance_ms(SHORT_PAUSE_MS)
    response = await in_transition.post("/stage/continue", token=in_transition.dds_token)
    assert response.status_code == 200, response.text

    resumed = await _session_row(uow_factory, in_transition.session_id)
    assert resumed["paused_total_ms"] == SHORT_PAUSE_MS, "the interval, exactly"
    assert resumed["role_transition_started_offset_ms"] is None, "the stamp is cleared"

    log = await _log(in_transition)
    assert _offset_of(log, "ROLE_TRANSITION_COMPLETED") == started_ms, (
        "the hand-over consumed no simulated time, so it completed where it began"
    )
    stages = await _stage_rows(uow_factory, in_transition.session_id)
    assert stages[1]["role_type"] == "DDS"
    assert stages[1]["started_at_offset_ms"] == started_ms

    # And the clock the trainee's console reads is back in step with the frozen value.
    assert int(response.json()["monotonic_offset_ms"]) == started_ms


async def test_the_world_engine_applies_nothing_while_the_session_is_paused(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    """A tick during `ROLE_TRANSITION` is a no-op however much wall clock has gone by."""
    before = await _log(in_transition)

    for _ in range(4):
        clock.advance_ms(LONG_PAUSE_MS)
        await in_transition.container.runner.tick_now(SessionId(in_transition.session_id))

    assert await _log(in_transition) == before, (
        "28 minutes of wall clock produced no event: the simulation was not running"
    )


async def test_offsets_never_decrease_and_the_first_dds_event_lands_at_the_transition_offset(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    """R1's bite: without the freeze the DDS half would start `SHORT_PAUSE_MS` later."""
    started_ms = _offset_of(await _log(in_transition), "ROLE_TRANSITION_STARTED")

    clock.advance_ms(SHORT_PAUSE_MS)
    assert (
        await in_transition.post("/stage/continue", token=in_transition.dds_token)
    ).status_code == 200
    # One real DDS command and one tick on top, so the assertion covers appended events too.
    assert (
        await in_transition.post("/dds/acknowledge", token=in_transition.dds_token)
    ).status_code == 200
    clock.advance_ms(60_000)
    await in_transition.container.runner.tick_now(SessionId(in_transition.session_id))

    log = await _log(in_transition)
    # From the transition onwards — the 112 half carries one synthetic offset, the `1000 ms` the
    # `append_asr` test lever hard-codes for the voice agent's events (`OperatorFlow.append_asr`).
    start_index = next(
        index for index, item in enumerate(log) if item["event_type"] == "ROLE_TRANSITION_STARTED"
    )
    offsets = [int(item["monotonic_offset_ms"]) for item in log]
    tail = offsets[start_index:]
    assert tail == sorted(tail), f"an offset went backwards across the hand-over: {tail}"

    completed_index = next(
        index for index, item in enumerate(log) if item["event_type"] == "ROLE_TRANSITION_COMPLETED"
    )
    assert offsets[completed_index] == started_ms
    assert offsets[completed_index + 1] == started_ms, (
        "ROLE_STAGE_STARTED — the DDS stage's first event — is at the transition offset, "
        f"not at {started_ms + SHORT_PAUSE_MS}"
    )
    acknowledged = next(item for item in log if item["event_type"] == "DDS_ACKNOWLEDGED")
    assert int(acknowledged["monotonic_offset_ms"]) == started_ms, (
        "the first trainee action of the DDS stage is not pushed forward by the hand-over either"
    )


# ---------------------------------------------------------------------------------------------
# 4: the pause length is not an input to the event stream (INV 7 / D7 rule 5)
# ---------------------------------------------------------------------------------------------


async def _run_one_cycle(
    client: httpx.AsyncClient,
    container: Container,
    clock: FakeClock,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: Any,
    *,
    pause_ms: int,
) -> list[tuple[str, int, str]]:
    """One 112 -> hand-over -> DDS cycle whose only variable is how long the hand-over took.

    Every other instant is pinned to an absolute *session offset* read back from the server, so
    the two runs issue the same commands at the same simulated times by construction.
    """
    session_id = await _start_session(client, tokens, users, demo_version_id)
    flow = OperatorFlow(
        client=client,
        container=container,
        session_id=session_id,
        operator_token=tokens["trainee1"],
        dds_token=tokens["trainee2"],
        instructor_token=tokens["instructor1"],
        operator_user_id=users["trainee1"],
        dds_user_id=users["trainee2"],
    )

    async def seek(offset_ms: int) -> None:
        """Put the session's running clock at `offset_ms`, whatever has been banked."""
        detail = await flow.get("", token=flow.instructor_token)
        assert detail.status_code == 200, detail.text
        clock.advance_ms(offset_ms - int(detail.json()["monotonic_offset_ms"]))

    # -- the 112 stage, at fixed session offsets ----------------------------------------------
    assert await flow.advance_call_flow() is True
    assert (await flow.post("/operator/call/answer")).status_code == 200
    await flow.append_asr(EventType.ASR_FINAL, "Горит квартира на улице Ленина, дом 5")
    assert await flow.advance_call_flow() is True
    await fill_card(flow)
    await prepare_handoff(flow, "FIRE_RESCUE", "AMBULANCE")
    assert (await flow.post("/operator/handoff", json={})).status_code == 201
    assert (
        await flow.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200
    assert (await flow.post("/operator/stage/complete")).status_code == 200

    # -- the hand-over, whose length is the variable under test -------------------------------
    clock.advance_ms(pause_ms)
    assert (await flow.post("/stage/continue", token=flow.dds_token)).status_code == 200

    # -- the DDS stage, again at fixed session offsets -----------------------------------------
    assert (await flow.post("/dds/acknowledge", token=flow.dds_token)).status_code == 200
    assert (
        await flow.post("/dds/resources/selection/open", token=flow.dds_token)
    ).status_code == 200
    board = (await flow.get("/dds/resources", token=flow.dds_token)).json()["items"]
    engine = next(item for item in board if item["callsign"] == "АЦ-1")
    assert (
        await flow.post(
            "/dds/resources/select",
            token=flow.dds_token,
            json={"resource_id": engine["resource_id"]},
        )
    ).status_code == 200
    assert (
        await flow.post("/dds/resources/dispatch", token=flow.dds_token, json={"note_ru": None})
    ).status_code in (200, 201)

    for offset_ms in (200_000, 400_000, 560_000):
        await seek(offset_ms)
        await container.runner.tick_now(SessionId(session_id))

    return [_stable_row(item) for item in await _log(flow)]


async def test_two_hand_overs_of_different_wall_clock_length_produce_the_same_offsets(
    client: httpx.AsyncClient,
    container: Container,
    clock: FakeClock,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: Any,
) -> None:
    """The point of ruling R1, stated as INV 7 (D7 determinism rule 5).

    An eleven-second hand-over and a seven-minute one are the same exercise: the same commands at
    the same simulated offsets, the same world events fired at the same times, the same numbers a
    DEADLINE scoring rule would subtract. If the pause were counted as simulated time, the second
    run's whole DDS half would sit 409 seconds later and its ETAs would have expired en route.

    The comparison is "the same event types in the same order, carrying the same offsets" rather
    than a plain list equality: several resource movements that a single tick applies share that
    tick's transaction and are ordered among themselves by a set iteration, which is the tie-break
    `tests/api/dds/test_full_cycle.py` already documents for `select`/`dispatch`. That ordering is
    not what this ruling is about, and pinning it here would be pinning an unrelated bug.
    """
    short = await _run_one_cycle(
        client, container, clock, tokens, users, demo_version_id, pause_ms=SHORT_PAUSE_MS
    )
    long = await _run_one_cycle(
        client, container, clock, tokens, users, demo_version_id, pause_ms=LONG_PAUSE_MS
    )

    assert short == long, "the same events, about the same units, at the same simulated offsets"
    assert [name for name, _o, _s in short].count("ROLE_TRANSITION_COMPLETED") == 1
    # A DEADLINE scoring rule subtracts two of these offsets outright
    # (`app.domain.scoring.evaluators.deadline`), so identical offsets are identical verdicts:
    # the trainee is never penalised, or rewarded, for how long the hand-over screen was up.
    for event_type in ("HANDOFF_CREATED", "ROLE_STAGE_STARTED", "RESOURCE_DISPATCHED"):
        assert [offset for name, offset, _s in short if name == event_type] == [
            offset for name, offset, _s in long if name == event_type
        ], f"{event_type} moved with the pause length; a DEADLINE rule would score differently"

    # The hand-over is the only difference between the two runs, and it left no trace at all.
    started_ms = _offset_of_pair(short, "ROLE_TRANSITION_STARTED")
    assert _offset_of_pair(short, "ROLE_TRANSITION_COMPLETED") == started_ms
