"""`ResourceRepository` port — `emergency_resources` + `resource_state_changes` (§20.5, D5, D7).

Per-session resource instances are created from `scenario_versions.content.available_resources`
when the incident is instantiated (§20.5), so the repository always speaks in **pairs**: the
runtime `EmergencyResource` the engine moves, and the scenario-local `scenario_resource_id`
(`"ac2"`) an `AlterResourceAvailability` effect or a `ResourceSelector` names. §10.7's
`EmergencyResource` has no field for that string — it is a storage key, not a domain fact — so it
travels beside the resource in `StoredResource` and ends up in `WorldState.resource_keys`.

`record_state_change` appends the `resource_state_changes` audit row (§20.5) that every fired
transition owes. It is a separate operation from `save` on purpose: the board write and the audit
row are two different facts, and a tick that moves a resource owes exactly one row per transition
even when several transitions of one resource fire in one tick.

**Attachment** (`emergency_resources.assignment_id`) is the DDS side's column and has its own
operation, `attach`, so that the engine's `save` and a trainee's selection remain two
non-overlapping writes. A unit is attached at `select` and detached at `deselect`; the leg it
attaches to is decided in one place, `app.application.dds.leg_for` (E9 analyst R4). Because a
release nulls the live column, a leg's *history* is read back from `resource_state_changes`
(`dispatch_history`), which is append-only and carries the same `assignment_id`.

This port deliberately reaches **no** information layer: the DDS side holds it (E9) and must not
gain a path to `WorldTruth` through it (D3).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import AssignmentId, ResourceId, SessionId
from app.domain.dds.resources import EmergencyResource
from app.domain.enums import ResourceStatus

__all__ = [
    "DispatchRecord",
    "ResourceRepository",
    "ResourceStateChange",
    "StoredResource",
]


class StoredResource(BaseModel):
    """One `emergency_resources` row: the domain resource plus its scenario-local id (§20.5).

    `assignment_id` is the DDS leg the unit is attached to, or `None` for a unit nobody selected.
    §10.7's `EmergencyResource` has no field for it — it is an attachment, not a property of the
    vehicle — so it travels beside the resource exactly as `scenario_resource_id` does.
    """

    model_config = ConfigDict(frozen=True)

    scenario_resource_id: str
    resource: EmergencyResource
    assignment_id: AssignmentId | None = None


class ResourceStateChange(BaseModel):
    """One `resource_state_changes` row — the append-only resource audit of §20.5, SPEC §29.

    `assignment_id` is the leg the unit hung on when the transition fired (`None` for an
    unattached unit, e.g. a scenario unit becoming available on its own schedule), and
    `session_event_id` is the `session_events` row of the `RESOURCE_STATUS_CHANGED` that records
    it — both §20.5 columns, both written by the slice that appends the event.
    """

    model_config = ConfigDict(frozen=True)

    resource: EmergencyResource
    previous_status: ResourceStatus | None
    new_status: ResourceStatus
    trigger: str
    source_world_event_id: str | None = None
    at_offset_ms: int
    assignment_id: AssignmentId | None = None
    session_event_id: UUID | None = None


class DispatchRecord(BaseModel):
    """One historical `trigger = 'dispatch'` row: which unit was sent under which leg (§20.5)."""

    model_config = ConfigDict(frozen=True)

    assignment_id: AssignmentId
    resource_id: ResourceId
    at_offset_ms: int


@runtime_checkable
class ResourceRepository(Protocol):
    """`emergency_resources` and its `resource_state_changes` audit (§20.5)."""

    async def add_all(self, session_id: SessionId, resources: Sequence[StoredResource]) -> None:
        """Insert the session's whole resource board, as scenario instantiation produced it."""
        ...

    async def list_for_session(self, session_id: SessionId) -> list[StoredResource]:
        """Every resource of the session, ordered by `scenario_resource_id`."""
        ...

    async def save(self, session_id: SessionId, resource: EmergencyResource) -> None:
        """Write back one resource the engine moved: status, `eta`, `status_changed_at`."""
        ...

    async def attach(
        self,
        session_id: SessionId,
        resource_id: ResourceId,
        assignment_id: AssignmentId | None,
    ) -> None:
        """Set (or clear) `emergency_resources.assignment_id` — the DDS side's one column."""
        ...

    async def record_state_change(self, change: ResourceStateChange) -> None:
        """Append one `resource_state_changes` row for a fired transition (§20.5)."""
        ...

    async def dispatch_history(self, session_id: SessionId) -> list[DispatchRecord]:
        """Every `trigger = 'dispatch'` audit row of the session, oldest first (§20.5).

        This is what `DDSAssignment.dispatched_resource_ids` is projected from, per leg. The live
        `emergency_resources.assignment_id` cannot serve: `deselect` and the closure release null
        it, and "which units did this service receive" must survive both (E9 analyst R7).
        """
        ...
