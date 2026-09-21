"""INV 13 — "Refresh does not lose active incident state" (SPEC §42 item 13, §39; D7).

SPEC §39's rule is "never silently reset the simulation", and D7 spells out how: "sim time is
derived from the persisted `started_at` plus paused intervals, so a restart or refresh never resets
a session". This file proves the *backend* half of that — the half a browser refresh cannot test —
by doing what a restart actually does: running N ticks, **dropping every in-memory object**, and
rebuilding the repositories, the Unit of Work factory and the runner on a brand-new SQLAlchemy
engine against the same database.

After the restart, three things must hold:

1. simulated time continues from `started_at` — the next tick's `now_ms` is where the clock says it
   is, never back at `0`;
2. no already-fired `TIMED` event fires a second time;
3. the occurrence counters, the world-truth facts and the resource board are exactly what the dead
   process left behind.

The only thing that carries between the two halves is PostgreSQL and the wall clock. Nothing
process-monotonic is allowed to: `app.application.timebase` exists precisely because a
`time.monotonic()` origin dies with the process, and if `tick_session` ever read one, assertion 1
would come back as `now_ms == 0`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from app.application.simulation import SimulationRunner, TickSession
from app.application.testing.fakes import FakeClock, InMemoryEventPublisher, InMemoryRunnerLock
from app.db.session import create_session_factory
from app.domain.common.actors import ActorRef
from app.domain.common.ids import IncidentId, SessionId
from app.domain.enums import ActorType, ResourceStatus
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.simulation._support import SimHarness, build_session, scalar, truncate_all

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def clean_database(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    await truncate_all(migrated_engine)
    yield
    await truncate_all(migrated_engine)


@pytest.fixture
async def harness(migrated_engine: AsyncEngine) -> SimHarness:
    return await build_session(migrated_engine)


class RestartedBackend:
    """Everything the "new process" holds: a new engine, new repositories, a new runner.

    Only `database_url` and the wall clock survive the restart, which is the point.
    """

    def __init__(self, url: str, clock: FakeClock) -> None:
        self.engine = create_async_engine(url, poolclass=NullPool)
        self.clock = clock
        self.publisher = InMemoryEventPublisher()
        session_factory = create_session_factory(self.engine)

        def unit_of_work() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(session_factory, clock, self.publisher)

        self.unit_of_work = unit_of_work
        self.tick = TickSession(unit_of_work, clock)
        self.lock = InMemoryRunnerLock()
        self.runner = SimulationRunner(
            unit_of_work,
            self.tick,
            self.lock,
            instance_id="restarted-instance",
            tick_ms=1,
            lock_ttl_s=30,
            lock_refresh_s=10,
        )

    async def aclose(self) -> None:
        await self.runner.stop()
        await self.engine.dispose()


async def _occurrences(engine: AsyncEngine, incident_id: IncidentId) -> dict[str, int]:
    found = await scalar(
        engine,
        "SELECT bookkeeping -> 'occurrences' FROM world_engine_states WHERE incident_id = :id",
        id=incident_id,
    )
    return dict(found or {})


async def _world_event_count(
    engine: AsyncEngine, session_id: SessionId, world_event_id: str
) -> int:
    return int(
        await scalar(
            engine,
            "SELECT count(*) FROM session_events WHERE session_id = :sid"
            " AND event_type = :etype AND payload ->> 'world_event_id' = :wid",
            sid=session_id,
            etype=EventType.WORLD_EVENT_TRIGGERED.value,
            wid=world_event_id,
        )
    )


async def test_sim_time_and_bookkeeping_survive_a_full_restart(
    harness: SimHarness, migrated_engine: AsyncEngine
) -> None:
    """N ticks, drop everything, rebuild on a new engine, tick again (SPEC §39, §42 item 13)."""
    # --- the first process: run past the TIMED event at 180 s -------------------------------
    for _ in range(4):
        await harness.advance_and_tick(50_000)  # 50, 100, 150, 200 s
    assert await _world_event_count(migrated_engine, harness.session_id, "fire_spreads") == 1
    before = await _occurrences(migrated_engine, harness.incident_id)
    assert before["fire_spreads"] == 1
    world_before = await scalar(
        migrated_engine,
        "SELECT facts FROM incident_world_states WHERE incident_id = :id",
        id=harness.incident_id,
    )

    session_id, incident_id = harness.session_id, harness.incident_id
    url = migrated_engine.url.render_as_string(hide_password=False)
    # The clock is the wall clock: it is the one thing that legitimately crosses a restart.
    clock = harness.clock
    del harness  # every in-memory object of the first process is now unreachable

    # --- the second process ------------------------------------------------------------------
    restarted = RestartedBackend(url, clock)
    try:
        adopted = await restarted.runner.start()
        assert adopted == [session_id], "the restarted backend must re-adopt the ACTIVE session"

        clock.advance_ms(60_000)  # 260 s of simulated time
        result = await restarted.tick(session_id)

        # 1. simulated time continued from `started_at`; it did not reset to zero.
        assert result.now_ms == 260_000
        # 2. the TIMED event did not fire again.
        assert result.fired_world_event_ids == ()
        assert await _world_event_count(migrated_engine, session_id, "fire_spreads") == 1
        # 3. the bookkeeping and the world truth are what the dead process left.
        assert await _occurrences(migrated_engine, incident_id) == before
        assert (
            await scalar(
                migrated_engine,
                "SELECT facts FROM incident_world_states WHERE incident_id = :id",
                id=incident_id,
            )
            == world_before
        )
    finally:
        await restarted.aclose()


async def test_a_resource_keeps_walking_across_a_restart(
    harness: SimHarness, migrated_engine: AsyncEngine
) -> None:
    """Resource movement is scheduled off persisted offsets, so a restart does not rewind it."""
    resource_id = await harness.set_resource_status("ac1", ResourceStatus.DISPATCHED, 0)
    await harness.advance_and_tick(100_000)  # turnout 30 s done: EN_ROUTE
    board = await harness.resources()
    assert board["ac1"].resource.current_status is ResourceStatus.EN_ROUTE

    session_id = harness.session_id
    url = migrated_engine.url.render_as_string(hide_password=False)
    clock = harness.clock
    del harness

    restarted = RestartedBackend(url, clock)
    try:
        clock.advance_ms(100_000)  # 200 s: arrival was due at 180 s
        await restarted.tick(session_id)
        async with restarted.unit_of_work() as uow:
            stored = await uow.resources.list_for_session(session_id)
            await uow.commit()
        moved = next(entry for entry in stored if entry.resource.resource_id == resource_id)
        assert moved.resource.current_status is ResourceStatus.ON_SCENE
        # Stamped with its own due time, not with the tick that noticed it.
        assert moved.resource.status_changed_at_offset_ms == 180_000
    finally:
        await restarted.aclose()


async def test_the_restarted_backend_re_folds_the_event_index_from_the_log(
    harness: SimHarness, migrated_engine: AsyncEngine
) -> None:
    """`EventIndex` is not stored: a restart must rebuild it from `session_events` (D5)."""
    await harness.append(
        DomainEvent(
            event_type=EventType.HANDOFF_CREATED,
            actor=ActorRef(actor_type=ActorType.TRAINEE),
            monotonic_offset_ms=0,
            payload={"snapshot_id": "00000000-0000-4000-8000-000000000001"},
        )
    )
    await harness.advance_and_tick(10_000)  # folds the action and queues the delayed trigger

    session_id = harness.session_id
    url = migrated_engine.url.render_as_string(hide_password=False)
    clock = harness.clock
    del harness

    restarted = RestartedBackend(url, clock)
    try:
        clock.advance_ms(60_000)  # 70 s: the 60 s delay elapsed
        result = await restarted.tick(session_id)
        assert result.fired_world_event_ids == ("second_report_balcony",)
    finally:
        await restarted.aclose()
