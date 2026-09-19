"""`RedisEventPublisher` — the `session:{session_id}:events` fan-out (HLD §40.6, D5).

One JSON envelope per event, published in `seq_no` order, **unredacted**: each WebSocket applies
its own role filter (§40.4, owed by E7). The channel name uses the session UUID in canonical
lowercase hyphenated form and never contains braces (§40.6 "Placeholder note").

Every failure is swallowed and logged. The Unit of Work calls this only after its transaction has
committed, so the events are already authoritative in PostgreSQL; a failed publish costs live
fan-out until the subscriber's next resume and nothing else (§40.6, SPEC §31).

TODO(E7): the `session:{id}:last_seq_no` read cache of §40.6 is written "on publish" by the same
publishers. It exists purely so a heartbeat frame does not hit PostgreSQL, and both the heartbeat
and the resume path that read it belong to E7's WebSocket handler, so E7 owes that write.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from redis.asyncio import Redis

from app.application.ports.event_publisher import EventEnvelope
from app.domain.common.ids import SessionId

__all__ = ["RedisEventPublisher", "session_events_channel"]

logger = logging.getLogger(__name__)


def session_events_channel(session_id: SessionId) -> str:
    """`session:{session_id}:events` (§40.6), with the UUID in canonical lowercase form."""
    return f"session:{str(session_id).lower()}:events"


class RedisEventPublisher:
    """`EventPublisher` over Redis pub/sub."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def publish(self, session_id: SessionId, envelopes: Sequence[EventEnvelope]) -> None:
        """Publish each envelope as one JSON message, in the order given."""
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
