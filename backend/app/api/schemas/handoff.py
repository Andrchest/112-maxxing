"""`handoff` schemas — `CreateHandoffRequest`, `HandoffSnapshotView`, `HandoffCreatedView` and
`DdsWorkItem` (`openapi.yaml`, SPEC §10; D3, D8).

Property names are copied **literally** from the contract; `backend/tests/api/test_contract.py`
compares each response model's field-name set with the YAML's `properties` keys, so a rename on
either side fails the suite.

`DdsWorkItemSchema` lives here rather than in a `dds` schema module because the work item is a
projection of the handoff: every one of its fields comes from a `handoff_snapshots` row or a
`dds_assignments` row (`x-source: HANDOFF_SNAPSHOT`), and there is deliberately **no field for a
world-truth or live-card value to arrive in** — which is half of what makes SPEC §42 test 3 a
structural property rather than a promise. The DDS command slice (E9-B) embeds this model in
`DdsStageView`; nothing about it changes when it does.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.operator import (
    CardFieldSpecSchema,
    FactValueSchema,
    card_field_spec_schema,
)
from app.application.handoff.create_handoff import HandoffCreatedView, HandoffSnapshotView
from app.application.handoff.work_item import DdsWorkItemView
from app.domain.enums import (
    ClosureReason,
    DDSStageState,
    Operator112StageState,
    ServiceId,
    SessionState,
)

__all__ = [
    "CreateHandoffRequestSchema",
    "DdsCardMarksSchema",
    "DdsWorkItemSchema",
    "HandoffCreatedViewSchema",
    "HandoffSnapshotViewSchema",
    "dds_work_item_schema",
    "handoff_created_schema",
    "handoff_snapshot_schema",
]


class CreateHandoffRequestSchema(ApiModel):
    """`openapi.yaml`'s `CreateHandoffRequest` — one optional comment for the receiving services.

    It is written to the card field `recipients.comment` *before* the card is frozen, "so it is
    part of the snapshot rather than a side channel around it" (`openapi.yaml`).
    """

    comment_ru: str | None = Field(default=None, max_length=2000)


class HandoffSnapshotViewSchema(ApiModel):
    """`openapi.yaml`'s `HandoffSnapshotView` — the immutable by-value copy DDS reads."""

    snapshot_id: UUID
    incident_id: UUID
    card_id: UUID
    card_revision_id: UUID
    card_values: dict[str, FactValueSchema]
    recipient_services: list[ServiceId]
    created_by_user_id: UUID
    created_at_offset_ms: int
    content_sha256: str


class HandoffCreatedViewSchema(ApiModel):
    """`openapi.yaml`'s `HandoffCreatedView` — what `createHandoff` answers with."""

    snapshot: HandoffSnapshotViewSchema
    assignment_ids: list[UUID]
    stage_state: Operator112StageState
    session_state: SessionState


class DdsCardMarksSchema(ApiModel):
    """`openapi.yaml`'s `DdsCardMarks` — the ДДС's «ЧС» / «ЧП» marks (I7 E55)."""

    chs: bool
    chp: bool


class DdsWorkItemSchema(ApiModel):
    """`openapi.yaml`'s `DdsWorkItem` (`x-source: HANDOFF_SNAPSHOT`)."""

    assignment_id: UUID
    incident_id: UUID
    role_stage_id: UUID
    snapshot_id: UUID
    service_type: ServiceId
    state: DDSStageState
    card_values: dict[str, FactValueSchema]
    recipient_services: list[ServiceId]
    handoff_content_sha256: str
    received_at_offset_ms: int
    acknowledged_at_offset_ms: int | None = None
    dispatched_at_offset_ms: int | None = None
    closed_at_offset_ms: int | None = None
    closure_reason: ClosureReason | None = None
    selected_resource_ids: list[UUID]
    dispatched_resource_ids: list[UUID]
    missing_field_paths: list[str]
    card_schema: str = "v1"
    field_specs: list[CardFieldSpecSchema] = Field(default_factory=list)
    dds_marks: DdsCardMarksSchema = Field(
        default_factory=lambda: DdsCardMarksSchema(chs=False, chp=False)
    )


def handoff_snapshot_schema(view: HandoffSnapshotView) -> HandoffSnapshotViewSchema:
    """`HandoffSnapshotView` -> `HandoffSnapshotView` (the wire model)."""
    return HandoffSnapshotViewSchema(
        snapshot_id=view.snapshot_id,
        incident_id=view.incident_id,
        card_id=view.card_id,
        card_revision_id=view.card_revision_id,
        card_values=dict(view.card_values),
        recipient_services=list(view.recipient_services),
        created_by_user_id=view.created_by_user_id,
        created_at_offset_ms=view.created_at_offset_ms,
        content_sha256=view.content_sha256,
    )


def handoff_created_schema(view: HandoffCreatedView) -> HandoffCreatedViewSchema:
    """`HandoffCreatedView` -> the wire model."""
    return HandoffCreatedViewSchema(
        snapshot=handoff_snapshot_schema(view.snapshot),
        assignment_ids=list(view.assignment_ids),
        stage_state=view.stage_state,
        session_state=view.session_state,
    )


def dds_work_item_schema(view: DdsWorkItemView) -> DdsWorkItemSchema:
    """`DdsWorkItemView` -> `DdsWorkItem`."""
    return DdsWorkItemSchema(
        assignment_id=view.assignment_id,
        incident_id=view.incident_id,
        role_stage_id=view.role_stage_id,
        snapshot_id=view.snapshot_id,
        service_type=view.service_type,
        state=view.state,
        card_values=dict(view.card_values),
        recipient_services=list(view.recipient_services),
        handoff_content_sha256=view.handoff_content_sha256,
        received_at_offset_ms=view.received_at_offset_ms,
        acknowledged_at_offset_ms=view.acknowledged_at_offset_ms,
        dispatched_at_offset_ms=view.dispatched_at_offset_ms,
        closed_at_offset_ms=view.closed_at_offset_ms,
        closure_reason=view.closure_reason,
        selected_resource_ids=list(view.selected_resource_ids),
        dispatched_resource_ids=list(view.dispatched_resource_ids),
        missing_field_paths=list(view.missing_field_paths),
        card_schema=view.card_schema,
        field_specs=[card_field_spec_schema(spec) for spec in view.field_specs],
        dds_marks=DdsCardMarksSchema(chs=view.dds_marks.chs, chp=view.dds_marks.chp),
    )
