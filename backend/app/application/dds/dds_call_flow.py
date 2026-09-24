"""`AdvanceDdsCalls` — the SIMULATION side of the ДДС phone line (I3 E6b, HLD `80-telephony.md`
§80.3.2, §80.3.6, D23).

Three rows of `DDS_CALL_TRANSITIONS` are the simulation's, never the trainee's, and this module is
where they fire — as a `SimulationRunner` `after_tick` hook beside `AdvanceCallFlow` (the 112
call's, untouched) and `DdsStageAutomation`:

* `DIALING --ring--> RINGING`, guarded on `transport_ready` exactly as the 112 `ring` is (LiveKit
  reachable ∧ agent heartbeat). It appends nothing; after the commit `voice:join` is published for
  the call's own room with the additive keys of §80.3.6 (`call_kind`, `assignment_id`,
  `persona_id`, `endpoint`);
* `RINGING --busy--> ENDED` for a `CLAIMANT` while the session's 112 call is `RINGING` or
  `CONNECTED` — the claimant cannot be on two calls at once (the frozen `CallerBelief` would be
  driven by two pipelines, §80.13);
* `RINGING --answer--> CONNECTED` by the AI callee of an OUTBOUND call, `answer_after_ms` after the
  call started (a persona's `answer_after_ms` from E6c; the claimant uses the persona default).

Two more duties, both SYSTEM's:

* a live call whose DDS stage is no longer the session's active stage in a state that holds the
  card (`RECEIVED` / `ACKNOWLEDGED`) is hung up by SYSTEM with `end_reason ABORT` (§80.3.2 "stage
  completion"), and `voice:cancel:{session_id} {call_id, reason: ABORT}` follows the commit;
* `voice:join` is re-published per `call_id` every `join_retry_ms` while the call is `RINGING` or
  `CONNECTED` and the agent has appended nothing of its own for it — §40.6's self-healing rule,
  per call (§80.3.6).

`ring_now` and `join_extra` are shared with `startDdsCall`, which rings a call in its own command
when the transport is already up (the common case), so the trainee hears the ringback at once.

This module never touches the 112 call: it reads `project_call_state` for the busy rule and
nothing else, and it never writes `session:{id}:call_state` (§80.3.6).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.application.operator.views import CallPhase, project_call_state
from app.application.ports.call_transport_status import CallTransportStatus
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.voice_signal_publisher import VoiceSignalPublisher
from app.application.simulation.sim_time import running_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import SessionId
from app.domain.common.state_machine import GuardRuntime
from app.domain.dds.call import (
    DDS_CALL_EVENT_TYPES,
    DdsCall,
    DdsCallDirection,
    DdsCallEndReason,
    DdsCallKind,
    DdsCallState,
    fire_call_trigger,
)
from app.domain.enums import ActorType, DDSStageState, RoleType, SessionState
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.session.session import SimulationSession
from app.domain.session.variants import DdsBrigadeCall

__all__ = [
    "DEFAULT_ANSWER_AFTER_MS",
    "AdvanceDdsCalls",
    "CallSignal",
    "agent_joined_call",
    "claimant_busy",
    "join_extra",
    "publish_signals",
    "ring_now",
]

logger = logging.getLogger(__name__)

DEFAULT_ANSWER_AFTER_MS = 4000
"""A persona's default `answer_after_ms` (HLD 80 §80.4.1); the claimant answers after it too."""

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)
_SYSTEM = ActorRef(actor_type=ActorType.SYSTEM)
_LIVE_112_PHASES = frozenset({CallPhase.RINGING, CallPhase.CONNECTED})
_CALL_HOLDING_STATES = frozenset({DDSStageState.RECEIVED, DDSStageState.ACKNOWLEDGED})
"""The DDS stage states a ДДС call may stay live in — the ones `call_claimant` is offered in."""


@dataclass(frozen=True)
class CallSignal:
    """One Redis signal owed after a commit: `voice:join` or `voice:cancel` for one ДДС call."""

    call: DdsCall
    cancel_reason: str | None = None
    at_offset_ms: int = 0


def join_extra(call: DdsCall) -> Mapping[str, str | None]:
    """`voice:join`'s additive keys for a ДДС call (HLD 80 §80.3.6)."""
    return {
        "call_kind": call.kind.value,
        "assignment_id": None if call.assignment_id is None else str(call.assignment_id).lower(),
        "persona_id": call.persona_id,
        "endpoint": call.endpoint.value,
    }


def claimant_busy(log: Sequence[SessionEvent]) -> bool:
    """The claimant is on the 112 call right now (§80.3.2 `busy`)."""
    return project_call_state(log).phase in _LIVE_112_PHASES


def agent_joined_call(log: Sequence[SessionEvent], call_id: UUID) -> bool:
    """The voice agent appended something of its own for this ДДС call (§40.6's only ack).

    The backend's own events for a ДДС call are the three `DDS_CALL_*`; every other event naming
    the call's id — `USER_SPEECH_*`, `ASR_*`, `CALLER_TTS_*`, `TRANSPORT_*`, … — is the agent's.
    """
    wanted = str(call_id).lower()
    for event in log:
        if event.event_type in DDS_CALL_EVENT_TYPES:
            continue
        raw = event.payload.get("call_id")
        if raw is not None and str(raw).lower() == wanted:
            return True
    return False


async def ring_now(
    uow: UnitOfWork,
    call: DdsCall,
    *,
    now_ms: int,
    transport_ready: bool,
    log: Sequence[SessionEvent],
) -> tuple[DdsCall, list[DomainEvent]]:
    """`ring` a `DIALING` call when the transport is up, then — for a claimant whose 112 call is
    live — `busy`. Returns the call as it now stands and the events to append (none for `ring`).

    Persists the moved call through `uow.dds_calls`; the caller appends the events.
    """
    if call.state is not DdsCallState.DIALING or not transport_ready:
        return call, []
    try:
        rung, _ = fire_call_trigger(
            call,
            "ring",
            actor=_SIMULATION,
            now_ms=now_ms,
            runtime=GuardRuntime(transport_ready=True),
        )
    except InvalidTransitionError:  # pragma: no cover - checked just above
        return call, []
    events: list[DomainEvent] = []
    if rung.kind is DdsCallKind.CLAIMANT and claimant_busy(log):
        rung, ended = fire_call_trigger(rung, "busy", actor=_SIMULATION, now_ms=now_ms)
        assert ended is not None
        events.append(ended)
    await uow.dds_calls.save(rung)
    return rung, events


async def publish_signals(
    voice_signals: VoiceSignalPublisher | None, session_id: SessionId, signals: Sequence[CallSignal]
) -> None:
    """Publish the owed signals, after the commit (§40.6: never inside the transaction)."""
    if voice_signals is None:
        return
    for signal in signals:
        if signal.cancel_reason is not None:
            await voice_signals.publish_cancel(
                session_id,
                call_id=signal.call.call_id,
                reason=signal.cancel_reason,
                at_offset_ms=signal.at_offset_ms,
            )
        else:
            await voice_signals.publish_join(
                session_id,
                room=signal.call.room,
                call_id=signal.call.call_id,
                extra=join_extra(signal.call),
            )


class AdvanceDdsCalls:
    """Fire whatever the session's live ДДС calls are now due (see the module docstring)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        call_transport: CallTransportStatus,
        voice_signals: VoiceSignalPublisher | None = None,
        *,
        answer_after_ms: int = DEFAULT_ANSWER_AFTER_MS,
        join_retry_ms: int = 2000,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._call_transport = call_transport
        self._voice_signals = voice_signals
        self._answer_after_ms = answer_after_ms
        self._join_retry_ms = join_retry_ms
        #: `call_id -> monotonic ms of the last `voice:join``: a rate limiter, not state (§40.6).
        self._last_join_ms: dict[UUID, int] = {}

    async def __call__(self, session_id: SessionId) -> bool:
        """One transaction; `True` when a transition fired. Never raises for an idle session."""
        signals: list[CallSignal] = []
        fired = False
        async with self._unit_of_work() as uow:
            # The cheap read first: a session with no live ДДС call — every `OFF` session, and an
            # `ON` one between calls — costs one indexed query and takes no row lock.
            if not await uow.dds_calls.list_live(session_id):
                return False
            session = await uow.sessions.get_for_update(session_id)
            if session is None or session.state is not SessionState.ACTIVE:
                return False
            if session.variants.dds_brigade_call is not DdsBrigadeCall.ON:
                return False
            live = await uow.dds_calls.list_live(session_id)
            log = list(await uow.events.read(session_id))
            now_ms = running_ms(session, self._clock.now())
            holding = _stage_holds_calls(session)
            transport_ready: bool | None = None
            for call in live:
                if not holding:
                    ended, event = fire_call_trigger(
                        call,
                        "hang_up",
                        actor=_SYSTEM,
                        now_ms=now_ms,
                        end_reason=DdsCallEndReason.ABORT,
                    )
                    await uow.dds_calls.save(ended)
                    assert event is not None
                    log.extend(await uow.events.append(session_id, [event]))
                    signals.append(CallSignal(ended, cancel_reason="ABORT", at_offset_ms=now_ms))
                    fired = True
                    continue
                if call.state is DdsCallState.DIALING and transport_ready is None:
                    transport_ready = await self._call_transport.transport_ready(session_id)
                moved, events = await self._advance(uow, call, now_ms, log, bool(transport_ready))
                if moved.state is not call.state:
                    fired = True
                if events:
                    log.extend(await uow.events.append(session_id, events))
                if (
                    moved.state is DdsCallState.RINGING and call.state is DdsCallState.DIALING
                ) or self._join_due(moved, log):
                    signals.append(CallSignal(moved))
                    self._last_join_ms[moved.call_id] = self._clock.monotonic_ms()
            if fired:
                await uow.commit()
            elif not signals:
                return False
        await publish_signals(self._voice_signals, session_id, signals)
        return fired

    async def _advance(
        self,
        uow: UnitOfWork,
        call: DdsCall,
        now_ms: int,
        log: Sequence[SessionEvent],
        transport_ready: bool,
    ) -> tuple[DdsCall, list[DomainEvent]]:
        """Ring a `DIALING` call, or let the AI callee answer a `RINGING` OUTBOUND one."""
        if call.state is DdsCallState.DIALING:
            return await ring_now(
                uow, call, now_ms=now_ms, transport_ready=transport_ready, log=log
            )
        if (
            call.state is DdsCallState.RINGING
            and call.direction is DdsCallDirection.OUTBOUND
            and now_ms >= call.started_at_offset_ms + self._answer_after_ms
        ):
            if call.kind is DdsCallKind.CLAIMANT and claimant_busy(log):
                ended, event = fire_call_trigger(call, "busy", actor=_SIMULATION, now_ms=now_ms)
                await uow.dds_calls.save(ended)
                return ended, [] if event is None else [event]
            answered, event = fire_call_trigger(call, "answer", actor=_SIMULATION, now_ms=now_ms)
            await uow.dds_calls.save(answered)
            return answered, [] if event is None else [event]
        return call, []

    def _join_due(self, call: DdsCall, log: Sequence[SessionEvent]) -> bool:
        """§40.6's per-call retry: live, no agent yet, `join_retry_ms` since the last publish."""
        if self._voice_signals is None:
            return False
        if call.state not in (DdsCallState.RINGING, DdsCallState.CONNECTED):
            return False
        last = self._last_join_ms.get(call.call_id)
        if last is not None and self._clock.monotonic_ms() - last < self._join_retry_ms:
            return False
        return not agent_joined_call(log, call.call_id)


def _stage_holds_calls(session: SimulationSession) -> bool:
    """The session's active stage is its DDS stage in a state a ДДС call may stay live in."""
    stage = session.current_stage
    if stage is None or stage.role_type is not RoleType.DDS:
        return False
    return stage.state in _CALL_HOLDING_STATES
