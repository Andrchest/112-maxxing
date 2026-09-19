"""`SqlAlchemyUnitOfWork`: one transaction, publish strictly after commit (D5, §20.8, §40.6).

Three properties are asserted here:

* a rollback leaves `next_seq_no` and the log exactly as they were and publishes nothing;
* a commit publishes the envelopes in `seq_no` order to `session:{id}:events` — checked with a real
  Redis subscriber, not a fake;
* a publisher failure neither rolls back nor loses the committed events (Redis is
  non-authoritative, §40.6).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import pytest
import redis.asyncio as redis_asyncio
from app.application.testing.fakes import FakeClock, InMemoryEventPublisher
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.realtime.redis_publisher import (
    RedisEventPublisher,
    session_events_channel,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.persistence.conftest import make_event

pytestmark = pytest.mark.integration

_SUBSCRIBE_TIMEOUT_S = 5.0


async def test_rollback_changes_nothing_and_publishes_nothing(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    publisher: InMemoryEventPublisher,
    session_id: SessionId,
    migrated_engine: AsyncEngine,
) -> None:
    async with unit_of_work() as uow:
        appended = await uow.events.append(session_id, [make_event(), make_event()])
        assert [event.seq_no for event in appended] == [1, 2]
        # Leaving the block without commit() rolls back.

    async with migrated_engine.connect() as connection:
        count = (
            await connection.execute(
                text("SELECT count(*) FROM session_events WHERE session_id = :sid"),
                {"sid": session_id},
            )
        ).scalar_one()
        next_seq_no = (
            await connection.execute(
                text("SELECT next_seq_no FROM simulation_sessions WHERE id = :sid"),
                {"sid": session_id},
            )
        ).scalar_one()

    assert count == 0
    assert next_seq_no == 1
    assert publisher.published == []
    assert publisher.calls == 0


async def test_explicit_rollback_discards_the_pending_envelopes(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    publisher: InMemoryEventPublisher,
    session_id: SessionId,
) -> None:
    async with unit_of_work() as uow:
        await uow.events.append(session_id, [make_event()])
        await uow.rollback()
        await uow.commit()  # a commit after a rollback has nothing to publish

    assert publisher.published == []


async def test_commit_publishes_every_envelope_in_seq_order(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    publisher: InMemoryEventPublisher,
    session_id: SessionId,
) -> None:
    async with unit_of_work() as uow:
        await uow.events.append(
            session_id,
            [
                make_event(EventType.SESSION_STARTED, 0),
                make_event(EventType.ROLE_STAGE_STARTED, 10),
                make_event(EventType.CARD_FIELD_CHANGED, 20),
            ],
        )
        await uow.commit()

    envelopes = publisher.envelopes_for(session_id)
    assert [envelope.seq_no for envelope in envelopes] == [1, 2, 3]
    assert [envelope.event_type for envelope in envelopes] == [
        EventType.SESSION_STARTED,
        EventType.ROLE_STAGE_STARTED,
        EventType.CARD_FIELD_CHANGED,
    ]


async def test_commit_publishes_to_the_real_redis_channel(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis_asyncio.Redis,
    session_id: SessionId,
) -> None:
    channel = session_events_channel(session_id)
    assert channel == f"session:{session_id}:events"

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    try:
        # Redis delivers only to subscribers present at publish time, so subscribe first.
        await _drain_subscribe_confirmation(pubsub)

        async with SqlAlchemyUnitOfWork(
            session_factory, FakeClock(), RedisEventPublisher(redis_client)
        ) as uow:
            await uow.events.append(
                session_id,
                [
                    make_event(EventType.SESSION_STARTED, 0),
                    make_event(EventType.CARD_FIELD_CHANGED, 500, field_path="location.address"),
                ],
            )
            await uow.commit()

        received = [json.loads(message) for message in await _receive(pubsub, 2)]
    finally:
        await pubsub.aclose()

    assert [message["seq_no"] for message in received] == [1, 2]
    assert [message["event_type"] for message in received] == [
        "SESSION_STARTED",
        "CARD_FIELD_CHANGED",
    ]
    assert received[1]["payload"] == {"field_path": "location.address"}
    # §40.6: the envelope is the eight-key, unredacted object.
    assert set(received[0]) == {
        "seq_no",
        "event_type",
        "timestamp_utc",
        "monotonic_offset_ms",
        "actor_type",
        "actor_id",
        "correlation_id",
        "payload",
    }


async def test_nothing_is_published_to_redis_when_the_transaction_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis_asyncio.Redis,
    session_id: SessionId,
) -> None:
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(session_events_channel(session_id))
    try:
        await _drain_subscribe_confirmation(pubsub)

        async with SqlAlchemyUnitOfWork(
            session_factory, FakeClock(), RedisEventPublisher(redis_client)
        ) as uow:
            await uow.events.append(session_id, [make_event()])

        assert await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0) is None
    finally:
        await pubsub.aclose()


async def test_a_publisher_failure_never_loses_the_committed_events(
    session_factory: async_sessionmaker[AsyncSession],
    session_id: SessionId,
    migrated_engine: AsyncEngine,
) -> None:
    """§40.6: Redis is non-authoritative, so a broken publisher may not fail the commit."""
    broken = InMemoryEventPublisher(fail_with=RuntimeError("redis is down"))
    async with SqlAlchemyUnitOfWork(session_factory, FakeClock(), broken) as uow:
        await uow.events.append(session_id, [make_event(), make_event()])
        await uow.commit()

    assert broken.calls == 1
    assert broken.published == []
    async with migrated_engine.connect() as connection:
        count = (
            await connection.execute(
                text("SELECT count(*) FROM session_events WHERE session_id = :sid"),
                {"sid": session_id},
            )
        ).scalar_one()
    assert count == 2


async def _drain_subscribe_confirmation(pubsub: redis_asyncio.client.PubSub) -> None:
    await pubsub.get_message(timeout=_SUBSCRIBE_TIMEOUT_S)


async def _receive(pubsub: redis_asyncio.client.PubSub, count: int) -> list[str]:
    async def collect() -> list[str]:
        messages: list[str] = []
        while len(messages) < count:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None:
                messages.append(message["data"])
        return messages

    return await asyncio.wait_for(collect(), timeout=_SUBSCRIBE_TIMEOUT_S)
