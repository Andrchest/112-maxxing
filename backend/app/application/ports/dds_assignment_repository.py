"""`DDSAssignmentRepository` port — `dds_assignments` (HLD `20-db-schema.md` §20.5, §10.7, D3).

The DDS side of D3, expressed the same way the four layer ports are: one module, one table, one
domain type. What makes this port safe to hand to the DDS application services is what it does
**not** mention — there is no `WorldTruth`, no `CallerBelief` and no `OperatorCard` anywhere in
its imports or its signatures, so a component holding it has no path to them (SPEC §42 test 3).
`backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py` asserts exactly that.

Three operations, which are the three the handoff and DDS slices need:

* `add_all` — the handoff use case inserts the whole fan-out at once. One `DDSAssignment` row per
  recipient service is created in a single statement inside the handoff's Unit of Work, because
  the legs of one handoff either all exist or none does;
* `list_for_stage` — every leg of one DDS `RoleStage`, in `service_type` order of the snapshot's
  `recipient_services`. The work-item projection and the DDS commands read the legs this way,
  never by assignment id: the API has no way to address one leg (E9 analyst §2);
* `save` — write one leg back after the stage moved. `role_stages.state` is the authority and
  `dds_assignments.state` mirrors it, so every leg of a stage is saved in the same transaction as
  the stage transition that changed it (E9 analyst R1).

HLD gap (analyst §7 #7): `DDSAssignment.selected_resource_ids` / `dispatched_resource_ids` are
fields of the §10.7 domain type and of `DdsWorkItem`, but §20.5 gives `dds_assignments` no column
for either — they are projections over `emergency_resources` / `resource_state_changes`. This
port therefore neither writes nor reads them: a leg comes back with both tuples empty, and the
slice that owns resources (E9-B) fills them in the projection.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.domain.common.ids import RoleStageId
from app.domain.dds.assignment import DDSAssignment

__all__ = ["DDSAssignmentRepository"]


@runtime_checkable
class DDSAssignmentRepository(Protocol):
    """`dds_assignments` — the N per-service legs of one DDS work item (§20.5, §10.7)."""

    async def add_all(self, assignments: Sequence[DDSAssignment]) -> None:
        """Insert the whole fan-out of one handoff, in the order it was given."""
        ...

    async def list_for_stage(self, role_stage_id: RoleStageId) -> list[DDSAssignment]:
        """Every leg of this DDS `RoleStage`, ordered by `received_at_offset_ms` then id."""
        ...

    async def save(self, assignment: DDSAssignment) -> None:
        """Write one leg back: its mirrored `state` and its own per-leg timestamps."""
        ...
