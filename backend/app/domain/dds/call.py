"""`DdsCall` and `DDS_CALL_TRANSITIONS` — a ДДС trainee's telephone line (HLD `80-telephony.md`
§80.3.1, §80.3.2, D23; I3 E6b).

Under `dds_brigade_call: ON` the ДДС workstation has a phone (D25). One call is one `DdsCall`, keyed
by its own `call_id`, **beside** the 112 call and never inside it: the 112 call model
(`CallStateView`, `session:{id}:call_state`) is not widened, and nothing here reads or writes it.

The machine is table-driven (INV 8) like every other one of the domain: `DDS_CALL_TRANSITIONS` holds
the five rows of §80.3.2 that start from a state, and `start_call` is the `[*] --start--> DIALING`
row — there is no source state to key a table row by, so it is a constructor, and its guard
(`guard_dds_call_allowed`: session `ACTIVE`, DDS stage started, `dds_brigade_call = ON`, the action
in `available_actions`, one line per workstation) is the application's to check before calling it,
because every one of those facts lives outside the call.

Every accepted transition returns exactly one event (`start` → `DDS_CALL_STARTED`, `answer` →
`DDS_CALL_ANSWERED`, `no_answer` / `busy` / `hang_up` → `DDS_CALL_ENDED`), except `ring`, which
appends nothing new (§80.3.2: the `voice:join` publish after the commit is its only effect).

The guard facts a call cannot hold itself arrive the way the leg machine's do (`dds/response.py`):
`GuardRuntime.transport_ready` for `ring`, and a `CallGuardSubject` riding in
`GuardContext.assignment` (typed `Any` for exactly such role-specific subjects) for `answer`, whose
allowed actor depends on the call's direction.

`dds_call_ids(events)` is the one derived fact §80.6.2 builds call-scoped visibility and fact
scoring on: the DDS call ids of a session are the `call_id`s of its `DDS_CALL_STARTED` events, a
pure function of the log (P2/P4). `fold_dds_calls` rebuilds the whole `dds_calls` read model from
the same events (INV 13).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import AssignmentId, SessionId, UserId
from app.domain.common.state_machine import (
    GuardContext,
    GuardRuntime,
    StateMachine,
    Transition,
    TransitionTable,
)
from app.domain.enums import ActorType, ServiceId
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType

__all__ = [
    "DDS_CALL_EVENT_TYPES",
    "DDS_CALL_GUARDS",
    "DDS_CALL_MACHINE",
    "DDS_CALL_TRANSITIONS",
    "LIVE_CALL_STATES",
    "CallAnsweredBy",
    "CallEndpoint",
    "CallGuardSubject",
    "CallSelectionReason",
    "DdsCall",
    "DdsCallDirection",
    "DdsCallEndReason",
    "DdsCallKind",
    "DdsCallState",
    "DdsLineBusyError",
    "dds_call_ids",
    "dds_call_room_name",
    "fire_call_trigger",
    "fold_dds_calls",
    "start_call",
]


class DdsCallKind(str, Enum):
    """Who the ДДС is calling (§80.3.1)."""

    SERVICE_HEAD = "SERVICE_HEAD"
    """The brigade head of one leg's service (E6c)."""
    CLAIMANT = "CLAIMANT"
    """The scenario's caller, called back on the card's number (E6b, REQ-5917)."""
    OPERATOR_112 = "OPERATOR_112"
    """The 112 operator, answered by an AI operator in I3 (E6d, owner Q1)."""


class DdsCallDirection(str, Enum):
    OUTBOUND = "OUTBOUND"
    """The ДДС trainee placed the call."""
    INBOUND = "INBOUND"
    """The brigade calls the ДДС (REQ-1038 push, a `report: CALL_IN` step; E6c)."""


class CallEndpoint(str, Enum):
    """Where the trainee's side of the call is — never a variant switch (D25)."""

    BROWSER = "BROWSER"
    SIP = "SIP"


class DdsCallState(str, Enum):
    DIALING = "DIALING"
    RINGING = "RINGING"
    CONNECTED = "CONNECTED"
    ENDED = "ENDED"


class DdsCallEndReason(str, Enum):
    HANGUP = "HANGUP"
    NO_ANSWER = "NO_ANSWER"
    BUSY = "BUSY"
    ABORT = "ABORT"
    TRANSPORT_LOST = "TRANSPORT_LOST"


class CallAnsweredBy(str, Enum):
    AI = "AI"
    TRAINEE = "TRAINEE"
    """On an `OPERATOR_112` call: the reserved hook for a human 112 trainee (E6g, not in I3)."""


class CallSelectionReason(str, Enum):
    """Why this session was the one the call went to (§80.3.5, recorded on the event, P4)."""

    BROWSER_BUTTON = "BROWSER_BUTTON"
    LAST_OPENED_CARD = "LAST_OPENED_CARD"
    OLDEST_ACTIVE = "OLDEST_ACTIVE"
    INBOUND_SCRIPT = "INBOUND_SCRIPT"


LIVE_CALL_STATES: frozenset[DdsCallState] = frozenset(
    {DdsCallState.DIALING, DdsCallState.RINGING, DdsCallState.CONNECTED}
)
"""Every state but `ENDED` — a call in one of these occupies the trainee's line (§80.3.2)."""

DDS_CALL_EVENT_TYPES: frozenset[EventType] = frozenset(
    {EventType.DDS_CALL_STARTED, EventType.DDS_CALL_ANSWERED, EventType.DDS_CALL_ENDED}
)
"""The three events of this machine (E6b); `dds_calls` is rebuildable from them alone."""


class DdsLineBusyError(DomainError):
    """The trainee already has a live `DdsCall` in this session — one line per workstation
    (`409`)."""

    code = "DDS_LINE_BUSY"

    def __init__(self, call_id: uuid.UUID) -> None:
        self.call_id = call_id
        super().__init__(f"the caller already has a live ДДС call {call_id} in this session")


class DdsCall(BaseModel):
    """One ДДС call (§80.3.1). A row of the `dds_calls` read model, rebuildable from the log."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: uuid.UUID
    session_id: SessionId
    kind: DdsCallKind
    direction: DdsCallDirection
    assignment_id: AssignmentId | None
    """`SERVICE_HEAD`: the leg (70 §70.4.5); `None` otherwise."""
    service_type: ServiceId | None
    """`SERVICE_HEAD`: the leg's service; `None` otherwise."""
    dialed: str
    """`"101"`, `"7012"`, `"112"`, the claimant's digits."""
    endpoint: CallEndpoint
    room: str
    """`dds-{session_id}-{call_id}` — one LiveKit room per call (§80.2.2)."""
    persona_id: str | None
    """Resolved at start (§80.4.1); `None` for `CLAIMANT` (the scenario's `CallerProfile` is it)."""
    actor_user_id: UserId | None
    """The ДДС trainee on the line."""
    selection_reason: CallSelectionReason
    state: DdsCallState
    answered_by: CallAnsweredBy | None
    started_at_offset_ms: int
    answered_at_offset_ms: int | None
    ended_at_offset_ms: int | None
    end_reason: DdsCallEndReason | None

    @property
    def live(self) -> bool:
        """The call still occupies the line."""
        return self.state in LIVE_CALL_STATES


class CallGuardSubject(BaseModel):
    """The facts `answer`'s guard needs, riding in `GuardContext.assignment` (see the docstring)."""

    model_config = ConfigDict(frozen=True)

    direction: DdsCallDirection


def _transport_ready(ctx: GuardContext) -> bool:
    """`guard_dds_call_transport_ready`: LiveKit reachable ∧ agent heartbeat (as the 112 `ring`);
    for a `SIP` endpoint the gateway's `leg UP` is folded into the same runtime fact (E6e)."""
    return ctx.runtime.transport_ready


def _answer_actor_matches_direction(ctx: GuardContext) -> bool:
    """`answer`: the AI callee answers an OUTBOUND call, the trainee an INBOUND one (§80.3.2)."""
    subject = ctx.assignment
    if not isinstance(subject, CallGuardSubject):
        return False
    if subject.direction is DdsCallDirection.OUTBOUND:
        return ctx.actor.actor_type is ActorType.SIMULATION
    return ctx.actor.actor_type is ActorType.TRAINEE


DDS_CALL_GUARDS: Mapping[str, Callable[[GuardContext], bool]] = {
    "guard_dds_call_transport_ready": _transport_ready,
    "guard_dds_call_answer_actor": _answer_actor_matches_direction,
}

_SIM = frozenset({ActorType.SIMULATION})


def _row(
    source: DdsCallState,
    trigger: str,
    target: DdsCallState,
    actors: frozenset[ActorType],
    *,
    guard: str | None = None,
    emits: EventType | None = None,
) -> tuple[tuple[DdsCallState, str], Transition[DdsCallState]]:
    return (source, trigger), Transition(
        source=source,
        trigger=trigger,
        target=target,
        allowed_actors=actors,
        guard_name=guard,
        emits=emits,
    )


DDS_CALL_TRANSITIONS: TransitionTable[DdsCallState] = dict(
    [
        _row(
            DdsCallState.DIALING,
            "ring",
            DdsCallState.RINGING,
            _SIM,
            guard="guard_dds_call_transport_ready",
        ),
        _row(
            DdsCallState.RINGING,
            "answer",
            DdsCallState.CONNECTED,
            frozenset({ActorType.SIMULATION, ActorType.TRAINEE}),
            guard="guard_dds_call_answer_actor",
            emits=EventType.DDS_CALL_ANSWERED,
        ),
        _row(
            DdsCallState.RINGING,
            "no_answer",
            DdsCallState.ENDED,
            _SIM,
            emits=EventType.DDS_CALL_ENDED,
        ),
        _row(
            DdsCallState.RINGING, "busy", DdsCallState.ENDED, _SIM, emits=EventType.DDS_CALL_ENDED
        ),
        *(
            _row(
                source,
                "hang_up",
                DdsCallState.ENDED,
                frozenset({ActorType.TRAINEE, ActorType.SYSTEM}),
                emits=EventType.DDS_CALL_ENDED,
            )
            for source in (DdsCallState.DIALING, DdsCallState.RINGING, DdsCallState.CONNECTED)
        ),
    ]
)
"""§80.3.2 row for row, minus `[*] --start--> DIALING` (`start_call`). Any other `(state,
trigger)` is `InvalidTransitionError` — `409 INVALID_TRANSITION` (INV 8)."""

DDS_CALL_MACHINE: StateMachine[DdsCallState] = StateMachine(DDS_CALL_TRANSITIONS, DDS_CALL_GUARDS)

_FIXED_END_REASONS: Mapping[str, DdsCallEndReason] = {
    "no_answer": DdsCallEndReason.NO_ANSWER,
    "busy": DdsCallEndReason.BUSY,
}
_SYSTEM_HANG_UP_REASONS = frozenset({DdsCallEndReason.ABORT, DdsCallEndReason.TRANSPORT_LOST})


def dds_call_room_name(session_id: SessionId, call_id: uuid.UUID) -> str:
    """`dds-{session_id}-{call_id}`, both canonical lowercase (the 112 room's naming rule)."""
    return f"dds-{str(session_id).lower()}-{str(call_id).lower()}"


def start_call(
    *,
    call_id: uuid.UUID,
    session_id: SessionId,
    kind: DdsCallKind,
    direction: DdsCallDirection,
    dialed: str,
    endpoint: CallEndpoint,
    actor: ActorRef,
    now_ms: int,
    selection_reason: CallSelectionReason,
    assignment_id: AssignmentId | None = None,
    service_type: ServiceId | None = None,
    persona_id: str | None = None,
    callee_user_id: UserId | None = None,
) -> tuple[DdsCall, DomainEvent]:
    """`[*] --start--> DIALING` and its `DDS_CALL_STARTED` (§80.3.2, §80.6.1).

    The caller has checked `guard_dds_call_allowed`. What is checked here is what the call alone
    can tell: a `SERVICE_HEAD` call names its leg and nothing else does (the `dds_calls` CHECK), and
    an OUTBOUND call is the trainee's while an INBOUND one is the simulation's.

    `actor_user_id` is the ДДС trainee on the line: the caller of an OUTBOUND call, and for an
    INBOUND one (a brigade's `report: CALL_IN`, I3 E6c) the workstation it rings, `callee_user_id`
    — so one line per workstation, `hang_up` and `createVoiceToken {call_id}` read one field for
    both directions.
    """
    if (kind is DdsCallKind.SERVICE_HEAD) != (assignment_id is not None):
        raise DomainError(
            f"a {kind.value} call {'needs' if kind is DdsCallKind.SERVICE_HEAD else 'takes no'} "
            f"assignment_id"
        )
    expected = ActorType.TRAINEE if direction is DdsCallDirection.OUTBOUND else ActorType.SIMULATION
    if actor.actor_type is not expected:
        raise DomainError(f"a {direction.value} call is started by {expected.value}")
    room = dds_call_room_name(session_id, call_id)
    actor_user_id = actor.actor_id if direction is DdsCallDirection.OUTBOUND else callee_user_id
    call = DdsCall(
        call_id=call_id,
        session_id=session_id,
        kind=kind,
        direction=direction,
        assignment_id=assignment_id,
        service_type=service_type,
        dialed=dialed,
        endpoint=endpoint,
        room=room,
        persona_id=persona_id,
        actor_user_id=actor_user_id,
        selection_reason=selection_reason,
        state=DdsCallState.DIALING,
        answered_by=None,
        started_at_offset_ms=now_ms,
        answered_at_offset_ms=None,
        ended_at_offset_ms=None,
        end_reason=None,
    )
    event = DomainEvent(
        event_type=EventType.DDS_CALL_STARTED,
        actor=actor,
        monotonic_offset_ms=now_ms,
        payload={
            "call_id": call_id,
            "kind": kind.value,
            "direction": direction.value,
            "assignment_id": None if assignment_id is None else uuid.UUID(str(assignment_id)),
            "service_type": service_type,
            "dialed": dialed,
            "endpoint": endpoint.value,
            "room": room,
            "persona_id": persona_id,
            "actor_user_id": None if actor_user_id is None else uuid.UUID(str(actor_user_id)),
            "selection_reason": selection_reason.value,
            "at_offset_ms": now_ms,
        },
    )
    return call, event


def fire_call_trigger(
    call: DdsCall,
    trigger: str,
    *,
    actor: ActorRef,
    now_ms: int,
    runtime: GuardRuntime | None = None,
    end_reason: DdsCallEndReason | None = None,
) -> tuple[DdsCall, DomainEvent | None]:
    """Fire one `DDS_CALL_TRANSITIONS` trigger on `call`; raise what the machine raises.

    Returns the moved call and the one event the row emits (`None` for `ring`). `end_reason`
    matters only for a SYSTEM `hang_up` — `ABORT` (the default) or `TRANSPORT_LOST`; a TRAINEE
    `hang_up` is always `HANGUP`, and `no_answer` / `busy` name their own reason.
    """
    ctx = GuardContext(
        actor=actor,
        now_ms=now_ms,
        assignment=CallGuardSubject(direction=call.direction),
        runtime=runtime if runtime is not None else GuardRuntime(),
    )
    target = DDS_CALL_MACHINE.fire(call.state, trigger, ctx)
    if trigger == "ring":
        return call.model_copy(update={"state": target}), None
    if trigger == "answer":
        answered_by = (
            CallAnsweredBy.AI
            if actor.actor_type is ActorType.SIMULATION
            else CallAnsweredBy.TRAINEE
        )
        moved = call.model_copy(
            update={
                "state": target,
                "answered_by": answered_by,
                "answered_at_offset_ms": now_ms,
            }
        )
        return moved, DomainEvent(
            event_type=EventType.DDS_CALL_ANSWERED,
            actor=actor,
            monotonic_offset_ms=now_ms,
            payload={
                "call_id": call.call_id,
                "answered_by": answered_by.value,
                "at_offset_ms": now_ms,
            },
        )
    reason = _end_reason(trigger, actor, end_reason)
    duration_ms = (
        0 if call.answered_at_offset_ms is None else max(0, now_ms - call.answered_at_offset_ms)
    )
    moved = call.model_copy(
        update={"state": target, "ended_at_offset_ms": now_ms, "end_reason": reason}
    )
    return moved, DomainEvent(
        event_type=EventType.DDS_CALL_ENDED,
        actor=actor,
        monotonic_offset_ms=now_ms,
        payload={
            "call_id": call.call_id,
            "reason": reason.value,
            "duration_ms": duration_ms,
            "at_offset_ms": now_ms,
        },
    )


def _end_reason(
    trigger: str, actor: ActorRef, requested: DdsCallEndReason | None
) -> DdsCallEndReason:
    fixed = _FIXED_END_REASONS.get(trigger)
    if fixed is not None:
        return fixed
    if actor.actor_type is ActorType.TRAINEE:
        return DdsCallEndReason.HANGUP
    if requested is None:
        return DdsCallEndReason.ABORT
    if requested not in _SYSTEM_HANG_UP_REASONS:
        raise DomainError(
            f"a SYSTEM hang_up ends a call as ABORT or TRANSPORT_LOST, not {requested}"
        )
    return requested


# ---------------------------------------------------------------------------------------------
# Folds over the log (§80.6.2, INV 13)
# ---------------------------------------------------------------------------------------------


def dds_call_ids(events: Iterable[SessionEvent | Any]) -> frozenset[str]:
    """The session's DDS call ids: the `call_id`s of its `DDS_CALL_STARTED` events (§80.6.2).

    Lowercase strings, so a payload's `call_id` — a `UUID` on the write path, a string after a JSON
    round trip — compares with one `str(...).lower()`. Accepts anything with `event_type` and
    `payload` (a stored row, a realtime source event).
    """
    return frozenset(
        str(event.payload["call_id"]).lower()
        for event in events
        if event.event_type is EventType.DDS_CALL_STARTED and event.payload.get("call_id")
    )


def fold_dds_calls(session_id: SessionId, events: Sequence[SessionEvent]) -> list[DdsCall]:
    """Rebuild every `DdsCall` of the session from its `DDS_CALL_*` events, oldest first (INV 13).

    `ring` appends no event (§80.3.2), so an unanswered live call folds to `DIALING`: the log cannot
    tell the two apart, and it does not need to — the next tick's `ring` is idempotent in effect
    (it appends nothing) and the read model, written in the ring's own Unit of Work, holds the
    finer state.
    """
    calls: dict[str, DdsCall] = {}
    for event in events:
        payload = event.payload
        if event.event_type is EventType.DDS_CALL_STARTED:
            call_id = uuid.UUID(str(payload["call_id"]))
            assignment = payload.get("assignment_id")
            actor_user = payload.get("actor_user_id")
            calls[str(call_id)] = DdsCall(
                call_id=call_id,
                session_id=session_id,
                kind=DdsCallKind(str(payload["kind"])),
                direction=DdsCallDirection(str(payload["direction"])),
                assignment_id=None
                if assignment is None
                else AssignmentId(uuid.UUID(str(assignment))),
                service_type=payload.get("service_type"),
                dialed=str(payload["dialed"]),
                endpoint=CallEndpoint(str(payload["endpoint"])),
                room=str(payload["room"]),
                persona_id=payload.get("persona_id"),
                actor_user_id=None if actor_user is None else UserId(uuid.UUID(str(actor_user))),
                selection_reason=CallSelectionReason(str(payload["selection_reason"])),
                state=DdsCallState.DIALING,
                answered_by=None,
                started_at_offset_ms=int(payload.get("at_offset_ms", event.monotonic_offset_ms)),
                answered_at_offset_ms=None,
                ended_at_offset_ms=None,
                end_reason=None,
            )
            continue
        if event.event_type not in DDS_CALL_EVENT_TYPES:
            continue
        key = str(payload.get("call_id", "")).lower()
        call = calls.get(key)
        if call is None:
            continue
        at = int(payload.get("at_offset_ms", event.monotonic_offset_ms))
        if event.event_type is EventType.DDS_CALL_ANSWERED:
            calls[key] = call.model_copy(
                update={
                    "state": DdsCallState.CONNECTED,
                    "answered_by": CallAnsweredBy(str(payload["answered_by"])),
                    "answered_at_offset_ms": at,
                }
            )
        else:
            calls[key] = call.model_copy(
                update={
                    "state": DdsCallState.ENDED,
                    "ended_at_offset_ms": at,
                    "end_reason": DdsCallEndReason(str(payload["reason"])),
                }
            )
    return list(calls.values())
