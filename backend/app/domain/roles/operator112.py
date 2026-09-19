"""`Operator112Module` (HLD `10-domain-model.md` §10.9).

Two action ids in the §10.9 `available_actions` table are not `OPERATOR_112_TRANSITIONS` triggers
at all: `edit_card` and `end_call` are non-transition commands (`ActionDescriptor.trigger = None`)
— `end_call` is expected to emit `CALL_ENDED` (referenced by the `guard_call_ended` /
`guard_call_still_connected` guard names) without itself moving the stage machine. Three
transition-triggered action ids (`open_handoff_preparation`, `back_to_interview`,
`complete_stage`) have no dedicated entry in `Permission` (§10.9 fixes that enum at 14 members and
does not add one for them); the mapping below picks the closest existing permission — see this
task's report, "HLD gaps".

The state machine below is built with `OPERATOR_112_GUARDS` (`session/guards.py`), so every
`guard_name` `OPERATOR_112_TRANSITIONS` references resolves to a real predicate.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from app.domain.common.state_machine import StateMachine
from app.domain.enums import Operator112StageState, RoleType
from app.domain.events.types import EventType
from app.domain.roles.module import ActionDescriptor, Permission
from app.domain.roles.visibility import DataVisibilityPolicy, VisibilitySource
from app.domain.session.guards import OPERATOR_112_GUARDS
from app.domain.session.transitions import OPERATOR_112_TRANSITIONS

_ANSWER = ActionDescriptor(
    action_id="answer", label_ru="Ответить", permission=Permission.ANSWER_CALL, trigger="answer"
)
_EDIT_CARD = ActionDescriptor(
    action_id="edit_card", label_ru="Заполнить карточку", permission=Permission.EDIT_CARD
)
_SELECT_SERVICES = ActionDescriptor(
    action_id="select_services",
    label_ru="Выбрать службы",
    permission=Permission.SELECT_SERVICES,
)
_OPEN_HANDOFF_PREPARATION = ActionDescriptor(
    action_id="open_handoff_preparation",
    label_ru="Подготовить передачу",
    permission=Permission.CREATE_HANDOFF,
    trigger="open_handoff_preparation",
)
_CREATE_HANDOFF = ActionDescriptor(
    action_id="create_handoff",
    label_ru="Передать в ДДС",
    permission=Permission.CREATE_HANDOFF,
    trigger="create_handoff",
)
_BACK_TO_INTERVIEW = ActionDescriptor(
    action_id="back_to_interview",
    label_ru="Вернуться к опросу",
    permission=Permission.EDIT_CARD,
    trigger="back_to_interview",
)
_END_CALL = ActionDescriptor(
    action_id="end_call", label_ru="Завершить вызов", permission=Permission.END_CALL
)
_COMPLETE_STAGE = ActionDescriptor(
    action_id="complete_stage",
    label_ru="Завершить этап",
    permission=Permission.END_CALL,
    trigger="complete_stage",
)

_AVAILABLE_ACTIONS: Mapping[Operator112StageState, tuple[ActionDescriptor, ...]] = {
    Operator112StageState.WAITING_FOR_CALL: (),
    Operator112StageState.RINGING: (_ANSWER,),
    Operator112StageState.CONNECTED: (_EDIT_CARD, _END_CALL),
    Operator112StageState.INTERVIEW: (
        _EDIT_CARD,
        _SELECT_SERVICES,
        _OPEN_HANDOFF_PREPARATION,
        _END_CALL,
    ),
    Operator112StageState.HANDOFF_PREPARATION: (
        _EDIT_CARD,
        _SELECT_SERVICES,
        _CREATE_HANDOFF,
        _BACK_TO_INTERVIEW,
        _END_CALL,
    ),
    Operator112StageState.HANDED_OFF: (_END_CALL, _COMPLETE_STAGE),
    Operator112StageState.STAGE_COMPLETED: (),
}


class Operator112Module:
    """§10.9 `Operator112Module`."""

    role_type: RoleType = RoleType.OPERATOR_112
    implemented: bool = True
    ui_schema: Mapping[str, Any] = {}

    def __init__(self) -> None:
        self.permissions: frozenset[Permission] = frozenset(
            {
                Permission.ANSWER_CALL,
                Permission.END_CALL,
                Permission.EDIT_CARD,
                Permission.SELECT_SERVICES,
                Permission.CREATE_HANDOFF,
                Permission.VIEW_TRANSCRIPT,
                Permission.ACKNOWLEDGE_NOTIFICATION,
            }
        )
        self.state_machine: StateMachine[Operator112StageState] = StateMachine(
            OPERATOR_112_TRANSITIONS, OPERATOR_112_GUARDS
        )
        self.visibility_policy = DataVisibilityPolicy(
            role_type=RoleType.OPERATOR_112,
            sources=frozenset(
                {
                    VisibilitySource.OPERATOR_CARD,
                    VisibilitySource.CARD_REVISIONS,
                    VisibilitySource.TRANSCRIPT,
                    VisibilitySource.CALL_STATE,
                    VisibilitySource.NOTIFICATIONS,
                }
            ),
            # Exactly the OPERATOR_112 column of `40-realtime-protocol.md` §40.4 (ruling R6): a
            # `✔`/`▲`/`◆` row is a member of this whitelist regardless of the redaction or
            # per-connection filter §40.4 applies to that row's payload/delivery.
            visible_event_types=frozenset(
                {
                    EventType.SESSION_STARTED,
                    EventType.ROLE_STAGE_STARTED,
                    EventType.CALL_RINGING,
                    EventType.CALL_ANSWERED,
                    EventType.USER_SPEECH_STARTED,
                    EventType.USER_SPEECH_ENDED,
                    EventType.ASR_PARTIAL,
                    EventType.ASR_FINAL,
                    EventType.CALLER_TTS_STARTED,
                    EventType.CALLER_TTS_ENDED,
                    EventType.CALLER_UTTERANCE_INTERRUPTED,
                    EventType.CARD_FIELD_CHANGED,
                    EventType.SERVICE_SELECTED,
                    EventType.HANDOFF_CREATED,
                    EventType.ROLE_STAGE_COMPLETED,
                    EventType.SESSION_COMPLETED,
                    EventType.SESSION_ABORTED,
                    EventType.STAGE_STATE_CHANGED,
                    EventType.ROLE_TRANSITION_STARTED,
                    EventType.ROLE_TRANSITION_COMPLETED,
                    EventType.SERVICE_DESELECTED,
                    EventType.NOTIFICATION_CREATED,
                    EventType.NOTIFICATION_ACKNOWLEDGED,
                    EventType.RADIO_MESSAGE_CREATED,
                    EventType.CALL_ENDED,
                    EventType.TRANSPORT_DISCONNECTED,
                    EventType.TRANSPORT_RECONNECTED,
                }
            ),
        )

    def available_actions(self, stage_state: Enum) -> tuple[ActionDescriptor, ...]:
        assert isinstance(stage_state, Operator112StageState)
        return _AVAILABLE_ACTIONS[stage_state]

    def initial_state(self) -> Enum:
        return Operator112StageState.WAITING_FOR_CALL

    def terminal_states(self) -> frozenset[Enum]:
        return frozenset({Operator112StageState.STAGE_COMPLETED})
