"""`DDSAssignment` — the DDS work item created from a `HandoffSnapshot` (HLD `10-domain-model.md`
§10.7, D3).

One assignment per recipient service. Exposes no accessor to `WorldTruth`: per D3 the DDS
application service is constructed without a world-truth repository, so this type is never even
given one to hold.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import AssignmentId, IncidentId, ResourceId, RoleStageId, SnapshotId
from app.domain.enums import ClosureReason, DDSStageState, ServiceId


class DDSAssignment(BaseModel):
    """The DDS work item for one recipient service (§10.7)."""

    model_config = ConfigDict(extra="forbid")

    assignment_id: AssignmentId
    incident_id: IncidentId
    role_stage_id: RoleStageId
    snapshot_id: SnapshotId
    service_type: ServiceId
    state: DDSStageState
    received_at_offset_ms: int
    acknowledged_at_offset_ms: int | None = None
    dispatched_at_offset_ms: int | None = None
    closed_at_offset_ms: int | None = None
    closure_reason: ClosureReason | None = None
    selected_resource_ids: tuple[ResourceId, ...] = ()
    dispatched_resource_ids: tuple[ResourceId, ...] = ()
