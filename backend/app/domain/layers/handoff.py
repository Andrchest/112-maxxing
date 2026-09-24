"""`HandoffSnapshot` — the immutable information actually sent to DDS (HLD `10-domain-model.md`
§10.3, §10.7, D3, SPEC §3, §10).

Written only by the handoff use case, copied from `OperatorCard` by value (not built here — see
`app/domain/layers/copies.py`, a later task). This module must not import any other layer module
(`world_truth`, `caller_belief`, `operator_card`) — see the structural test in
`backend/tests/unit/domain/layers/`.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import CardId, CardRevisionId, IncidentId, SnapshotId, UserId
from app.domain.common.values import FactValue
from app.domain.enums import ServiceId


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
