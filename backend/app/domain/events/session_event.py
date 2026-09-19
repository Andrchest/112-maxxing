"""`SessionEvent`, `DomainEvent` (HLD `10-domain-model.md` §10.13, D5, SPEC §8).

Per the §10.1 module map, `events/session_event.py` holds these two classes and
`events/catalog.py` holds `EventSpec`/`EVENT_PAYLOAD_CATALOG` — the module map wins over §10.13's
code-block header, which names `catalog.py` for all four (ruling R2 of this task's brief; the
§10.13 header line itself is fixed to say so, see the report).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.actors import ActorRef
from app.domain.common.ids import EventId, SessionId, UserId
from app.domain.enums import ActorType
from app.domain.events.types import EventType


class SessionEvent(BaseModel):
    """A persisted, immutable audit-log row (§10.13, SPEC §8). `seq_no` is allocated on persist."""

    model_config = ConfigDict(frozen=True)

    id: EventId
    session_id: SessionId
    seq_no: int
    event_type: EventType
    timestamp_utc: datetime
    monotonic_offset_ms: int
    actor_type: ActorType
    actor_id: UserId | None = None
    correlation_id: UUID | None = None
    payload: Mapping[str, Any]


class DomainEvent(BaseModel):
    """What a pure domain method returns (§10.13); `seq_no` is assigned on persist, so it has no
    field here."""

    model_config = ConfigDict(frozen=True)

    event_type: EventType
    actor: ActorRef
    monotonic_offset_ms: int
    correlation_id: UUID | None = None
    payload: Mapping[str, Any]
