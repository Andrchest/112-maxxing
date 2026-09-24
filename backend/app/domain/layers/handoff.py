"""`HandoffSnapshot` — the immutable information actually sent to DDS (HLD `10-domain-model.md`
§10.3, §10.7, D3, SPEC §3, §10).

Written only by the handoff use case, copied from `OperatorCard` by value (not built here — see
`app/domain/layers/copies.py`, a later task). This module must not import any other layer module
(`world_truth`, `caller_belief`, `operator_card`) — see the structural test in
`backend/tests/unit/domain/layers/`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.actors import ActorRef
from app.domain.common.ids import CardId, CardRevisionId, IncidentId, SnapshotId, UserId
from app.domain.common.values import FactValue
from app.domain.enums import ServiceId
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType


class HandoffSnapshot(BaseModel):
    """Frozen; the DB trigger enforces the same immutability at rest (D3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: SnapshotId
    incident_id: IncidentId
    card_id: CardId
    card_revision_id: CardRevisionId
    card_values: Mapping[str, FactValue]
    recipient_services: tuple[ServiceId, ...]
    created_by_user_id: UserId
    created_at_offset_ms: int
    content_sha256: str


def handoff_created_event(
    snapshot: HandoffSnapshot,
    *,
    auto: Sequence[ServiceId],
    manual: Sequence[ServiceId],
    informed: Sequence[ServiceId],
    actor: ActorRef,
    at_offset_ms: int,
) -> DomainEvent:
    """`HANDOFF_CREATED` for `snapshot` (§10.13), with the I3 E2b′ additive keys (HLD 70 §70.7):
    `recipient_services` is the union auto ∪ manual the snapshot froze, and its automatic, manual
    and informed parts ride beside it. `TRAINEE` for `createHandoff`, `SIMULATION` for a schema-2
    prefab handoff."""
    return DomainEvent(
        event_type=EventType.HANDOFF_CREATED,
        actor=actor,
        monotonic_offset_ms=at_offset_ms,
        payload={
            "snapshot_id": UUID(str(snapshot.snapshot_id)),
            "incident_id": UUID(str(snapshot.incident_id)),
            "card_id": UUID(str(snapshot.card_id)),
            "card_revision_id": UUID(str(snapshot.card_revision_id)),
            "recipient_services": list(snapshot.recipient_services),
            "card_values": dict(snapshot.card_values),
            "content_sha256": snapshot.content_sha256,
            "at_offset_ms": at_offset_ms,
            "auto_recipient_services": list(auto),
            "manual_recipient_services": list(manual),
            "informed_services": list(informed),
        },
    )
