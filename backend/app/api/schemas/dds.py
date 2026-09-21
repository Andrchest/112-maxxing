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

from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.handoff import DdsWorkItemSchema, dds_work_item_schema
from app.api.schemas.operator import ActionDescriptorSchema, action_schemas
from app.application.dds.views import (
    DdsStageView,
    DispatchResultView,
    EmergencyResourceView,
    EtaProfileView,
    NotificationView,
    RadioMessagePage,
    RadioMessageView,
    StatusUpdateView,
)
from app.domain.dds.resources import ResourceCapability
from app.domain.enums import (
    ClosureReason,
    DDSStageState,
    NotificationSeverity,
    ResourceStatus,
    ResourceType,
    RoleType,
    ServiceType,
    SessionState,
    StatusUpdateKind,
)

__all__ = [
    "CloseIncidentRequestSchema",
    "DdsStageViewSchema",
    "DispatchRequestSchema",
    "DispatchResultViewSchema",
    "EmergencyResourceViewSchema",
    "EtaProfileViewSchema",
    "NotificationPageSchema",
    "NotificationViewSchema",
    "RadioMessagePageSchema",
    "RadioMessageViewSchema",
    "ResourcePageSchema",
    "ResourceSelectionRequestSchema",
    "StatusUpdateRequestSchema",
    "StatusUpdateViewSchema",
    "dds_stage_schema",
    "dispatch_result_schema",
    "notification_schema",
    "radio_message_page_schema",
    "resource_schema",
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


# ---------------------------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------------------------


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
    service_type: ServiceType
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
    """`openapi.yaml`'s `NotificationView` — one `notifications` row."""

    notification_id: UUID
    incident_id: UUID
    audience_role: RoleType
    severity: NotificationSeverity
    title_ru: str
    body_ru: str
    created_at_offset_ms: int
    source_world_event_id: str | None = None
    acknowledged_at_offset_ms: int | None = None


class NotificationPageSchema(ApiModel):
    """`listNotifications`' inline `{items, total}` envelope."""

    items: list[NotificationViewSchema]
    total: int = Field(ge=0)


class RadioMessageViewSchema(ApiModel):
    """`openapi.yaml`'s `RadioMessageView` — projected from the log, never from a table."""

    radio_message_id: UUID
    seq_no: int = Field(ge=1)
    incident_id: UUID
    from_callsign: str
    to_role: RoleType
    text_ru: str
    resource_id: UUID | None = None
    created_at_offset_ms: int
    source_world_event_id: str | None = None


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
        source_world_event_id=view.source_world_event_id,
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
        source_world_event_id=view.source_world_event_id,
    )


def radio_message_page_schema(page: RadioMessagePage) -> RadioMessagePageSchema:
    """`RadioMessagePage` -> the wire model."""
    return RadioMessagePageSchema(
        items=[radio_message_schema(item) for item in page.items],
        last_seq_no=page.last_seq_no,
    )
