"""The two leg-level facts the DDS slice computes, in one leaf module.

It imports the domain, two port *types* and the handoff's `primary_leg`, and nothing else — no
repository, no Unit of Work, no use case — so `app.application.sessions.get_snapshot` can build
the same work-item projection the DDS endpoints do without the two packages importing each other.

## `leg_for` — which assignment leg a unit hangs on (E9 analyst R4, manager ruling 3)

A handoff addressed to N services produces N `dds_assignments` legs of one work item. A unit the
DDS trainee selects has to be attached to exactly one of them, because
`RESOURCE_SELECTED.assignment_id` and `RESOURCE_DESELECTED.assignment_id` are non-null `uuid` in
the event catalog (§10.13) and because the stage guards are shown only the units attached to the
stage (R6). The rule is:

    the leg whose `service_type` is the unit's own, else the **primary** leg.

The second half is the decided one (manager ruling 3, analyst §3.3): **dispatching an off-service
unit is allowed.** The demo scenario makes the case concretely — the prefab handoff names
`FIRE_RESCUE` and `AMBULANCE` while the scenario lists `POLICE` and `GAS_SERVICE` as optional and
sends DDS a CRITICAL "gas cylinder" notification, so ППС-204, ДПС-31 and АГС-1 must be
dispatchable. Refusing would also contradict the design's stance that a trainee's mistakes are
*scored*, not blocked (`forbidden_resource_ids` and `penalty_per_excess` exist precisely because
the wrong unit can be sent), and it is not an INV 3 question at all: choosing to send an ambulance
is trainee judgment, not a read of hidden world truth.

**The cost, stated once here and in `openapi.yaml`: an `assignment_id` does not imply the unit's
service.** Nobody — the report, the scoring evaluators, the instructor overview — may use
leg → service as a shortcut for unit → service. That is why `RESOURCE_DISPATCHED` carries the
additive `service_type_by_resource` key: the unit's own service, per unit, from the board.

Isolating the rule in one function is deliberate: if the owner ever rules that a profile DDS may
only move its own service's units, the `else` branch becomes a `409` and nothing else changes.

## `project_legs` — the two resource lists §20.5 has no column for (analyst §7 #7)

`DDSAssignment.selected_resource_ids` and `dispatched_resource_ids` are fields of the §10.7 domain
type and of `DdsWorkItem`, and `dds_assignments` stores neither. They are projections, and they
come from two different places on purpose — see the function's own docstring.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.application.handoff.work_item import primary_leg
from app.application.ports.resource_repository import DispatchRecord, StoredResource
from app.domain.common.ids import AssignmentId, ResourceId
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.resources import EmergencyResource
from app.domain.enums import ResourceStatus
from app.domain.layers.handoff import HandoffSnapshot

__all__ = ["leg_for", "project_legs"]


def leg_for(
    resource: EmergencyResource,
    legs: Sequence[DDSAssignment],
    snapshot: HandoffSnapshot,
) -> DDSAssignment:
    """The leg `resource` attaches to: its own service's, else the primary one (see above)."""
    for leg in legs:
        if leg.service_type is resource.service_type:
            return leg
    return primary_leg(legs, snapshot)


def project_legs(
    legs: Sequence[DDSAssignment],
    board: Sequence[StoredResource],
    dispatched: Sequence[DispatchRecord],
) -> tuple[DDSAssignment, ...]:
    """Fill each leg's `selected_resource_ids` / `dispatched_resource_ids` (E9 analyst R7).

    Neither is a column of `dds_assignments`, so both are projected:

    * **selected** — the units currently attached to the leg and in `SELECTED`, from the live
      board. A deselected unit loses its attachment, so it drops out by construction;
    * **dispatched** — the leg's `trigger = 'dispatch'` rows in `resource_state_changes`, which is
      append-only. It must not come from the live attachment: closing the incident releases every
      unit, and "which units did this service receive" has to survive the release.
    """
    selected: dict[AssignmentId, list[ResourceId]] = {leg.assignment_id: [] for leg in legs}
    for stored in board:
        key = stored.assignment_id
        if key is None or key not in selected:
            continue
        if stored.resource.current_status is ResourceStatus.SELECTED:
            selected[key].append(stored.resource.resource_id)

    history: dict[AssignmentId, list[ResourceId]] = {leg.assignment_id: [] for leg in legs}
    for record in dispatched:
        bucket = history.get(record.assignment_id)
        if bucket is not None and record.resource_id not in bucket:
            bucket.append(record.resource_id)

    return tuple(
        leg.model_copy(
            update={
                "selected_resource_ids": tuple(selected[leg.assignment_id]),
                "dispatched_resource_ids": tuple(history[leg.assignment_id]),
            }
        )
        for leg in legs
    )
