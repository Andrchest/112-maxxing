"""`DdsWorkItem` — the stage-wide projection the DDS trainee reads (§10.7, SPEC §10, §11; D3).

**One work item, N legs** (E9 analyst §1, rule R3). SPEC is singular everywhere ("Create the DDS
work item from the snapshot", "incoming work item"); the HLD is plural in four places, the first
of which is "one assignment per recipient service". Both hold if the work item is owned by the
DDS `RoleStage` and addressed to N services, and each `DDSAssignment` row is that work item's leg
for one receiving service. This module builds the singular projection over the legs:

* `assignment_id`, `service_type` come from the **primary leg** — the one whose `service_type` is
  `recipient_services[0]`. These are the only two fields where "primary" shows at all;
* `incident_id`, `role_stage_id`, `snapshot_id`, `card_values`, `recipient_services`,
  `handoff_content_sha256` and `missing_field_paths` come from the snapshot;
* `state`, `received_at`, `acknowledged_at`, `closed_at` and `closure_reason` come from any leg —
  they are identical across the legs by construction (E9 analyst R1/R1b);
* `dispatched_at_offset_ms` is the **minimum** over the legs that have one, i.e. when the stage
  first left `RESOURCE_SELECTION`;
* `selected_resource_ids` and `dispatched_resource_ids` are the **union** over the legs.

The min/union are what make the choice of primary leg inert: an ambulance selected under the
AMBULANCE leg still shows up for a trainee whose work item is identified by the FIRE_RESCUE leg,
so E10's action gating cannot break on the operator's click order.

The *instructor's* `InstructorSessionOverview.assignments` and the report's `dds_decisions` are
the N legs verbatim — same schema, two documented readings (see `openapi.yaml`'s `DdsWorkItem`
description). E16 built the report's reading (`app.application.reports.dds_decisions`) and E17
built the instructor's (`app.application.instructor.get_overview._assignments`); this module
builds the trainee's reading only.

**D3, structurally.** The inputs are a `HandoffSnapshot` and a sequence of `DDSAssignment`, and
there is no third. Nothing here imports `WorldTruth`, `CallerBelief` or `OperatorCard`, and no
function takes a repository, so no value the operator did not enter can reach a DDS screen —
which is what `backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py` asserts on
this module's source, not on its behaviour. `CARD_FIELDS` is imported for `missing_field_paths`
and is a *specification* of the card's shape, not card data: it is the same public field list
`getOperatorCard` already ships to every client.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import ResourceId
from app.domain.common.values import FactValue
from app.domain.dds.assignment import DDSAssignment
from app.domain.enums import ClosureReason, DDSStageState, ServiceId
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import CARD_FIELDS

__all__ = [
    "DdsWorkItemView",
    "legs_in_recipient_order",
    "missing_field_paths",
    "primary_leg",
    "work_item_view",
]

REQUIRED_FOR_HANDOFF: tuple[str, ...] = tuple(
    spec.field_path for spec in CARD_FIELDS if spec.required_for_handoff
)
"""The `CARD_FIELDS` paths marked `required_for_handoff`, in §10.6 order."""


class DdsWorkItemView(BaseModel):
    """`openapi.yaml`'s `DdsWorkItem`, property names literal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assignment_id: UUID
    incident_id: UUID
    role_stage_id: UUID
    snapshot_id: UUID
    service_type: ServiceId
    state: DDSStageState
    card_values: dict[str, FactValue]
    recipient_services: tuple[ServiceId, ...]
    handoff_content_sha256: str
    received_at_offset_ms: int
    acknowledged_at_offset_ms: int | None
    dispatched_at_offset_ms: int | None
    closed_at_offset_ms: int | None
    closure_reason: ClosureReason | None
    selected_resource_ids: tuple[UUID, ...]
    dispatched_resource_ids: tuple[UUID, ...]
    missing_field_paths: tuple[str, ...]


def missing_field_paths(snapshot: HandoffSnapshot) -> tuple[str, ...]:
    """The `required_for_handoff` `CARD_FIELDS` paths the snapshot leaves empty (SPEC §10).

    "If the 112 operator omitted a critical fact, the omission propagates." This names the gap; it
    never fills it, and there is no input here from which it could be filled. A path counts as
    empty when the snapshot has no entry for it, or its value is `None`, the empty string or an
    empty list — a field the trainee cleared is as absent as one they never touched.
    """
    return tuple(path for path in REQUIRED_FOR_HANDOFF if _is_empty(snapshot.card_values.get(path)))


def legs_in_recipient_order(
    snapshot: HandoffSnapshot, legs: Sequence[DDSAssignment]
) -> tuple[DDSAssignment, ...]:
    """The legs in `snapshot.recipient_services` order — the order the operator chose in.

    The storage layer cannot supply it: every leg of one handoff shares `received_at_offset_ms`,
    so a `dds_assignments` query can only fall back to the row id, which is arbitrary. The
    snapshot carries the order, so the ordering is applied here, once, for every reader that
    wants "who this went to, first choice first" (the instructor overview and the report do).
    A leg whose service is somehow not in the list is kept, last, rather than dropped.
    """
    order = {service: index for index, service in enumerate(snapshot.recipient_services)}
    return tuple(sorted(legs, key=lambda leg: order.get(leg.service_type, len(order))))


def primary_leg(legs: Sequence[DDSAssignment], snapshot: HandoffSnapshot) -> DDSAssignment:
    """The leg of `recipient_services[0]`, which is the work item's identity (R3).

    Falls back to the first leg given when — which cannot happen for a fan-out this codebase
    created — no leg matches, so a projection never raises over an id choice that is arbitrary
    anyway.
    """
    if not legs:
        raise ValueError(
            f"handoff snapshot {snapshot.snapshot_id} has no DDS assignment leg to project"
        )
    if snapshot.recipient_services:
        first = snapshot.recipient_services[0]
        for leg in legs:
            if leg.service_type == first:
                return leg
    return legs[0]


def work_item_view(snapshot: HandoffSnapshot, legs: Sequence[DDSAssignment]) -> DdsWorkItemView:
    """Project one `DdsWorkItem` from the snapshot and its legs — and from nothing else."""
    primary = primary_leg(legs, snapshot)
    dispatched_at = [
        leg.dispatched_at_offset_ms for leg in legs if leg.dispatched_at_offset_ms is not None
    ]
    return DdsWorkItemView(
        assignment_id=UUID(str(primary.assignment_id)),
        incident_id=UUID(str(snapshot.incident_id)),
        role_stage_id=UUID(str(primary.role_stage_id)),
        snapshot_id=UUID(str(snapshot.snapshot_id)),
        service_type=primary.service_type,
        state=primary.state,
        card_values=dict(snapshot.card_values),
        recipient_services=tuple(snapshot.recipient_services),
        handoff_content_sha256=snapshot.content_sha256,
        received_at_offset_ms=primary.received_at_offset_ms,
        acknowledged_at_offset_ms=primary.acknowledged_at_offset_ms,
        dispatched_at_offset_ms=min(dispatched_at) if dispatched_at else None,
        closed_at_offset_ms=primary.closed_at_offset_ms,
        closure_reason=primary.closure_reason,
        selected_resource_ids=_union(leg.selected_resource_ids for leg in legs),
        dispatched_resource_ids=_union(leg.dispatched_resource_ids for leg in legs),
        missing_field_paths=missing_field_paths(snapshot),
    )


def _union(id_lists: Iterable[Sequence[ResourceId]]) -> tuple[UUID, ...]:
    """The legs' resource ids, deduplicated, in first-seen order."""
    seen: list[UUID] = []
    for ids in id_lists:
        for resource_id in ids:
            value = UUID(str(resource_id))
            if value not in seen:
                seen.append(value)
    return tuple(seen)


def _is_empty(value: FactValue) -> bool:
    return value is None or value == "" or value == []
