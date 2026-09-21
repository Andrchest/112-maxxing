"""`TickSession` against real PostgreSQL (SPEC §12, §39; D3, D5, D7).

Simulated time is driven by advancing the `FakeClock`, never by sleeping: `tick_session` derives
`now_ms` from `clock.now() - session.started_at`, so a test can cover ten minutes of simulation in
microseconds and still exercise the production path end to end.
"""

from __future__ import annotations

import asyncio

import pytest
from app.application.testing.fakes import FakeClock
from app.domain.common.actors import ActorRef
from app.domain.enums import ActorType, ResourceStatus, SessionState
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.simulation._support import SimHarness, build_session, count, scalar

pytestmark = pytest.mark.integration

TRAINEE = ActorRef(actor_type=ActorType.TRAINEE)


# ---------------------------------------------------------------------------------------------
# Instantiation (create_session's new half)
# ---------------------------------------------------------------------------------------------


async def test_create_session_instantiates_the_board_and_the_engine_state(
    harness: SimHarness, migrated_engine: AsyncEngine
) -> None:
    """The scenario's eleven resources and one zeroed `world_engine_states` row (§20.5, E6)."""
    board = await harness.resources()
    assert len(board) == 11
    assert board["smp12"].resource.current_status is ResourceStatus.UNAVAILABLE
    assert board["ac1"].resource.current_status is ResourceStatus.AVAILABLE
    assert board["ac1"].resource.eta.travel_time_seconds == 150

    assert await count(migrated_engine, "world_engine_states") == 1
    assert (
        await scalar(
            migrated_engine,
            "SELECT last_tick_ms FROM world_engine_states WHERE incident_id = :id",
            id=harness.incident_id,
        )
        == 0
    )


async def test_two_sessions_get_independent_resource_instances(
    migrated_engine: AsyncEngine,
) -> None:
    """§20.5: "session-scoped, so two concurrent sessions never collide"."""
    first = await build_session(migrated_engine, namespace=1)
    second = await build_session(migrated_engine, namespace=2, import_scenario=False)
    first_ids = {entry.resource.resource_id for entry in (await first.resources()).values()}
    second_ids = {entry.resource.resource_id for entry in (await second.resources()).values()}
    assert first_ids.isdisjoint(second_ids)
    assert await count(migrated_engine, "emergency_resources") == 22


# ---------------------------------------------------------------------------------------------
# A TIMED event
# ---------------------------------------------------------------------------------------------


async def test_a_timed_event_fires_once_and_lands_in_both_layers(
    harness: SimHarness, migrated_engine: AsyncEngine
) -> None:
    """`fire_spreads` (TIMED, 180 s, `caller_observable: true`) mutates world *and* belief."""
    result = await harness.advance_and_tick(180_000)
    assert result.fired_world_event_ids == ("fire_spreads",)

    world_facts = await scalar(
        migrated_engine,
        "SELECT facts FROM incident_world_states WHERE incident_id = :id",
        id=harness.incident_id,
    )
    belief_facts = await scalar(
        migrated_engine,
        "SELECT facts FROM incident_caller_beliefs WHERE incident_id = :id",
        id=harness.incident_id,
    )
    assert world_facts["incident.smoke_visible"] is True
    assert belief_facts["incident.smoke_visible"] is True

    # A second tick past the same moment must not fire it again (`max_occurrences: 1`).
    again = await harness.advance_and_tick(60_000)
    assert again.fired_world_event_ids == ()
    occurrences = await scalar(
        migrated_engine,
        "SELECT bookkeeping -> 'occurrences' FROM world_engine_states WHERE incident_id = :id",
        id=harness.incident_id,
    )
    assert occurrences["fire_spreads"] == 1


async def test_fired_events_are_appended_with_the_simulation_actor_and_valid_payloads(
    harness: SimHarness,
) -> None:
    """Every event a tick appends is a SIMULATION event whose payload satisfies §10.13."""
    await harness.advance_and_tick(180_000)
    appended = [
        event
        for event in await harness.events()
        if event.event_type
        in {
            EventType.WORLD_EVENT_TRIGGERED,
            EventType.WORLD_TRUTH_MUTATED,
            EventType.CALLER_BELIEF_MUTATED,
            EventType.CALLER_EMOTION_CHANGED,
            EventType.NOTIFICATION_CREATED,
        }
    ]
    assert appended, "the tick appended nothing"
    for event in appended:
        assert event.actor_type is ActorType.SIMULATION
        validate_payload(event.event_type, event.payload)

    triggered = next(
        event for event in appended if event.event_type is EventType.WORLD_EVENT_TRIGGERED
    )
    assert triggered.payload["world_event_id"] == "fire_spreads"
    assert triggered.payload["at_offset_ms"] == 180_000


# ---------------------------------------------------------------------------------------------
# D3: a non-observable event never touches the caller's row
# ---------------------------------------------------------------------------------------------


async def test_a_non_observable_event_changes_world_truth_only(
    harness: SimHarness, migrated_engine: AsyncEngine
) -> None:
    """`second_report_balcony` is `caller_observable: false`: the belief row must not move (D3)."""
    belief_before = await scalar(
        migrated_engine,
        "SELECT revision, updated_at FROM incident_caller_beliefs WHERE incident_id = :id",
        id=harness.incident_id,
    )
    await harness.append(
        DomainEvent(
            event_type=EventType.HANDOFF_CREATED,
            actor=TRAINEE,
            monotonic_offset_ms=0,
            payload={"snapshot_id": "00000000-0000-4000-8000-000000000001"},
        )
    )
    # The first tick folds the action and queues the delayed trigger; the second fires it.
    await harness.advance_and_tick(61_000)
    fired = await harness.advance_and_tick(1_000)
    assert fired.fired_world_event_ids == ("second_report_balcony",)

    world_facts = await scalar(
        migrated_engine,
        "SELECT facts FROM incident_world_states WHERE incident_id = :id",
        id=harness.incident_id,
    )
    assert world_facts["people.total_inside"] == 2

    belief_after = await scalar(
        migrated_engine,
        "SELECT revision, updated_at FROM incident_caller_beliefs WHERE incident_id = :id",
        id=harness.incident_id,
    )
    assert belief_after == belief_before


# ---------------------------------------------------------------------------------------------
# Resource movement
# ---------------------------------------------------------------------------------------------


async def test_a_dispatched_resource_walks_to_on_scene_with_audit_rows(
    harness: SimHarness, migrated_engine: AsyncEngine
) -> None:
    """`ac1`: turnout 30 s, travel 150 s, setup 30 s — at 200 s it is ON_SCENE (§10.7, D7)."""
    resource_id = await harness.set_resource_status("ac1", ResourceStatus.DISPATCHED, 0)
    await harness.advance_and_tick(200_000)

    board = await harness.resources()
    assert board["ac1"].resource.current_status is ResourceStatus.ON_SCENE
    assert board["ac1"].resource.status_changed_at_offset_ms == 180_000

    changes = await scalar(
        migrated_engine,
        "SELECT array_agg(new_status ORDER BY at_offset_ms) FROM resource_state_changes"
        " WHERE resource_id = :id",
        id=resource_id,
    )
    assert changes == ["EN_ROUTE", "ON_SCENE"]

    offsets = await scalar(
        migrated_engine,
        "SELECT array_agg(at_offset_ms ORDER BY at_offset_ms) FROM resource_state_changes"
        " WHERE resource_id = :id",
        id=resource_id,
    )
    assert offsets == [30_000, 180_000]

    status_events = [
        event
        for event in await harness.events()
        if event.event_type is EventType.RESOURCE_STATUS_CHANGED
        and event.payload["resource_id"] == str(resource_id)
    ]
    assert [event.payload["new_status"] for event in status_events] == ["EN_ROUTE", "ON_SCENE"]
    assert all(event.actor_type is ActorType.SIMULATION for event in status_events)
    # `smp12` enters its availability window at 120 s, so the same tick also emits its
    # `make_available` — proof that the window is walked by the same scheduler (§10.7).
    window_events = [
        event
        for event in await harness.events()
        if event.event_type is EventType.RESOURCE_STATUS_CHANGED
        and event.payload["trigger"] == "make_available"
    ]
    assert [event.payload["callsign"] for event in window_events] == ["СМП-12"]


# ---------------------------------------------------------------------------------------------
# Idleness
# ---------------------------------------------------------------------------------------------


async def test_an_idle_tick_writes_nothing_at_all(
    harness: SimHarness, migrated_engine: AsyncEngine
) -> None:
    """Nothing fired, nothing folded, nothing moved ⇒ no row is touched and no event appended."""
    # The first tick folds the session-creation events, so it does write; the second is idle.
    await harness.advance_and_tick(1_000)

    async def snapshot() -> tuple[object, object, object, int]:
        return (
            await scalar(
                migrated_engine,
                "SELECT xmin::text FROM world_engine_states WHERE incident_id = :id",
                id=harness.incident_id,
            ),
            await scalar(
                migrated_engine,
                "SELECT updated_at FROM incident_world_states WHERE incident_id = :id",
                id=harness.incident_id,
            ),
            await scalar(
                migrated_engine,
                "SELECT updated_at FROM incident_caller_beliefs WHERE incident_id = :id",
                id=harness.incident_id,
            ),
            await count(migrated_engine, "session_events"),
        )

    before = await snapshot()
    result = await harness.advance_and_tick(1_000)
    assert result.ticked is True
    assert result.wrote is False
    assert await snapshot() == before


async def test_a_session_that_is_not_active_is_a_no_op(
    harness: SimHarness, migrated_engine: AsyncEngine
) -> None:
    """`tick_session` never touches a session outside `ACTIVE` (the runner may still hold it)."""
    async with harness.unit_of_work() as uow:
        session = await uow.sessions.get_for_update(harness.session_id)
        assert session is not None
        await uow.sessions.save(session.model_copy(update={"state": SessionState.COMPLETED}))
        await uow.commit()

    events_before = await count(migrated_engine, "session_events")
    result = await harness.advance_and_tick(600_000)
    assert result == (False, 0, (), 0, False)
    assert await count(migrated_engine, "session_events") == events_before


# ---------------------------------------------------------------------------------------------
# Serialisation by the session row lock
# ---------------------------------------------------------------------------------------------


async def test_two_concurrent_ticks_of_one_session_are_serialised(
    harness: SimHarness, migrated_engine: AsyncEngine
) -> None:
    """The §20.8 `FOR UPDATE` row lock means a TIMED event fires exactly once, not twice."""
    harness.clock.advance_ms(180_000)
    first, second = await asyncio.gather(
        harness.tick(harness.session_id), harness.tick(harness.session_id)
    )
    fired = [*first.fired_world_event_ids, *second.fired_world_event_ids]
    assert fired == ["fire_spreads"]

    triggered = [
        event
        for event in await harness.events()
        if event.event_type is EventType.WORLD_EVENT_TRIGGERED
    ]
    assert len(triggered) == 1


# ---------------------------------------------------------------------------------------------
# Simulated time
# ---------------------------------------------------------------------------------------------


async def test_time_scale_scales_simulated_time(migrated_engine: AsyncEngine) -> None:
    """`time_scale = 2` makes 90 s of wall clock 180 s of simulation (D7, `sim_ms`)."""
    clock = FakeClock()
    harness = await build_session(migrated_engine, clock=clock, time_scale=2.0)
    result = await harness.advance_and_tick(90_000)
    assert result.now_ms == 180_000
    assert result.fired_world_event_ids == ("fire_spreads",)
