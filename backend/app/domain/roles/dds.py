"""`DDSModule` (HLD `10-domain-model.md` §10.9).

`select_resource`, `deselect_resource`, `send_status_update` are non-transition commands
(`ActionDescriptor.trigger = None`): resource selection fires on `RESOURCE_STATUS_TRANSITIONS`
(`dds/resources.py`), a different machine than this module's `DDS_TRANSITIONS`, and a status
update does not move the DDS stage at all. The state machine below is built with `DDS_GUARDS`
(`session/guards.py`), so every `guard_name` `DDS_TRANSITIONS` references resolves to a real
predicate.

**Repair (E9).** `dispatch_additional` was unreachable as §10.9 was originally written: its guard
needs a `SELECTED` unit, `select` was guarded by "assignment state is `RESOURCE_SELECTION`",
`select_resource` was not an available action in `EN_ROUTE` / `ARRIVED` / `WORKING`, the only way
back to `RESOURCE_SELECTION` is from `DISPATCHED` and only before the first unit departs, and
`dispatch` takes *every* selected unit. `select_resource` / `deselect_resource` are therefore
available actions in those three states here, and `dds/resources.py` widens the two unit-level
guards to match. `deselect` keeps its "not yet dispatched" guard, so reinforcement can never
un-send a unit that is already moving. `10-domain-model.md` §10.7 and §10.9 carry the same
tables, and `tests/unit/domain/roles/test_dds_tables_match_the_hld.py` parses them at test time
so the two halves cannot drift apart again.

**Memo mode (I3 E5a, HLD 70 §70.4.4, D16).** The module is variant-aware. Under `dds_mode:
MEMO_STATUSES` it offers `_MEMO_AVAILABLE_ACTIONS` — no resource action at all; per-service
progress lives on the legs (`dds/response.py`) — and fires its stage triggers through
`memo_state_machine`: `MEMO_DDS_TRANSITIONS` (the memo triggers' rows of the one
`DDS_TRANSITIONS`) with `DDS_GUARDS_MEMO`. `RESOURCE_SELECTION` … `WORKING` are never entered, and
the stage leaves `ACKNOWLEDGED` only through the additive `close` row. `RESOURCE_PICKER` (and a
session with no variants) keeps the picker table and machine verbatim.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.domain.common.state_machine import StateMachine
from app.domain.enums import DDSStageState, RoleType
from app.domain.events.types import EventType
from app.domain.roles.module import ActionDescriptor, Permission
from app.domain.roles.visibility import DataVisibilityPolicy, VisibilitySource
from app.domain.session.guards import DDS_GUARDS, DDS_GUARDS_MEMO
from app.domain.session.transitions import DDS_TRANSITIONS, MEMO_DDS_TRANSITIONS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.domain.session.variants import SessionVariants

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
    # Repair (E9, §10.7 / §10.9): `select_resource` and `deselect_resource` are available in the
    # three states `dispatch_additional` fires from. Without them nothing could ever be `SELECTED`
    # there, so `dispatch_additional`'s own guard could never hold — see the module docstring.
    DDSStageState.EN_ROUTE: (
        _SELECT_RESOURCE,
        _DESELECT_RESOURCE,
        _DISPATCH_ADDITIONAL,
        _SEND_STATUS_UPDATE,
    ),
    DDSStageState.ARRIVED: (
        _SELECT_RESOURCE,
        _DESELECT_RESOURCE,
        _DISPATCH_ADDITIONAL,
        _SEND_STATUS_UPDATE,
    ),
    DDSStageState.WORKING: (
        _SELECT_RESOURCE,
        _DESELECT_RESOURCE,
        _DISPATCH_ADDITIONAL,
        _SEND_STATUS_UPDATE,
    ),
    DDSStageState.RESOLVED: (_CLOSE, _SEND_STATUS_UPDATE),
    DDSStageState.CLOSED: (),
}


# -- memo mode (I3 E5a, HLD 70 §70.4.4) ------------------------------------------------------

_OPEN_CARD = ActionDescriptor(
    action_id="open_card",
    label_ru="Открыть карточку",
    permission=Permission.VIEW_HANDOFF,
)
_SET_SERVICE_STATUS = ActionDescriptor(
    action_id="set_service_status",
    label_ru="Изменить статус",
    permission=Permission.SET_SERVICE_STATUS,
)

_MEMO_AVAILABLE_ACTIONS: Mapping[DDSStageState, tuple[ActionDescriptor, ...]] = {
    DDSStageState.RECEIVED: (_OPEN_CARD, _SET_SERVICE_STATUS),
    DDSStageState.ACKNOWLEDGED: (_SET_SERVICE_STATUS, _SEND_STATUS_UPDATE, _CLOSE),
    DDSStageState.RESOURCE_SELECTION: (),
    DDSStageState.DISPATCHED: (),
    DDSStageState.EN_ROUTE: (),
    DDSStageState.ARRIVED: (),
    DDSStageState.WORKING: (),
    DDSStageState.RESOLVED: (_CLOSE,),
    DDSStageState.CLOSED: (),
}
"""§70.4.4's memo table. `flag_card_issue` joins `ACKNOWLEDGED` with E5b (only under
`dds_card_check: ON`, which is not implemented before it); `close` is offered in `ACKNOWLEDGED`
and its guard `memo_all_legs_terminal` decides — a leg still open is the ordinary `409`."""


def _is_memo(variants: SessionVariants | None) -> bool:
    return variants is not None and variants.dds_mode.value == "MEMO_STATUSES"


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
        self.memo_state_machine: StateMachine[DDSStageState] = StateMachine(
            MEMO_DDS_TRANSITIONS, DDS_GUARDS_MEMO
        )
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
                    EventType.DDS_CARD_STATUS_CHANGED,  # I3 E4a (HLD 70 §70.7)
                    EventType.DDS_CARD_OPENED,  # I3 E5a (HLD 70 §70.7)
                    EventType.DDS_SERVICE_STATUS_SET,  # I3 E5a (HLD 70 §70.7)
                }
            ),
        )

    def available_actions(
        self, stage_state: Enum, *, variants: SessionVariants | None = None
    ) -> tuple[ActionDescriptor, ...]:
        """§10.9's table for the session's `dds_mode` (HLD 70 §70.4.4): the memo table under
        `MEMO_STATUSES`, the picker table otherwise (and for `variants=None`)."""
        assert isinstance(stage_state, DDSStageState)
        if _is_memo(variants):
            return _MEMO_AVAILABLE_ACTIONS[stage_state]
        return _AVAILABLE_ACTIONS[stage_state]

    def state_machine_for(
        self, variants: SessionVariants | None = None
    ) -> StateMachine[DDSStageState]:
        """`memo_state_machine` under `MEMO_STATUSES`, the picker `state_machine` otherwise."""
        return self.memo_state_machine if _is_memo(variants) else self.state_machine

    def initial_state(self) -> Enum:
        return DDSStageState.RECEIVED

    def terminal_states(self) -> frozenset[Enum]:
        return frozenset({DDSStageState.CLOSED})
