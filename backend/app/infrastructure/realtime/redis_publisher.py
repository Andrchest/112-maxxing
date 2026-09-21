"""`RedisEventPublisher` — the `session:{session_id}:events` fan-out (HLD §40.6, D5).

One JSON envelope per event, published in `seq_no` order, **unredacted**: each WebSocket applies
its own role filter (§40.4, owed by E7). The channel name uses the session UUID in canonical
lowercase hyphenated form and never contains braces (§40.6 "Placeholder note").

Every failure is swallowed and logged. The Unit of Work calls this only after its transaction has
committed, so the events are already authoritative in PostgreSQL; a failed publish costs live
fan-out until the subscriber's next resume and nothing else (§40.6, SPEC §31).

The `session:{id}:last_seq_no` read cache of §40.6 is written here, "on publish", because §40.6
names "backend and voice-agent publishers" as its writers. It is refreshed once per `publish`
call, with the highest `seq_no` in the batch and `SESSION_CACHE_TTL_S`, and its failure is as
harmless as a failed publish: the WebSocket heartbeat that reads it falls back to `MAX(seq_no)`
in PostgreSQL (`app.application.realtime.event_stream`).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from redis.asyncio import Redis

from app.application.ports.event_publisher import EventEnvelope
from app.domain.common.ids import SessionId
from app.infrastructure.realtime.redis_last_seq_no_cache import RedisLastSeqNoCache

__all__ = ["DEFAULT_SESSION_CACHE_TTL_S", "RedisEventPublisher", "session_events_channel"]

DEFAULT_SESSION_CACHE_TTL_S = 3600
"""`SESSION_CACHE_TTL_S`'s default (§40.6), mirrored from `Settings.session_cache_ttl_s`."""

logger = logging.getLogger(__name__)


def session_events_channel(session_id: SessionId) -> str:
    """`session:{session_id}:events` (§40.6), with the UUID in canonical lowercase form."""
    return f"session:{str(session_id).lower()}:events"


class RedisEventPublisher:
    """`EventPublisher` over Redis pub/sub."""

    def __init__(self, client: Redis, cache_ttl_s: int = DEFAULT_SESSION_CACHE_TTL_S) -> None:
        self._client = client
        self._cache = RedisLastSeqNoCache(client, cache_ttl_s)

    async def publish(self, session_id: SessionId, envelopes: Sequence[EventEnvelope]) -> None:
        """Publish each envelope as one JSON message, in the order given.

        Then refresh `session:{session_id}:last_seq_no` with the batch's highest `seq_no` (§40.6).
        The order is deliberate: the key is a *read cache* for heartbeats, so it must never claim
        a number the bus has not yet carried.
        """
        if not envelopes:
            return
        channel = session_events_channel(session_id)
        for envelope in envelopes:
            try:
                await self._client.publish(channel, envelope.model_dump_json())
            except Exception:  # Redis is non-authoritative (§40.6, SPEC §31)
                logger.exception(
                    "publishing seq_no %d to %s failed; the event is committed in PostgreSQL "
                    "and reaches the client on its next resume",
                    envelope.seq_no,
                    channel,
                )
        await self._cache.set(session_id, max(envelope.seq_no for envelope in envelopes))
