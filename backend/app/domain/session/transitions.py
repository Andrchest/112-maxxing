"""`SESSION_TRANSITIONS`, `OPERATOR_112_TRANSITIONS`, `DDS_TRANSITIONS` (HLD `10-domain-model.md`
§10.8, SPEC §7).

Every row below copies the HLD tables literally: `trigger`/`guard_name` strings, `allowed_actors`,
`allowed_roles`, and `emits`. Two clarifications the HLD tables state in prose rather than as
table data:

- A "Who may fire" cell written `TRAINEE (ROLE)` means `allowed_actors = {TRAINEE}` and
  `allowed_roles = {ROLE}`; a cell listing several actor types (e.g. `INSTRUCTOR, SYSTEM`) means
  `allowed_roles` is empty for that row (`StateMachine` only checks `allowed_roles` when the
  firing actor is `TRAINEE` — a non-trainee actor is never "playing" a `RoleStage`). A row like
  `TRAINEE (OPERATOR_112), SIMULATION` (Operator 112 `complete_stage`) therefore reads as "a
  TRAINEE assigned to OPERATOR_112, or any SIMULATION actor".
- `emits` is `Transition`'s single named event (§10.8); the HLD prose "every transition
  additionally emits `STAGE_STATE_CHANGED`" (and, for DDS `close`, the additional
  `ROLE_STAGE_COMPLETED`) is a use-case-level convention applied on top of every fired
  transition, not per-row table data — `Transition.emits` has no list field to hold two events.

Guard *callables* for the `guard_name`s below are not implemented here — they live in
`session/guards.py` (`SESSION_GUARDS`, `OPERATOR_112_GUARDS`, `DDS_GUARDS`) and are wired into the
state machines by `roles/registry.py`; see `common/state_machine.py`'s module docstring.
"""

from __future__ import annotations

from app.domain.common.state_machine import Transition, TransitionTable
from app.domain.enums import ActorType, DDSStageState, Operator112StageState, RoleType, SessionState
from app.domain.events.types import EventType

_TRAINEE = frozenset({ActorType.TRAINEE})
_SIMULATION = frozenset({ActorType.SIMULATION})
_TRAINEE_OR_SIMULATION = frozenset({ActorType.TRAINEE, ActorType.SIMULATION})
_INSTRUCTOR_SYSTEM = frozenset({ActorType.INSTRUCTOR, ActorType.SYSTEM})
_SYSTEM = frozenset({ActorType.SYSTEM})
_INSTRUCTOR = frozenset({ActorType.INSTRUCTOR})

_OPERATOR_112_ROLE = frozenset({RoleType.OPERATOR_112})
_DDS_ROLE = frozenset({RoleType.DDS})

# ---------------------------------------------------------------------------------------------
# Session state machine (§10.8 "Session state machine")
# ---------------------------------------------------------------------------------------------

_SESSION_ROWS: tuple[Transition[SessionState], ...] = (
    Transition(
        source=SessionState.CREATED,
        trigger="validate",
        target=SessionState.READY,
        allowed_actors=_SYSTEM,
        guard_name="guard_scenario_valid_and_participants_assigned",
        emits=None,
    ),
    Transition(
        source=SessionState.CREATED,
        trigger="abort",
        target=SessionState.ABORTED,
        allowed_actors=_INSTRUCTOR_SYSTEM,
        emits=EventType.SESSION_ABORTED,
    ),
    Transition(
        source=SessionState.READY,
        trigger="start",
        target=SessionState.ACTIVE,
        allowed_actors=_INSTRUCTOR,
        guard_name="guard_inference_ready",
        emits=EventType.SESSION_STARTED,
    ),
    Transition(
        source=SessionState.READY,
        trigger="abort",
        target=SessionState.ABORTED,
        allowed_actors=_INSTRUCTOR_SYSTEM,
        emits=EventType.SESSION_ABORTED,
    ),
    Transition(
        source=SessionState.ACTIVE,
        trigger="begin_role_transition",
        target=SessionState.ROLE_TRANSITION,
        allowed_actors=_SYSTEM,
        guard_name="guard_stage_terminal_and_next_exists",
        emits=EventType.ROLE_TRANSITION_STARTED,
    ),
    Transition(
        source=SessionState.ACTIVE,
        trigger="complete",
        target=SessionState.COMPLETED,
        allowed_actors=_SYSTEM,
        guard_name="guard_stage_terminal_and_last",
        emits=EventType.SESSION_COMPLETED,
    ),
    Transition(
        source=SessionState.ACTIVE,
        trigger="abort",
        target=SessionState.ABORTED,
        allowed_actors=_INSTRUCTOR_SYSTEM,
        emits=EventType.SESSION_ABORTED,
    ),
    Transition(
        source=SessionState.ROLE_TRANSITION,
        trigger="finish_role_transition",
        target=SessionState.ACTIVE,
        allowed_actors=_SYSTEM,
        guard_name="guard_pause_elapsed_and_next_assigned",
        emits=EventType.ROLE_TRANSITION_COMPLETED,
    ),
    Transition(
        source=SessionState.ROLE_TRANSITION,
        trigger="abort",
        target=SessionState.ABORTED,
        allowed_actors=_INSTRUCTOR_SYSTEM,
        emits=EventType.SESSION_ABORTED,
    ),
)

SESSION_TRANSITIONS: TransitionTable[SessionState] = {
    (row.source, row.trigger): row for row in _SESSION_ROWS
}

# ---------------------------------------------------------------------------------------------
# Operator 112 stage machine (§10.8 "Operator 112 stage machine")
# ---------------------------------------------------------------------------------------------

_OPERATOR_112_ABORTABLE_STATES: tuple[Operator112StageState, ...] = (
    Operator112StageState.WAITING_FOR_CALL,
    Operator112StageState.RINGING,
    Operator112StageState.CONNECTED,
    Operator112StageState.INTERVIEW,
    Operator112StageState.HANDOFF_PREPARATION,
    Operator112StageState.HANDED_OFF,
)

_OPERATOR_112_ROWS: tuple[Transition[Operator112StageState], ...] = (
    Transition(
        source=Operator112StageState.WAITING_FOR_CALL,
        trigger="ring",
        target=Operator112StageState.RINGING,
        allowed_actors=_SIMULATION,
        guard_name="guard_session_active_and_transport_ready",
        emits=EventType.CALL_RINGING,
    ),
    Transition(
        source=Operator112StageState.RINGING,
        trigger="answer",
        target=Operator112StageState.CONNECTED,
        allowed_actors=_TRAINEE,
        allowed_roles=_OPERATOR_112_ROLE,
        guard_name="guard_participant_assigned_to_stage",
        emits=EventType.CALL_ANSWERED,
    ),
    Transition(
        source=Operator112StageState.CONNECTED,
        trigger="begin_interview",
        target=Operator112StageState.INTERVIEW,
        allowed_actors=_SIMULATION,
        guard_name="guard_first_finalized_turn",
        emits=None,
    ),
    Transition(
        source=Operator112StageState.INTERVIEW,
        trigger="open_handoff_preparation",
        target=Operator112StageState.HANDOFF_PREPARATION,
        allowed_actors=_TRAINEE,
        allowed_roles=_OPERATOR_112_ROLE,
        emits=None,
    ),
    Transition(
        source=Operator112StageState.HANDOFF_PREPARATION,
        trigger="back_to_interview",
        target=Operator112StageState.INTERVIEW,
        allowed_actors=_TRAINEE,
        allowed_roles=_OPERATOR_112_ROLE,
        guard_name="guard_call_still_connected",
        emits=None,
    ),
    Transition(
        source=Operator112StageState.HANDOFF_PREPARATION,
        trigger="create_handoff",
        target=Operator112StageState.HANDED_OFF,
        allowed_actors=_TRAINEE,
        allowed_roles=_OPERATOR_112_ROLE,
        guard_name="guard_at_least_one_recipient_service",
        emits=EventType.HANDOFF_CREATED,
    ),
    Transition(
        source=Operator112StageState.HANDED_OFF,
        trigger="complete_stage",
        target=Operator112StageState.STAGE_COMPLETED,
        allowed_actors=_TRAINEE_OR_SIMULATION,
        allowed_roles=_OPERATOR_112_ROLE,
        guard_name="guard_call_ended",
        emits=EventType.ROLE_STAGE_COMPLETED,
    ),
    *(
        Transition(
            source=state,
            trigger="abort_stage",
            target=Operator112StageState.STAGE_COMPLETED,
            allowed_actors=_INSTRUCTOR_SYSTEM,
            emits=None,
        )
        for state in _OPERATOR_112_ABORTABLE_STATES
    ),
)

OPERATOR_112_TRANSITIONS: TransitionTable[Operator112StageState] = {
    (row.source, row.trigger): row for row in _OPERATOR_112_ROWS
}

# ---------------------------------------------------------------------------------------------
# DDS stage machine (§10.8 "DDS stage machine")
# ---------------------------------------------------------------------------------------------

_DDS_ABORTABLE_STATES: tuple[DDSStageState, ...] = (
    DDSStageState.RECEIVED,
    DDSStageState.ACKNOWLEDGED,
    DDSStageState.RESOURCE_SELECTION,
    DDSStageState.DISPATCHED,
    DDSStageState.EN_ROUTE,
    DDSStageState.ARRIVED,
    DDSStageState.WORKING,
    DDSStageState.RESOLVED,
)

_DDS_DISPATCH_ADDITIONAL_STATES: tuple[DDSStageState, ...] = (
    DDSStageState.EN_ROUTE,
    DDSStageState.ARRIVED,
    DDSStageState.WORKING,
)

_DDS_ROWS: tuple[Transition[DDSStageState], ...] = (
    Transition(
        source=DDSStageState.RECEIVED,
        trigger="acknowledge",
        target=DDSStageState.ACKNOWLEDGED,
        allowed_actors=_TRAINEE,
        allowed_roles=_DDS_ROLE,
        guard_name="guard_participant_assigned_to_stage",
        emits=EventType.DDS_ACKNOWLEDGED,
    ),
    Transition(
        source=DDSStageState.ACKNOWLEDGED,
        trigger="open_resource_selection",
        target=DDSStageState.RESOURCE_SELECTION,
        allowed_actors=_TRAINEE,
        allowed_roles=_DDS_ROLE,
        emits=None,
    ),
    Transition(
        source=DDSStageState.RESOURCE_SELECTION,
        trigger="dispatch",
        target=DDSStageState.DISPATCHED,
        allowed_actors=_TRAINEE,
        allowed_roles=_DDS_ROLE,
        guard_name="guard_at_least_one_selected_available",
        emits=EventType.RESOURCE_DISPATCHED,
    ),
    Transition(
        source=DDSStageState.RESOURCE_SELECTION,
        trigger="back_to_acknowledged",
        target=DDSStageState.ACKNOWLEDGED,
        allowed_actors=_TRAINEE,
        allowed_roles=_DDS_ROLE,
        guard_name="guard_no_resource_selected",
        emits=None,
    ),
    Transition(
        source=DDSStageState.DISPATCHED,
        trigger="open_resource_selection",
        target=DDSStageState.RESOURCE_SELECTION,
        allowed_actors=_TRAINEE,
        allowed_roles=_DDS_ROLE,
        guard_name="guard_additional_dispatch_allowed",
        emits=None,
    ),
    Transition(
        source=DDSStageState.DISPATCHED,
        trigger="first_en_route",
        target=DDSStageState.EN_ROUTE,
        allowed_actors=_SIMULATION,
        guard_name="guard_any_dispatched_reached_en_route",
        emits=None,
    ),
    Transition(
        source=DDSStageState.EN_ROUTE,
        trigger="first_arrived",
        target=DDSStageState.ARRIVED,
        allowed_actors=_SIMULATION,
        guard_name="guard_any_dispatched_reached_on_scene",
        emits=None,
    ),
    Transition(
        source=DDSStageState.ARRIVED,
        trigger="work_started",
        target=DDSStageState.WORKING,
        allowed_actors=_SIMULATION,
        guard_name="guard_any_dispatched_reached_working",
        emits=None,
    ),
    Transition(
        source=DDSStageState.WORKING,
        trigger="incident_resolved",
        target=DDSStageState.RESOLVED,
        allowed_actors=_SIMULATION,
        guard_name="guard_resolution_condition",
        emits=None,
    ),
    Transition(
        source=DDSStageState.RESOLVED,
        trigger="close",
        target=DDSStageState.CLOSED,
        allowed_actors=_TRAINEE,
        allowed_roles=_DDS_ROLE,
        emits=EventType.DDS_INCIDENT_CLOSED,
    ),
    # I3 E5a (HLD 70 §70.4.4, D16, manager decision O-1): the one additive row — memo mode's only
    # way out of ACKNOWLEDGED. Its guard denies in picker mode, so picker sessions are unchanged.
    Transition(
        source=DDSStageState.ACKNOWLEDGED,
        trigger="close",
        target=DDSStageState.RESOLVED,
        allowed_actors=_TRAINEE,
        allowed_roles=_DDS_ROLE,
        guard_name="memo_all_legs_terminal",
        emits=None,
    ),
    *(
        Transition(
            source=state,
            trigger="dispatch_additional",
            target=state,
            allowed_actors=_TRAINEE,
            allowed_roles=_DDS_ROLE,
            guard_name="guard_at_least_one_selected_available",
            emits=EventType.RESOURCE_DISPATCHED,
        )
        for state in _DDS_DISPATCH_ADDITIONAL_STATES
    ),
    *(
        Transition(
            source=state,
            trigger="abort_stage",
            target=DDSStageState.CLOSED,
            allowed_actors=_INSTRUCTOR_SYSTEM,
            emits=None,
        )
        for state in _DDS_ABORTABLE_STATES
    ),
)

DDS_TRANSITIONS: TransitionTable[DDSStageState] = {
    (row.source, row.trigger): row for row in _DDS_ROWS
}

MEMO_DDS_TRIGGERS: frozenset[str] = frozenset({"acknowledge", "close", "abort_stage"})
"""The stage triggers memo mode fires (HLD 70 §70.4.4): `RESOURCE_SELECTION` … `WORKING` are never
entered, so no resource trigger belongs to it."""

MEMO_DDS_TRANSITIONS: TransitionTable[DDSStageState] = {
    key: row for key, row in DDS_TRANSITIONS.items() if row.trigger in MEMO_DDS_TRIGGERS
}
"""`DDS_TRANSITIONS` restricted to `MEMO_DDS_TRIGGERS` — a view of the one table, not a second one.

The memo `DDSModule` machine runs over it, so every resource trigger (`open_resource_selection`,
`dispatch`, the four SIMULATION rows, …) is refused in memo mode as the ordinary "no such
transition" (INV 8), including `open_resource_selection`, whose row has no guard to deny it."""
