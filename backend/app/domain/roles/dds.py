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

**The ДДС phone (I3 E6b, HLD 80 §80.5, D25).** Under `dds_brigade_call: ON` — memo mode only (R41)
— the memo table also offers `call_service_head` «Позвонить старшему» (E6c), `call_claimant`
«Позвонить заявителю» (E6b) and `call_112` «Позвонить в 112» (E6d, answered by the AI 112
operator) in the two states the ДДС holds the card in (`RECEIVED`, `ACKNOWLEDGED`). `hang_up`
«Положить трубку» and, on a ringing INBOUND call, `answer` «Ответить» (E6c) are actions of a
live `DdsCall`, not of the stage: they are served as `DdsCallView.available_actions`
(`dds_call_actions`). Under `OFF` no call action exists anywhere. The DDS visibility whitelist
also gains the three `DDS_CALL_*` events and the per-turn pipeline events, which
`realtime/redaction.py` then delivers call-scoped (HLD 80 §80.6.2).
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
    from app.domain.dds.call import DdsCall
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

_FLAG_CARD_ISSUE = ActionDescriptor(
    action_id="flag_card_issue",
    label_ru="Отметить ошибку в карточке",
    permission=Permission.FLAG_CARD_ISSUE,
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
"""§70.4.4's memo table under `dds_card_check: OFF`; `close` is offered in `ACKNOWLEDGED` and its
guard `memo_all_legs_terminal` decides — a leg still open is the ordinary `409`."""

_MEMO_CARD_CHECK_ACTIONS: Mapping[DDSStageState, tuple[ActionDescriptor, ...]] = {
    **_MEMO_AVAILABLE_ACTIONS,
    DDSStageState.ACKNOWLEDGED: (
        _SET_SERVICE_STATUS,
        _SEND_STATUS_UPDATE,
        _FLAG_CARD_ISSUE,
        _CLOSE,
    ),
}
"""The same table under `dds_card_check: ON` (I3 E5b, C1): «Отметить ошибку в карточке» joins
`ACKNOWLEDGED`, in §70.4.4's order."""


_PICKER_CARD_CHECK_ACTIONS: Mapping[DDSStageState, tuple[ActionDescriptor, ...]] = {
    state: (
        actions
        if state in (DDSStageState.RECEIVED, DDSStageState.CLOSED)
        else (*actions, _FLAG_CARD_ISSUE)
    )
    for state, actions in _AVAILABLE_ACTIONS.items()
}
"""The picker table under `dds_card_check: ON` (I3 E5b, C1, §70.11): «Отметить ошибку в карточке»
in every state from `ACKNOWLEDGED` until the stage closes — where the ДДС holds the card."""


# -- the ДДС phone (I3 E6b, HLD 80 §80.5) --------------------------------------------------------

CALL_CLAIMANT = ActionDescriptor(
    action_id="call_claimant",
    label_ru="Позвонить заявителю",
    permission=Permission.PLACE_DDS_CALL,
)
CALL_SERVICE_HEAD = ActionDescriptor(
    action_id="call_service_head",
    label_ru="Позвонить старшему",
    permission=Permission.PLACE_DDS_CALL,
)
CALL_112 = ActionDescriptor(
    action_id="call_112",
    label_ru="Позвонить в 112",
    permission=Permission.PLACE_DDS_CALL,
)
CALL_HANG_UP = ActionDescriptor(
    action_id="hang_up",
    label_ru="Положить трубку",
    permission=Permission.PLACE_DDS_CALL,
    trigger="hang_up",
)
CALL_ANSWER = ActionDescriptor(
    action_id="answer",
    label_ru="Ответить",
    permission=Permission.PLACE_DDS_CALL,
    trigger="answer",
)

_CALL_STAGE_STATES: frozenset[DDSStageState] = frozenset(
    {DDSStageState.RECEIVED, DDSStageState.ACKNOWLEDGED}
)
"""The memo states the ДДС holds the card in — where the call actions are offered under `ON`."""

_CALL_ACTIONS: tuple[ActionDescriptor, ...] = (CALL_SERVICE_HEAD, CALL_CLAIMANT, CALL_112)
"""The stage's call actions under `ON`, in §80.5's order: «Позвонить старшему» (E6c; the leg is
the request's `assignment_id`, and only a leg the trainee plays may be called), «Позвонить
заявителю» (E6b), «Позвонить в 112» (E6d; REQ-5332 — the AI 112 operator answers, owner Q1)."""


def dds_call_actions(call: DdsCall) -> tuple[ActionDescriptor, ...]:
    """`DdsCallView.available_actions`: `answer` «Ответить» on a ringing INBOUND call (I3 E6c),
    `hang_up` while the call is live, nothing once it ended."""
    if not call.live:
        return ()
    if call.direction.value == "INBOUND" and call.state.value == "RINGING":
        return (CALL_ANSWER, CALL_HANG_UP)
    return (CALL_HANG_UP,)


def _brigade_call_on(variants: SessionVariants | None) -> bool:
    return variants is not None and variants.dds_brigade_call.value == "ON"


def _is_memo(variants: SessionVariants | None) -> bool:
    return variants is not None and variants.dds_mode.value == "MEMO_STATUSES"


def _card_check_on(variants: SessionVariants | None) -> bool:
    return variants is not None and variants.dds_card_check.value == "ON"


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
                Permission.PLACE_DDS_CALL,  # I3 E6b: used only under `dds_brigade_call: ON`
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
                    EventType.DDS_CARD_ISSUE_FLAGGED,  # I3 E5b (HLD 70 §70.7)
                    EventType.DDS_CARD_MARKS_SET,  # I7 E55 (HLD 71 §71.19.55)
                    # I3 E6b (HLD 80 §80.6): the ДДС phone line, and the per-turn pipeline events
                    # of a DDS call — delivered call-scoped by `realtime/redaction.py` (`▲`).
                    EventType.DDS_CALL_STARTED,
                    EventType.DDS_CALL_ANSWERED,
                    EventType.DDS_CALL_ENDED,
                    EventType.DDS_CALL_STATUS_PROPOSED,  # I3 E6c (HLD 80 §80.6.1)
                    EventType.USER_SPEECH_STARTED,
                    EventType.USER_SPEECH_ENDED,
                    EventType.ASR_PARTIAL,
                    EventType.ASR_FINAL,
                    EventType.CALLER_TTS_STARTED,
                    EventType.CALLER_TTS_ENDED,
                    EventType.CALLER_UTTERANCE_INTERRUPTED,
                    EventType.TRANSPORT_DISCONNECTED,
                    EventType.TRANSPORT_RECONNECTED,
                }
            ),
        )

    def available_actions(
        self, stage_state: Enum, *, variants: SessionVariants | None = None
    ) -> tuple[ActionDescriptor, ...]:
        """§10.9's table for the session's `dds_mode` (HLD 70 §70.4.4): the memo table under
        `MEMO_STATUSES` — with `flag_card_issue` in `ACKNOWLEDGED` when `dds_card_check: ON`
        (I3 E5b) — the picker table otherwise (and for `variants=None`), with `flag_card_issue`
        from `ACKNOWLEDGED` to `RESOLVED` under card check `ON`. Under `dds_brigade_call: ON` the
        memo `RECEIVED` / `ACKNOWLEDGED` rows end with `call_service_head` (I3 E6c),
        `call_claimant` (I3 E6b) and `call_112` (I3 E6d)."""
        assert isinstance(stage_state, DDSStageState)
        if _is_memo(variants):
            table = (
                _MEMO_CARD_CHECK_ACTIONS if _card_check_on(variants) else _MEMO_AVAILABLE_ACTIONS
            )
            actions = table[stage_state]
            if _brigade_call_on(variants) and stage_state in _CALL_STAGE_STATES:
                # I3 E6b/E6c/E6d (HLD 80 §80.5): the ДДС phone, memo mode only (R41).
                return (*actions, *_CALL_ACTIONS)
            return actions
        if _card_check_on(variants):
            return _PICKER_CARD_CHECK_ACTIONS[stage_state]
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
