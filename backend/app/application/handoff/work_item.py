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

**Field specs from the pack (I3 E3a, HLD 70 §70.5.4).** The work item carries `card_schema` and
`field_specs` — the specs of the card schema of the session's reference pack, so the ДДС side
renders the snapshot's values (and their option labels) from data, not from a hard-coded label
list (`with_card_schema`). The pack is the one `SESSION_CREATED.reference_pack` recorded
(`app.application.reference.card_schemas.pack_card_schema`): the log and the reference catalog,
never the `ScenarioVersion` (INV 3).

**«в службу 03 передаются только первые 100 символов» (I7 E55).** The card instruction's note on
«Описание со слов заявителя» (instr ¶257): `for_viewer` cuts `description.text` to its first
100 characters for a ДДС trainee whose own legs are all the 03 service (`AMBULANCE`). Everyone
else — another service, a trainee who plays every (unbound) leg, the instructor — reads it whole.
The snapshot itself is untouched (its `content_sha256` still covers the full text).

**«ЧС» / «ЧП» (I7 E55, owner decision 2026-09-29 Q9).** The ДДС screen's two marks with the
pencil are the ДДС's own, not the 112 card's: `setDdsCardMarks` appends `DDS_CARD_MARKS_SET`, and
`dds_marks_of` folds the log into `DdsWorkItemView.dds_marks` (the last event wins; both `false`
before the first). Read from the log only — like everything else here, never world truth.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.application.reference.card_schemas import CardFieldSpecView, field_spec_views
from app.domain.common.ids import ResourceId, UserId
from app.domain.common.values import FactValue
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.response import LegResponder
from app.domain.enums import ClosureReason, DDSStageState, ServiceId
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.card_schema import CardSchema
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import CARD_FIELDS, CARD_SCHEMA_V1

__all__ = [
    "DESCRIPTION_LIMIT_CHARS",
    "DdsMarksView",
    "DdsWorkItemView",
    "dds_marks_of",
    "for_viewer",
    "legs_in_recipient_order",
    "missing_field_paths",
    "primary_leg",
    "with_card_schema",
    "with_dds_marks",
    "work_item_view",
]

REQUIRED_FOR_HANDOFF: tuple[str, ...] = tuple(
    spec.field_path for spec in CARD_FIELDS if spec.required_for_handoff
)
"""The `CARD_FIELDS` paths marked `required_for_handoff`, in §10.6 order."""

DESCRIPTION_PATH = "description.text"
DESCRIPTION_LIMITED_SERVICE = ServiceId("AMBULANCE")
DESCRIPTION_LIMIT_CHARS = 100
"""instr ¶257: «в службу 03 передаются только первые 100 символов» (I7 E55)."""


class DdsMarksView(BaseModel):
    """`openapi.yaml`'s `DdsCardMarks` — the ДДС screen's «ЧС» / «ЧП» marks (I7 E55)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chs: bool = False
    chp: bool = False


def dds_marks_of(events: Iterable[SessionEvent]) -> DdsMarksView:
    """The marks the last `DDS_CARD_MARKS_SET` of `events` set; both `False` before the first."""
    marks = DdsMarksView()
    for event in events:
        if event.event_type is EventType.DDS_CARD_MARKS_SET:
            marks = DdsMarksView(
                chs=bool(event.payload.get("chs")), chp=bool(event.payload.get("chp"))
            )
    return marks


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
    card_schema: str = "v1"
    field_specs: tuple[CardFieldSpecView, ...] = ()
    dds_marks: DdsMarksView = DdsMarksView()
    """(I7 E55) The ДДС's «ЧС» / «ЧП» marks — `with_dds_marks` fills them from the log."""


def missing_field_paths(
    snapshot: HandoffSnapshot, schema: CardSchema = CARD_SCHEMA_V1
) -> tuple[str, ...]:
    """The `required_for_handoff` `CARD_FIELDS` paths the snapshot leaves empty (SPEC §10).

    "If the 112 operator omitted a critical fact, the omission propagates." This names the gap; it
    never fills it, and there is no input here from which it could be filled. A path counts as
    empty when the snapshot has no entry for it, or its value is `None`, the empty string or an
    empty list — a field the trainee cleared is as absent as one they never touched.
    """
    required = (
        REQUIRED_FOR_HANDOFF
        if schema is CARD_SCHEMA_V1
        else tuple(spec.field_path for spec in schema.fields if spec.required_for_handoff)
    )
    return tuple(path for path in required if _is_empty(snapshot.card_values.get(path)))


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
    """Project one `DdsWorkItem` from the snapshot and its legs — and from nothing else.

    The card specification is `v1`'s here; `with_card_schema` swaps in the session's pack schema
    (I3 E3a), so this projection's inputs stay exactly the snapshot and the legs (INV 3)."""
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
        card_schema=CARD_SCHEMA_V1.schema_id,
        field_specs=field_spec_views(CARD_SCHEMA_V1),
    )


def with_card_schema(
    view: DdsWorkItemView, snapshot: HandoffSnapshot, schema: CardSchema
) -> DdsWorkItemView:
    """`view` rendered by the session's card `schema` (HLD 70 §70.5.4): its `card_schema`, its
    `field_specs` and the schema's own `required_for_handoff` gaps. A specification, not data —
    the values stay the snapshot's."""
    return view.model_copy(
        update={
            "card_schema": schema.schema_id,
            "field_specs": field_spec_views(schema),
            "missing_field_paths": missing_field_paths(snapshot, schema),
        }
    )


def with_dds_marks(view: DdsWorkItemView, events: Iterable[SessionEvent]) -> DdsWorkItemView:
    """`view` with the marks the session's log holds (`dds_marks_of`, I7 E55)."""
    return view.model_copy(update={"dds_marks": dds_marks_of(events)})


def for_viewer(
    view: DdsWorkItemView, legs: Sequence[DDSAssignment], viewer_id: UserId | None
) -> DdsWorkItemView:
    """`view` as the ДДС trainee `viewer_id` reads it: `description.text` cut to its first
    `DESCRIPTION_LIMIT_CHARS` characters when every leg bound to the viewer is the 03 service
    (instr ¶257, I7 E55). `None` (the instructor, an observer) and any other viewer read it whole;
    an unbound leg is everyone's, so it never narrows the viewer to 03."""
    if viewer_id is None:
        return view
    mine = {
        leg.service_type
        for leg in legs
        if leg.responder is LegResponder.TRAINEE and leg.bound_user_id == viewer_id
    }
    if mine != {DESCRIPTION_LIMITED_SERVICE}:
        return view
    text = view.card_values.get(DESCRIPTION_PATH)
    if not isinstance(text, str) or len(text) <= DESCRIPTION_LIMIT_CHARS:
        return view
    return view.model_copy(
        update={
            "card_values": {**view.card_values, DESCRIPTION_PATH: text[:DESCRIPTION_LIMIT_CHARS]}
        }
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
