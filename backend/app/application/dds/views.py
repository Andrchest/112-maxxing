"""The materialized views every DDS command and read returns (D8, `openapi.yaml`).

D8: "commands return the new materialized view". These are the *application* shapes of
`openapi.yaml`'s `DdsStageView`, `EmergencyResourceView`, `EtaProfileView`, `NotificationView`,
`RadioMessageView`, `StatusUpdateView` and `DispatchResultView`; `app.api.schemas.dds` maps each
to its pydantic wire model, so the wire shape and the application shape can move independently
(D2). `DdsWorkItemView` is *not* redefined here — it is the handoff's projection
(`app.application.handoff.work_item`) and is embedded verbatim, which is what keeps
`getDdsWorkItem`, `DdsStageView.work_item` and `SessionSnapshot.work_item` one thing.

`ActionView` / `action_views` are reused from `app.application.operator.views` rather than copied:
they project `RoleModule.available_actions(state)`, which is a role-module fact and has nothing to
do with either role's data. Importing them brings no card, no repository and no world-truth path
with it (INV 3 scans the names this module mentions).

**Radio messages have no table.** `radio_message_views` folds them out of `session_events`
(`RADIO_MESSAGE_CREATED`), which `20-db-schema.md` §20.1 and `openapi.yaml` both state is the only
source. `incident_id` is the session's, because the event payload — correctly — does not repeat it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.application.handoff.work_item import DdsWorkItemView
from app.application.operator.views import ActionView, action_views
from app.application.ports.notification_repository import StoredNotification
from app.application.ports.resource_repository import StoredResource
from app.domain.dds.resources import (
    SELECTION_OPEN_STATES,
    EmergencyResource,
    EtaProfile,
    ResourceCapability,
    within_availability_window,
)
from app.domain.enums import (
    DDSStageState,
    NotificationSeverity,
    ResourceStatus,
    ResourceType,
    RoleType,
    ServiceId,
    SessionState,
    StatusUpdateKind,
)
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.roles.registry import ROLE_MODULES
from app.domain.session.session import RoleStage, SimulationSession

__all__ = [
    "DdsStageView",
    "DispatchResultView",
    "EmergencyResourceView",
    "EtaProfileView",
    "NotificationView",
    "RadioMessagePage",
    "RadioMessageView",
    "StatusUpdateView",
    "dds_stage_view",
    "eta_view",
    "notification_view",
    "radio_message_views",
    "resource_view",
    "resource_views",
    "selectable",
]


class DdsView(BaseModel):
    """Base for the views below: frozen, and no extra keys on the way back in."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EtaProfileView(DdsView):
    """`openapi.yaml`'s `EtaProfileView` — the five scenario-defined values, verbatim (D7)."""

    turnout_delay_seconds: int
    travel_time_seconds: int
    setup_seconds: int
    on_scene_work_seconds: int
    return_time_seconds: int


class EmergencyResourceView(DdsView):
    """`openapi.yaml`'s `EmergencyResourceView` — one row of the resource board (SPEC §11)."""

    resource_id: UUID
    service_type: ServiceId
    resource_type: ResourceType
    callsign: str
    name_ru: str
    capabilities: tuple[ResourceCapability, ...]
    current_status: ResourceStatus
    available_from_ms: int
    available_until_ms: int | None
    eta: EtaProfileView
    home_station_ru: str
    crew_size: int
    selectable: bool


class NotificationView(DdsView):
    """`openapi.yaml`'s `NotificationView` — one `notifications` row (§10.7, §20.5).

    INV 3: the row's `source_world_event_id` — the hidden world event that produced the
    notification — is deliberately absent. The WS path redacts it for trainees
    (`application/realtime/redaction.py`, HLD 40 §215-239) and this REST projection, which feeds
    the same trainee consoles, must not reintroduce it.
    """

    notification_id: UUID
    incident_id: UUID
    audience_role: RoleType
    severity: NotificationSeverity
    title_ru: str
    body_ru: str
    created_at_offset_ms: int
    acknowledged_at_offset_ms: int | None


class RadioMessageView(DdsView):
    """`openapi.yaml`'s `RadioMessageView` — projected from one `RADIO_MESSAGE_CREATED` row.

    INV 3: `source_world_event_id` is dropped here for the same reason as on `NotificationView`.
    """

    radio_message_id: UUID
    seq_no: int
    incident_id: UUID
    from_callsign: str
    to_role: RoleType
    text_ru: str
    resource_id: UUID | None
    created_at_offset_ms: int


class RadioMessagePage(DdsView):
    """`listRadioMessages`' inline `{items, last_seq_no}` envelope."""

    items: tuple[RadioMessageView, ...]
    last_seq_no: int


class StatusUpdateView(DdsView):
    """`openapi.yaml`'s `StatusUpdateView` — what `sendDdsStatusUpdate` answers with."""

    assignment_id: UUID
    update_kind: StatusUpdateKind
    text_ru: str
    at_offset_ms: int
    actor_user_id: UUID


class DdsStageView(DdsView):
    """`openapi.yaml`'s `DdsStageView` — what every DDS command returns (D8).

    It embeds the work item, never world truth: `work_item` is the stage-wide projection over the
    legs and their frozen snapshot, and `resources` is the board the scenario defined.
    """

    role_stage_id: UUID
    stage_state: DDSStageState
    available_actions: tuple[ActionView, ...]
    work_item: DdsWorkItemView
    resources: tuple[EmergencyResourceView, ...]
    unacknowledged_notification_count: int
    session_state: SessionState
    last_seq_no: int


class DispatchResultView(DdsView):
    """`openapi.yaml`'s `DispatchResultView` — what `dispatchDdsResources` answers with."""

    stage: DdsStageView
    dispatched_resource_ids: tuple[UUID, ...]
    eta_seconds_by_resource: Mapping[UUID, int]
    is_additional: bool


# ---------------------------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------------------------


def eta_view(eta: EtaProfile) -> EtaProfileView:
    """`EtaProfile` -> `EtaProfileView`, value for value (D7: no maps API is involved)."""
    return EtaProfileView(
        turnout_delay_seconds=eta.turnout_delay_seconds,
        travel_time_seconds=eta.travel_time_seconds,
        setup_seconds=eta.setup_seconds,
        on_scene_work_seconds=eta.on_scene_work_seconds,
        return_time_seconds=eta.return_time_seconds,
    )


def selectable(resource: EmergencyResource, *, stage_state: DDSStageState, now_ms: int) -> bool:
    """Would `select` succeed on this unit right now (`EmergencyResourceView.selectable`)?

    Derived from the same two facts `guard_selection_open_and_within_availability_window` reads —
    the stage is in a state where selection is open, and the unit is inside its availability
    window — plus the machine's own precondition that it is `AVAILABLE`. It is a UI hint: the
    backend re-checks the guard, and the contract says so.
    """
    if resource.current_status is not ResourceStatus.AVAILABLE:
        return False
    if stage_state not in SELECTION_OPEN_STATES:
        return False
    return within_availability_window(resource, now_ms)


def resource_view(
    resource: EmergencyResource, *, stage_state: DDSStageState, now_ms: int
) -> EmergencyResourceView:
    """`EmergencyResource` -> `EmergencyResourceView` (SPEC §11's minimum fields, all present)."""
    return EmergencyResourceView(
        resource_id=UUID(str(resource.resource_id)),
        service_type=resource.service_type,
        resource_type=resource.resource_type,
        callsign=resource.callsign,
        name_ru=resource.name_ru,
        capabilities=tuple(sorted(resource.capabilities, key=lambda item: item.value)),
        current_status=resource.current_status,
        available_from_ms=resource.availability.available_from_ms,
        available_until_ms=resource.availability.available_until_ms,
        eta=eta_view(resource.eta),
        home_station_ru=resource.home_station_ru,
        crew_size=resource.crew_size,
        selectable=selectable(resource, stage_state=stage_state, now_ms=now_ms),
    )


def resource_views(
    board: Sequence[StoredResource], *, stage_state: DDSStageState, now_ms: int
) -> tuple[EmergencyResourceView, ...]:
    """The whole board, in `callsign` order — a stable order the console can render directly."""
    return tuple(
        resource_view(stored.resource, stage_state=stage_state, now_ms=now_ms)
        for stored in sorted(board, key=lambda stored: stored.resource.callsign)
    )


def notification_view(stored: StoredNotification) -> NotificationView:
    """`StoredNotification` -> `NotificationView`."""
    return NotificationView(
        notification_id=stored.notification_id,
        incident_id=UUID(str(stored.incident_id)),
        audience_role=stored.audience_role,
        severity=stored.severity,
        title_ru=stored.title_ru,
        body_ru=stored.body_ru,
        created_at_offset_ms=stored.created_at_offset_ms,
        acknowledged_at_offset_ms=stored.acknowledged_at_offset_ms,
    )


def radio_message_views(
    events: Sequence[SessionEvent],
    *,
    incident_id: UUID,
    to_role: RoleType,
    after_seq_no: int = 0,
    limit: int = 100,
) -> RadioMessagePage:
    """Fold `RADIO_MESSAGE_CREATED` rows addressed to `to_role` into the radio log.

    In log order (`seq_no` ascending), which is the order the traffic happened in. The filter is
    the contract's — "`to_role == the caller's role`" — and it is applied here rather than in the
    reader, so the operator console and the DDS console share one implementation of it.
    `last_seq_no` is the cursor a client passes back as `after_seq_no`: the `seq_no` of the last
    item returned, or the one the caller asked from when nothing matched.
    """
    items: list[RadioMessageView] = []
    for event in events:
        if event.event_type is not EventType.RADIO_MESSAGE_CREATED:
            continue
        if event.seq_no <= after_seq_no:
            continue
        payload = event.payload
        if not _matches_role(payload.get("to_role"), to_role):
            continue
        items.append(
            RadioMessageView(
                radio_message_id=_uuid(payload["radio_message_id"]),
                seq_no=event.seq_no,
                incident_id=incident_id,
                from_callsign=str(payload.get("from_callsign", "")),
                to_role=to_role,
                text_ru=str(payload.get("text_ru", "")),
                resource_id=_optional_uuid(payload.get("resource_id")),
                created_at_offset_ms=int(payload.get("at_offset_ms", event.monotonic_offset_ms)),
            )
        )
        if len(items) >= limit:
            break
    return RadioMessagePage(
        items=tuple(items),
        last_seq_no=items[-1].seq_no if items else after_seq_no,
    )


def dds_stage_view(
    session: SimulationSession,
    stage: RoleStage,
    *,
    work_item: DdsWorkItemView,
    board: Sequence[StoredResource],
    unacknowledged_notification_count: int,
    now_ms: int,
    last_seq_no: int,
) -> DdsStageView:
    """Assemble `DdsStageView` from the state a command has just produced (D8)."""
    module = ROLE_MODULES[stage.role_type]
    state = stage.state
    assert isinstance(state, DDSStageState)
    return DdsStageView(
        role_stage_id=UUID(str(stage.role_stage_id)),
        stage_state=state,
        available_actions=action_views(module.available_actions(state)),
        work_item=work_item,
        resources=resource_views(board, stage_state=state, now_ms=now_ms),
        unacknowledged_notification_count=unacknowledged_notification_count,
        session_state=session.state,
        last_seq_no=last_seq_no,
    )


def _matches_role(value: Any, role: RoleType) -> bool:
    if isinstance(value, RoleType):
        return value is role
    return isinstance(value, str) and value == role.value


def _uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _optional_uuid(value: Any) -> UUID | None:
    return None if value is None else _uuid(value)
