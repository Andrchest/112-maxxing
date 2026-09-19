"""`SqlAlchemyEventStore` against real PostgreSQL (HLD `20-db-schema.md` §20.6, §20.8, D5).

The concurrency test is the one that matters: `N_APPENDERS` tasks on **separate connections**
append to **one** session at the same time, and the resulting `seq_no` set must be exactly
`1 .. N_APPENDERS * APPENDS_EACH` — no gap, no duplicate. That is only true because §20.8 takes the
`simulation_sessions` row lock before it reads `next_seq_no`.

It was proved to bite by replacing `_allocate` with a read-then-write allocation (a plain
`SELECT next_seq_no` with no `FOR UPDATE`, writing back the absolute value `read + event_count`);
the test then failed with a duplicate-key violation of `uq_session_events_session_seq`. The literal
§20.8 protocol was restored afterwards — see the task report for both runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import UUID

import pytest
from app.application.testing.fakes import FakeClock, InMemoryEventPublisher
from app.db.session import create_session_factory
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType
from app.domain.events.types import EventType
from app.infrastructure.persistence.event_store import SqlAlchemyEventStore, UnknownSessionError
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.persistence.conftest import make_event

pytestmark = pytest.mark.integration

N_APPENDERS = 8
APPENDS_EACH = 25


async def test_append_allocates_contiguous_seq_nos_and_read_returns_them_in_order(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], session_id: SessionId
) -> None:
    async with unit_of_work() as uow:
        appended = await uow.events.append(
            session_id,
            [make_event(monotonic_offset_ms=offset) for offset in (0, 120, 240)],
        )
        await uow.commit()

    assert [event.seq_no for event in appended] == [1, 2, 3]

    async with unit_of_work() as uow:
        read_back = await uow.events.read(session_id)
    assert [event.seq_no for event in read_back] == [1, 2, 3]
    assert [event.monotonic_offset_ms for event in read_back] == [0, 120, 240]
    assert [event.id for event in read_back] == [event.id for event in appended]


async def test_timestamp_utc_comes_from_the_injected_clock(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: InMemoryEventPublisher,
    session_id: SessionId,
) -> None:
    clock = FakeClock()
    pinned = clock.now()
    async with SqlAlchemyUnitOfWork(session_factory, clock, publisher) as uow:
        await uow.events.append(session_id, [make_event()])
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory, clock, publisher) as uow:
        stored = await uow.events.read(session_id)
    assert stored[0].timestamp_utc == pinned


async def test_read_honours_after_seq_no_and_limit(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], session_id: SessionId
) -> None:
    async with unit_of_work() as uow:
        await uow.events.append(session_id, [make_event() for _ in range(5)])
        await uow.commit()

    async with unit_of_work() as uow:
        assert [e.seq_no for e in await uow.events.read(session_id, after_seq_no=2)] == [3, 4, 5]
        assert [e.seq_no for e in await uow.events.read(session_id, limit=2)] == [1, 2]


async def test_append_of_nothing_allocates_nothing(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    migrated_engine: AsyncEngine,
) -> None:
    async with unit_of_work() as uow:
        assert await uow.events.append(session_id, []) == []
        await uow.commit()
    assert await _next_seq_no(migrated_engine, session_id) == 1


async def test_append_to_an_unknown_session_is_refused(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    unknown = SessionId(UUID("00000000-0000-0000-0000-0000000000ff"))
    async with unit_of_work() as uow:
        with pytest.raises(UnknownSessionError):
            await uow.events.append(unknown, [make_event()])


async def test_event_columns_are_persisted_as_spec_8_says(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], session_id: SessionId
) -> None:
    event = make_event(EventType.WORLD_EVENT_TRIGGERED, 4321, world_event_id="we-1")
    async with unit_of_work() as uow:
        await uow.events.append(session_id, [event])
        await uow.commit()

    async with unit_of_work() as uow:
        stored = (await uow.events.read(session_id))[0]
    assert stored.session_id == session_id
    assert stored.event_type is EventType.WORLD_EVENT_TRIGGERED
    assert stored.monotonic_offset_ms == 4321
    assert stored.actor_type is ActorType.SYSTEM
    assert stored.actor_id is None
    assert stored.correlation_id == event.correlation_id
    assert stored.payload == {"world_event_id": "we-1"}


async def test_concurrent_appenders_yield_a_gap_free_unique_sequence(
    migrated_engine: AsyncEngine, session_id: SessionId
) -> None:
    """§20.8: the `FOR UPDATE` row lock serialises concurrent appenders."""
    total = N_APPENDERS * APPENDS_EACH

    async def appender() -> None:
        # Its own session factory, hence its own connection (`migrated_engine` uses NullPool).
        factory = create_session_factory(migrated_engine)
        for _ in range(APPENDS_EACH):
            async with SqlAlchemyUnitOfWork(factory, FakeClock(), InMemoryEventPublisher()) as uow:
                await uow.events.append(session_id, [make_event()])
                await uow.commit()

    await asyncio.gather(*(appender() for _ in range(N_APPENDERS)))

    async with migrated_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT seq_no FROM session_events WHERE session_id = :session_id"
                    " ORDER BY seq_no"
                ),
                {"session_id": session_id},
            )
        ).scalars()
        seq_nos = list(rows)

    assert seq_nos == list(range(1, total + 1)), "gap or duplicate in the seq_no sequence"
    assert len(set(seq_nos)) == total
    assert await _next_seq_no(migrated_engine, session_id) == total + 1


async def test_a_direct_store_appends_inside_the_callers_transaction(
    session_factory: async_sessionmaker[AsyncSession], session_id: SessionId
) -> None:
    """The store never commits on its own: an uncommitted append is invisible elsewhere."""
    clock = FakeClock()
    async with session_factory() as session:
        store = SqlAlchemyEventStore(session, clock)
        await store.append(session_id, [make_event()])
        async with session_factory() as other:
            other_store = SqlAlchemyEventStore(other, clock)
            assert await other_store.read(session_id) == []
        await session.rollback()

    async with session_factory() as session:
        assert await SqlAlchemyEventStore(session, clock).read(session_id) == []


async def _next_seq_no(engine: AsyncEngine, session_id: SessionId) -> int:
    async with engine.connect() as connection:
        value = (
            await connection.execute(
                text("SELECT next_seq_no FROM simulation_sessions WHERE id = :session_id"),
                {"session_id": session_id},
            )
        ).scalar_one()
    return int(value)
