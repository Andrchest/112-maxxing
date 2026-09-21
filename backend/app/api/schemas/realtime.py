"""`realtime` schemas — `openapi.yaml`'s `SessionEventEnvelope` and `SessionEventPage` (D8).

Both property-name sets are copied literally from the contract; `backend/tests/api/test_contract.py`
compares them against the YAML, so a rename on either side fails the suite.

`session_event_envelope_schema` is the *only* bridge between the application's `RealtimeEnvelope`
and the wire, and it is a straight `model_validate` of that envelope's JSON dump — which is what
makes §40.2's "byte-identical to what `GET /api/v1/sessions/{id}/events` returns" true by
construction rather than by care: the WebSocket writes the same dump under a `"type": "event"` key
and `backend/tests/api/realtime/test_envelope_parity.py` asserts the two are equal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.realtime.list_events import SessionEventPageView
from app.application.realtime.redaction import RealtimeEnvelope
from app.domain.enums import ActorType
from app.domain.events.types import EventType

__all__ = [
    "SessionEventEnvelopeSchema",
    "SessionEventPageSchema",
    "session_event_envelope_schema",
    "session_event_page_schema",
]


class SessionEventEnvelopeSchema(ApiModel):
    """`openapi.yaml`'s `SessionEventEnvelope`, property names literal.

    `payload` holds exactly the keys this role may see; `redacted_keys` names what §40.4 removed,
    "so the UI can render «скрыто» instead of implying absence", and is always empty for
    `INSTRUCTOR`.
    """

    seq_no: int = Field(ge=1)
    event_type: EventType
    timestamp_utc: datetime
    monotonic_offset_ms: int
    payload: dict[str, Any]
    actor_type: ActorType
    correlation_id: UUID | None = None
    redacted_keys: list[str] = Field(default_factory=list)


class SessionEventPageSchema(ApiModel):
    """`openapi.yaml`'s `SessionEventPage`."""

    items: list[SessionEventEnvelopeSchema]
    last_seq_no: int = Field(ge=0)
    has_more: bool


def session_event_envelope_schema(envelope: RealtimeEnvelope) -> SessionEventEnvelopeSchema:
    """One already-redacted envelope on the wire."""
    return SessionEventEnvelopeSchema.model_validate(envelope.model_dump(mode="json"))


def session_event_page_schema(view: SessionEventPageView) -> SessionEventPageSchema:
    """`listSessionEvents`' body."""
    return SessionEventPageSchema(
        items=[session_event_envelope_schema(envelope) for envelope in view.items],
        last_seq_no=view.last_seq_no,
        has_more=view.has_more,
    )
