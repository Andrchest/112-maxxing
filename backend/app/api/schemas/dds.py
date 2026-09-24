"""`dds` schemas — the wire models of the eleven `/dds/*` operations (`openapi.yaml`, D8, D12).

Property names are copied **literally** from the contract; `backend/tests/api/test_contract.py`
compares each response model's field-name set with the YAML's `properties` keys, so a rename on
either side fails the suite. `DdsWorkItemSchema` is not redefined here — it lives in
`app.api.schemas.handoff`, because the work item is a projection of the handoff, and embedding
that one model in `DdsStageView` is what keeps `getDdsWorkItem`, `DdsStageView.work_item` and
`SessionSnapshot.work_item` a single shape.

Every mapping function is explicit (D2): an application view goes field by field into its wire
model, so neither side can silently gain the other's fields — which is half of what makes SPEC §42
test 3 structural, since there is no field here for a world-truth value to arrive in.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.handoff import DdsWorkItemSchema, dds_work_item_schema
from app.api.schemas.operator import ActionDescriptorSchema, action_schemas
from app.application.dds.views import (
    CardIssueView,
    DdsLegView,
    DdsStageView,
    DispatchResultView,
    EmergencyResourceView,
    EtaProfileView,
    NotificationView,
    RadioMessagePage,
    RadioMessageView,
    ServiceStatusEntryView,
    StatusUpdateView,
)
from app.domain.dds.card_issue import CardIssueKind
from app.domain.dds.resources import ResourceCapability
from app.domain.dds.response import LegResponder, ServiceResponseStatus, StatusSource
from app.domain.enums import (
    ClosureReason,
    DDSStageState,
    NotificationSeverity,
    ResourceStatus,
    ResourceType,
    RoleType,
    ServiceId,
    SessionState,
    StatusUpdateKind,
)

__all__ = [
    "CardIssueViewSchema",
    "CloseIncidentRequestSchema",
    "DdsLegViewSchema",
    "DdsStageViewSchema",
    "DispatchRequestSchema",
    "DispatchResultViewSchema",
    "EmergencyResourceViewSchema",
    "EtaProfileViewSchema",
    "FlagCardIssueRequestSchema",
    "NotificationPageSchema",
    "NotificationViewSchema",
    "RadioMessagePageSchema",
    "RadioMessageViewSchema",
    "ResourcePageSchema",
    "ResourceSelectionRequestSchema",
    "ServiceStatusEntryViewSchema",
    "SetServiceStatusRequestSchema",
    "StatusUpdateRequestSchema",
    "StatusUpdateViewSchema",
    "card_issue_schema",
    "dds_leg_schema",
    "dds_stage_schema",
    "dispatch_result_schema",
    "notification_schema",
    "radio_message_page_schema",
    "resource_schema",
    "status_entry_schema",
    "status_update_schema",
]


# ---------------------------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------------------------


class ResourceSelectionRequestSchema(ApiModel):
    """`openapi.yaml`'s `ResourceSelectionRequest` — one unit, by id."""

    resource_id: UUID


class DispatchRequestSchema(ApiModel):
    """`openapi.yaml`'s `DispatchRequest` — an optional note for the receiving units."""

    note_ru: str | None = Field(default=None, max_length=1000)


class StatusUpdateRequestSchema(ApiModel):
    """`openapi.yaml`'s `StatusUpdateRequest` — the kind and the trainee's own words."""

    update_kind: StatusUpdateKind
    text_ru: str = Field(min_length=1, max_length=2000)


class CloseIncidentRequestSchema(ApiModel):
    """`openapi.yaml`'s `CloseIncidentRequest` — why the incident is being closed."""

    closure_reason: ClosureReason
    comment_ru: str | None = Field(default=None, max_length=2000)


class SetServiceStatusRequestSchema(ApiModel):
    """`openapi.yaml`'s `SetServiceStatusRequest` — the memo's pencil form (I3 E5a)."""

    status: ServiceResponseStatus
    order_number: str | None = Field(default=None, max_length=64)
    comment_ru: str | None = Field(default=None, max_length=2000)
    proposed_by_call_id: UUID | None = None
    """I3 E6c (HLD 80 §80.3.3): the ДДС call on which the status was heard — it must name a
    `DDS_CALL_STATUS_PROPOSED` of this leg (`422 PROPOSAL_UNKNOWN`)."""


class FlagCardIssueRequestSchema(ApiModel):
    """`openapi.yaml`'s `FlagCardIssueRequest` — «Отметить ошибку в карточке» (I3 E5b)."""

    assignment_id: UUID
    field_path: str | None = None
    issue_kind: CardIssueKind
    comment_ru: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------------------------


class CardIssueViewSchema(ApiModel):
    """`openapi.yaml`'s `CardIssueView` — one recorded card-issue flag (I3 E5b)."""

    event_id: UUID
    assignment_id: UUID
    field_path: str | None
    issue_kind: CardIssueKind
    comment_ru: str
    at_offset_ms: int


class EtaProfileViewSchema(ApiModel):
    """`openapi.yaml`'s `EtaProfileView` — scenario-defined, read verbatim (D7, SPEC §11)."""

    turnout_delay_seconds: int
    travel_time_seconds: int
    setup_seconds: int
    on_scene_work_seconds: int
    return_time_seconds: int


class EmergencyResourceViewSchema(ApiModel):
    """`openapi.yaml`'s `EmergencyResourceView` — one row of the resource board."""

    resource_id: UUID
    service_type: ServiceId
    resource_type: ResourceType
    callsign: str
    name_ru: str
    capabilities: list[ResourceCapability]
    current_status: ResourceStatus
    available_from_ms: int
    available_until_ms: int | None = None
    eta: EtaProfileViewSchema
    home_station_ru: str
    crew_size: int
    selectable: bool


class ResourcePageSchema(ApiModel):
    """`listDdsResources`' inline `{items, total}` envelope."""

    items: list[EmergencyResourceViewSchema]
    total: int = Field(ge=0)


class DdsStageViewSchema(ApiModel):
    """`openapi.yaml`'s `DdsStageView` — what every DDS command returns (D8)."""

    role_stage_id: UUID
    stage_state: DDSStageState
    available_actions: list[ActionDescriptorSchema]
    work_item: DdsWorkItemSchema
    resources: list[EmergencyResourceViewSchema]
    unacknowledged_notification_count: int = Field(ge=0)
    session_state: SessionState
    last_seq_no: int = Field(ge=0)


class DispatchResultViewSchema(ApiModel):
    """`openapi.yaml`'s `DispatchResultView`."""

    stage: DdsStageViewSchema
    dispatched_resource_ids: list[UUID]
    eta_seconds_by_resource: dict[str, int]
    is_additional: bool


class StatusUpdateViewSchema(ApiModel):
    """`openapi.yaml`'s `StatusUpdateView`."""

    assignment_id: UUID
    update_kind: StatusUpdateKind
    text_ru: str
    at_offset_ms: int
    actor_user_id: UUID


class NotificationViewSchema(ApiModel):
    """`openapi.yaml`'s `NotificationView` — one `notifications` row.

    INV 3: no `source_world_event_id` — see `application/dds/views.NotificationView`.
    """

    notification_id: UUID
    incident_id: UUID
    audience_role: RoleType
    severity: NotificationSeverity
    title_ru: str
    body_ru: str
    created_at_offset_ms: int
    acknowledged_at_offset_ms: int | None = None


class NotificationPageSchema(ApiModel):
    """`listNotifications`' inline `{items, total}` envelope."""

    items: list[NotificationViewSchema]
    total: int = Field(ge=0)


class RadioMessageViewSchema(ApiModel):
    """`openapi.yaml`'s `RadioMessageView` — projected from the log, never from a table.

    INV 3: no `source_world_event_id` — see `application/dds/views.RadioMessageView`.
    """

    radio_message_id: UUID
    seq_no: int = Field(ge=1)
    incident_id: UUID
    from_callsign: str
    to_role: RoleType
    text_ru: str
    resource_id: UUID | None = None
    created_at_offset_ms: int


class RadioMessagePageSchema(ApiModel):
    """`listRadioMessages`' inline `{items, last_seq_no}` envelope."""

    items: list[RadioMessageViewSchema]
    last_seq_no: int = Field(ge=0)


# ---------------------------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------------------------


def eta_schema(view: EtaProfileView) -> EtaProfileViewSchema:
    """`EtaProfileView` -> the wire model."""
    return EtaProfileViewSchema(
        turnout_delay_seconds=view.turnout_delay_seconds,
        travel_time_seconds=view.travel_time_seconds,
        setup_seconds=view.setup_seconds,
        on_scene_work_seconds=view.on_scene_work_seconds,
        return_time_seconds=view.return_time_seconds,
    )


def resource_schema(view: EmergencyResourceView) -> EmergencyResourceViewSchema:
    """`EmergencyResourceView` -> the wire model."""
    return EmergencyResourceViewSchema(
        resource_id=view.resource_id,
        service_type=view.service_type,
        resource_type=view.resource_type,
        callsign=view.callsign,
        name_ru=view.name_ru,
        capabilities=list(view.capabilities),
        current_status=view.current_status,
        available_from_ms=view.available_from_ms,
        available_until_ms=view.available_until_ms,
        eta=eta_schema(view.eta),
        home_station_ru=view.home_station_ru,
        crew_size=view.crew_size,
        selectable=view.selectable,
    )


def dds_stage_schema(view: DdsStageView) -> DdsStageViewSchema:
    """`DdsStageView` -> the wire model."""
    return DdsStageViewSchema(
        role_stage_id=view.role_stage_id,
        stage_state=view.stage_state,
        available_actions=action_schemas(view.available_actions),
        work_item=dds_work_item_schema(view.work_item),
        resources=[resource_schema(resource) for resource in view.resources],
        unacknowledged_notification_count=view.unacknowledged_notification_count,
        session_state=view.session_state,
        last_seq_no=view.last_seq_no,
    )


def dispatch_result_schema(view: DispatchResultView) -> DispatchResultViewSchema:
    """`DispatchResultView` -> the wire model.

    `eta_seconds_by_resource` is keyed by the resource id rendered as text: a JSON object's keys
    are strings, and `openapi.yaml` types the value as a free-form object of integers.
    """
    return DispatchResultViewSchema(
        stage=dds_stage_schema(view.stage),
        dispatched_resource_ids=list(view.dispatched_resource_ids),
        eta_seconds_by_resource={
            str(resource_id): seconds
            for resource_id, seconds in view.eta_seconds_by_resource.items()
        },
        is_additional=view.is_additional,
    )


def status_update_schema(view: StatusUpdateView) -> StatusUpdateViewSchema:
    """`StatusUpdateView` -> the wire model."""
    return StatusUpdateViewSchema(
        assignment_id=view.assignment_id,
        update_kind=view.update_kind,
        text_ru=view.text_ru,
        at_offset_ms=view.at_offset_ms,
        actor_user_id=view.actor_user_id,
    )


def notification_schema(view: NotificationView) -> NotificationViewSchema:
    """`NotificationView` -> the wire model."""
    return NotificationViewSchema(
        notification_id=view.notification_id,
        incident_id=view.incident_id,
        audience_role=view.audience_role,
        severity=view.severity,
        title_ru=view.title_ru,
        body_ru=view.body_ru,
        created_at_offset_ms=view.created_at_offset_ms,
        acknowledged_at_offset_ms=view.acknowledged_at_offset_ms,
    )


def radio_message_schema(view: RadioMessageView) -> RadioMessageViewSchema:
    """`RadioMessageView` -> the wire model."""
    return RadioMessageViewSchema(
        radio_message_id=view.radio_message_id,
        seq_no=view.seq_no,
        incident_id=view.incident_id,
        from_callsign=view.from_callsign,
        to_role=view.to_role,
        text_ru=view.text_ru,
        resource_id=view.resource_id,
        created_at_offset_ms=view.created_at_offset_ms,
    )


def radio_message_page_schema(page: RadioMessagePage) -> RadioMessagePageSchema:
    """`RadioMessagePage` -> the wire model."""
    return RadioMessagePageSchema(
        items=[radio_message_schema(item) for item in page.items],
        last_seq_no=page.last_seq_no,
    )


# ---------------------------------------------------------------------------------------------
# Legs (I3 E5a, HLD 70 §70.4.3)
# ---------------------------------------------------------------------------------------------


class ServiceStatusEntryViewSchema(ApiModel):
    """`openapi.yaml`'s `ServiceStatusEntryView` — one entry of a leg's status history."""

    event_id: UUID
    previous_status: ServiceResponseStatus
    new_status: ServiceResponseStatus
    order_number: str | None
    comment_ru: str | None
    completion_reason: Literal["WITHOUT_BRIGADE"] | None
    source: StatusSource
    actor_user_id: UUID | None
    actor_display_ru: str
    at_offset_ms: int


class DdsLegViewSchema(ApiModel):
    """`openapi.yaml`'s `DdsLegView` — one notified service's block (REQ-5294)."""

    assignment_id: UUID
    service_type: ServiceId
    service_name_ru: str
    response_status: ServiceResponseStatus
    response_status_at_offset_ms: int | None
    order_number: str | None
    last_comment_ru: str | None
    accept_missed: bool
    responder: LegResponder
    bound_user_id: UUID | None
    is_mine: bool
    history: list[ServiceStatusEntryViewSchema]
    available_actions: list[ActionDescriptorSchema]
    live_call_id: UUID | None = None
    """I3 E6c: the non-`ENDED` `SERVICE_HEAD` call on this leg, if any (HLD 80 contract delta)."""


def dds_leg_schema(view: DdsLegView) -> DdsLegViewSchema:
    """`DdsLegView` -> the wire model, field by field."""
    return DdsLegViewSchema(
        assignment_id=view.assignment_id,
        service_type=view.service_type,
        service_name_ru=view.service_name_ru,
        response_status=view.response_status,
        response_status_at_offset_ms=view.response_status_at_offset_ms,
        order_number=view.order_number,
        last_comment_ru=view.last_comment_ru,
        accept_missed=view.accept_missed,
        responder=view.responder,
        bound_user_id=view.bound_user_id,
        is_mine=view.is_mine,
        history=[status_entry_schema(entry) for entry in view.history],
        available_actions=action_schemas(view.available_actions),
        live_call_id=view.live_call_id,
    )


def status_entry_schema(entry: ServiceStatusEntryView) -> ServiceStatusEntryViewSchema:
    """One `ServiceStatusEntryView` -> the wire model (the leg block and the report share it)."""
    return ServiceStatusEntryViewSchema(
        event_id=entry.event_id,
        previous_status=entry.previous_status,
        new_status=entry.new_status,
        order_number=entry.order_number,
        comment_ru=entry.comment_ru,
        completion_reason=(
            "WITHOUT_BRIGADE" if entry.completion_reason == "WITHOUT_BRIGADE" else None
        ),
        source=entry.source,
        actor_user_id=entry.actor_user_id,
        actor_display_ru=entry.actor_display_ru,
        at_offset_ms=entry.at_offset_ms,
    )


def card_issue_schema(view: CardIssueView) -> CardIssueViewSchema:
    """`CardIssueView` -> the wire model (I3 E5b)."""
    return CardIssueViewSchema(
        event_id=view.event_id,
        assignment_id=view.assignment_id,
        field_path=view.field_path,
        issue_kind=view.issue_kind,
        comment_ru=view.comment_ru,
        at_offset_ms=view.at_offset_ms,
    )
