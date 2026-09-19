"""`EventPublisher` port and its `EventEnvelope` (HLD `40-realtime-protocol.md` §40.6, D5).

The Redis channel `session:{session_id}:events` carries "one JSON envelope per event:
`{seq_no, event_type, timestamp_utc, monotonic_offset_ms, actor_type, actor_id, correlation_id,
payload}` — **unredacted**; each socket applies its own role filter" (§40.6). That is exactly
`EventEnvelope`.

HLD gap (see the task report): §40.2's WebSocket frame additionally carries `"type": "event"` and
`redacted_keys`. Those two keys belong to the socket frame, which is built per connection after
role redaction (§40.4); the fan-out payload of §40.6 is the eight-key object above, and this port
implements §40.6 literally. The WebSocket frame is owed by E7.

Publishing is *never* authoritative: PostgreSQL is (§40.6, SPEC §31). A failed publish therefore
never fails the transaction that produced the events — see `UnitOfWork`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import SessionId
from app.domain.enums import ActorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

__all__ = ["EventEnvelope", "EventPublisher", "envelope_of"]


class EventEnvelope(BaseModel):
    """The unredacted fan-out payload of one appended event (§40.6)."""

    model_config = ConfigDict(frozen=True)

    seq_no: int
    event_type: EventType
    timestamp_utc: datetime
    monotonic_offset_ms: int
    actor_type: ActorType
    actor_id: UUID | None = None
    correlation_id: UUID | None = None
    payload: Mapping[str, Any]


def envelope_of(event: SessionEvent) -> EventEnvelope:
    """Project a persisted `SessionEvent` onto its §40.6 fan-out envelope."""
    return EventEnvelope(
        seq_no=event.seq_no,
        event_type=event.event_type,
        timestamp_utc=event.timestamp_utc,
        monotonic_offset_ms=event.monotonic_offset_ms,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        correlation_id=event.correlation_id,
        payload=event.payload,
    )


@runtime_checkable
class EventPublisher(Protocol):
    """Fan-out of committed events to the realtime bus."""

    async def publish(self, session_id: SessionId, envelopes: Sequence[EventEnvelope]) -> None:
        """Publish `envelopes`, in `seq_no` order, to `session:{session_id}:events`.

        Called by the Unit of Work strictly *after* a successful commit (D5, §20.8). An
        implementation must never raise: Redis is non-authoritative, so a delivery failure is
        logged and swallowed rather than propagated.
        """
        ...
