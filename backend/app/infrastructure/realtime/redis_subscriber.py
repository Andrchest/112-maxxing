"""`RedisEventSubscriber` — the live tail of `session:{session_id}:events` (HLD §40.3, §40.6).

Entering `subscribe(session_id)` completes the Redis `SUBSCRIBE` **and** starts the reader task
before it returns, which is §40.3 step 2 ("subscribes […] **first** and buffers incoming messages
in memory"). Everything published from that moment lands in an unbounded in-process
`asyncio.Queue`; the replay then reads PostgreSQL knowing that nothing can fall between the two.

Leaving the context is the resource-hygiene half: the reader task is cancelled *and awaited*, the
channel is unsubscribed and the pub/sub connection is closed, so `PUBSUB NUMSUB
session:{id}:events` returns to `0` when the last socket for a session goes away. Nothing here
outlives the `async with`.

A malformed message is logged and dropped rather than raised: Redis is a fan-out bus and not
authoritative (§40.6), so a message the envelope model rejects costs the client one live event,
which its next `resume` replays from PostgreSQL.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from pydantic import ValidationError
from redis.asyncio import Redis

from app.application.ports.event_publisher import EventEnvelope
from app.domain.common.ids import SessionId
from app.infrastructure.realtime.redis_publisher import session_events_channel

__all__ = ["RedisEventSubscriber", "RedisEventSubscription"]

logger = logging.getLogger(__name__)


class RedisEventSubscription:
    """One subscribed channel plus the task draining it into a queue (`EventSubscription`)."""

    def __init__(self, channel: str) -> None:
        self._channel = channel
        self._queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()

    def offer(self, raw: str | bytes) -> None:
        """Parse one pub/sub message and buffer it; a malformed one is dropped and logged."""
        try:
            self._queue.put_nowait(EventEnvelope.model_validate_json(raw))
        except ValidationError:
            logger.warning(
                "dropping a malformed envelope on %s; the client recovers it on its next resume",
                self._channel,
            )

    async def get(self) -> EventEnvelope:
        """The next buffered or live envelope, waiting when the buffer is empty."""
        return await self._queue.get()

    def drain(self) -> list[EventEnvelope]:
        """Everything buffered so far, without waiting (§40.3 step 4)."""
        drained: list[EventEnvelope] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                return drained


class RedisEventSubscriber:
    """`EventSubscriber` over Redis pub/sub."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    @asynccontextmanager
    async def subscribe(self, session_id: SessionId) -> AsyncIterator[RedisEventSubscription]:
        """Subscribe, buffer, and release everything on the way out."""
        channel = session_events_channel(session_id)
        subscription = RedisEventSubscription(channel)
        pubsub = self._client.pubsub()
        await pubsub.subscribe(channel)
        reader = asyncio.create_task(
            _read_into(pubsub, subscription), name=f"ws-subscribe:{channel}"
        )
        try:
            yield subscription
        finally:
            reader.cancel()
            # Awaited, not merely cancelled: a cancelled-but-unawaited task is exactly the leak
            # `test_resource_hygiene.py` counts with `asyncio.all_tasks()`.
            with suppress(asyncio.CancelledError):
                await reader
            try:
                await pubsub.unsubscribe(channel)
            finally:
                await pubsub.aclose()


async def _read_into(pubsub: object, subscription: RedisEventSubscription) -> None:
    """Pump `pubsub` messages into the subscription's buffer until cancelled."""
    get_message = pubsub.get_message  # type: ignore[attr-defined]
    while True:
        message = await get_message(ignore_subscribe_messages=True, timeout=None)
        if message is None:
            continue
        data = message.get("data")
        if isinstance(data, str | bytes):
            subscription.offer(data)
