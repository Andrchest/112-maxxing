"""`DDSModule` (HLD `10-domain-model.md` §10.9).

`select_resource`, `deselect_resource`, `send_status_update` are non-transition commands
(`ActionDescriptor.trigger = None`): resource selection fires on `RESOURCE_STATUS_TRANSITIONS`
(`dds/resources.py`), a different machine than this module's `DDS_TRANSITIONS`, and a status
update does not move the DDS stage at all. The state machine below is built with `DDS_GUARDS`
(`session/guards.py`), so every `guard_name` `DDS_TRANSITIONS` references resolves to a real
predicate.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from app.domain.common.state_machine import StateMachine
from app.domain.enums import DDSStageState, RoleType
from app.domain.events.types import EventType
from app.domain.roles.module import ActionDescriptor, Permission
from app.domain.roles.visibility import DataVisibilityPolicy, VisibilitySource
from app.domain.session.guards import DDS_GUARDS
from app.domain.session.transitions import DDS_TRANSITIONS

_ACKNOWLEDGE = ActionDescriptor(
    action_id="acknowledge",
    label_ru="Принять к исполнению",
    permission=Permission.ACKNOWLEDGE_ASSIGNMENT,
    trigger="acknowledge",
)
_OPEN_RESOURCE_SELECTION = ActionDescriptor(
    action_id="open_resource_selection",
    label_ru="Подбор сил и средств",
    permission=Permission.SELECT_RESOURCES,
    trigger="open_resource_selection",
)
_OPEN_RESOURCE_SELECTION_ADD = ActionDescriptor(
    action_id="open_resource_selection",
    label_ru="Добавить силы",
    permission=Permission.SELECT_RESOURCES,
    trigger="open_resource_selection",
)
_SELECT_RESOURCE = ActionDescriptor(
    action_id="select_resource", label_ru="Выбрать", permission=Permission.SELECT_RESOURCES
)
_DESELECT_RESOURCE = ActionDescriptor(
    action_id="deselect_resource", label_ru="Снять", permission=Permission.SELECT_RESOURCES
)
_DISPATCH = ActionDescriptor(
    action_id="dispatch",
    label_ru="Направить",
    permission=Permission.DISPATCH_RESOURCES,
    trigger="dispatch",
)
_BACK_TO_ACKNOWLEDGED = ActionDescriptor(
    action_id="back_to_acknowledged",
    label_ru="Назад",
    permission=Permission.SELECT_RESOURCES,
    trigger="back_to_acknowledged",
)
_SEND_STATUS_UPDATE = ActionDescriptor(
    action_id="send_status_update",
    label_ru="Отправить статус",
    permission=Permission.SEND_STATUS_UPDATE,
)
_DISPATCH_ADDITIONAL = ActionDescriptor(
    action_id="dispatch_additional",
    label_ru="Направить дополнительно",
    permission=Permission.DISPATCH_RESOURCES,
    trigger="dispatch_additional",
)
_CLOSE = ActionDescriptor(
    action_id="close",
    label_ru="Закрыть происшествие",
    permission=Permission.CLOSE_INCIDENT,
    trigger="close",
)

_AVAILABLE_ACTIONS: Mapping[DDSStageState, tuple[ActionDescriptor, ...]] = {
    DDSStageState.RECEIVED: (_ACKNOWLEDGE,),
    DDSStageState.ACKNOWLEDGED: (_OPEN_RESOURCE_SELECTION, _SEND_STATUS_UPDATE),
    DDSStageState.RESOURCE_SELECTION: (
        _SELECT_RESOURCE,
        _DESELECT_RESOURCE,
        _DISPATCH,
        _BACK_TO_ACKNOWLEDGED,
        _SEND_STATUS_UPDATE,
    ),
    DDSStageState.DISPATCHED: (_OPEN_RESOURCE_SELECTION_ADD, _SEND_STATUS_UPDATE),
    DDSStageState.EN_ROUTE: (_DISPATCH_ADDITIONAL, _SEND_STATUS_UPDATE),
    DDSStageState.ARRIVED: (_DISPATCH_ADDITIONAL, _SEND_STATUS_UPDATE),
    DDSStageState.WORKING: (_DISPATCH_ADDITIONAL, _SEND_STATUS_UPDATE),
    DDSStageState.RESOLVED: (_CLOSE, _SEND_STATUS_UPDATE),
    DDSStageState.CLOSED: (),
}


class DDSModule:
    """§10.9 `DDSModule`. `visibility_policy.sources` has no `OPERATOR_CARD`, no `WORLD_TRUTH`,
    no `TRANSCRIPT` (SPEC §10, §42 test 3)."""

    role_type: RoleType = RoleType.DDS
    implemented: bool = True
    ui_schema: Mapping[str, Any] = {}

    def __init__(self) -> None:
        self.permissions: frozenset[Permission] = frozenset(
            {
                Permission.VIEW_HANDOFF,
                Permission.ACKNOWLEDGE_ASSIGNMENT,
                Permission.SELECT_RESOURCES,
                Permission.DISPATCH_RESOURCES,
                Permission.SEND_STATUS_UPDATE,
                Permission.CLOSE_INCIDENT,
                Permission.VIEW_RESOURCE_BOARD,
                Permission.ACKNOWLEDGE_NOTIFICATION,
            }
        )
        self.state_machine: StateMachine[DDSStageState] = StateMachine(DDS_TRANSITIONS, DDS_GUARDS)
        self.visibility_policy = DataVisibilityPolicy(
            role_type=RoleType.DDS,
            sources=frozenset(
                {
                    VisibilitySource.HANDOFF_SNAPSHOT,
                    VisibilitySource.DDS_ASSIGNMENT,
                    VisibilitySource.RESOURCE_BOARD,
                    VisibilitySource.NOTIFICATIONS,
                    VisibilitySource.RADIO_MESSAGES,
                }
            ),
            # Exactly the DDS column of `40-realtime-protocol.md` §40.4 (ruling R6): a `✔`/`▲` row
            # is a member of this whitelist regardless of the redaction or per-connection filter
            # §40.4 applies to that row's payload/delivery.
            visible_event_types=frozenset(
                {
                    EventType.SESSION_STARTED,
                    EventType.ROLE_STAGE_STARTED,
                    EventType.HANDOFF_RECEIVED,
                    EventType.DDS_ACKNOWLEDGED,
                    EventType.RESOURCE_SELECTED,
                    EventType.RESOURCE_DESELECTED,
                    EventType.RESOURCE_DISPATCHED,
                    EventType.RESOURCE_STATUS_CHANGED,
                    EventType.ROLE_STAGE_COMPLETED,
                    EventType.SESSION_COMPLETED,
                    EventType.SESSION_ABORTED,
                    EventType.STAGE_STATE_CHANGED,
                    EventType.ROLE_TRANSITION_STARTED,
                    EventType.ROLE_TRANSITION_COMPLETED,
                    EventType.DDS_STATUS_UPDATE_SENT,
                    EventType.DDS_INCIDENT_CLOSED,
                    EventType.NOTIFICATION_CREATED,
                    EventType.NOTIFICATION_ACKNOWLEDGED,
                    EventType.RADIO_MESSAGE_CREATED,
                }
            ),
        )

    def available_actions(self, stage_state: Enum) -> tuple[ActionDescriptor, ...]:
        assert isinstance(stage_state, DDSStageState)
        return _AVAILABLE_ACTIONS[stage_state]

    def initial_state(self) -> Enum:
        return DDSStageState.RECEIVED

    def terminal_states(self) -> frozenset[Enum]:
        return frozenset({DDSStageState.CLOSED})
