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
  call started (the persona's `answer_after_ms`, I3 E6c; the claimant uses the persona default);
* `RINGING --busy--> ENDED` at ring for a persona marked `busy`, and `RINGING --no_answer-->
  ENDED` `ring_timeout_ms` after the start for a persona marked `no_answer` (REQ-5325 «телефон не
  работает либо не отвечают») and for an INBOUND call the trainee never answers (I3 E6c).

Two more duties, both SYSTEM's:

* a live call whose DDS stage is no longer the session's active stage in a state that holds the
  card (`RECEIVED` / `ACKNOWLEDGED`) is hung up by SYSTEM with `end_reason ABORT` (§80.3.2 "stage
  completion"), and `voice:cancel:{session_id} {call_id, reason: ABORT}` follows the commit;
* `voice:join` is re-published per `call_id` every `join_retry_ms` while the call is `RINGING` or
  `CONNECTED` and the agent has appended nothing of its own for it — §40.6's self-healing rule,
  per call (§80.3.6).

`ring_now` and `join_extra` are shared with `startDdsCall`, which rings a call in its own command
when the transport is already up (the common case), so the trainee hears the ringback at once.

**The softphone endpoint (I3 E6e, §80.2.3, §80.3.7).** An OUTBOUND call whose endpoint is `SIP` is
rung only by the SIP gateway's `leg UP` report (`reportSipLeg`): §80.3.2's
`guard_dds_call_transport_ready` holds for it when the transport is up **and** the gateway is in the
room with the softphone connected, so neither `startDdsCall` nor this tick rings it on the transport
alone (`ring_now(leg_up=False)`). While such a call placed from the browser button waits in
`DIALING` for the gateway to ring the softphone, `voice:join {endpoint: SIP, sip_user}` is
re-published every `join_retry_ms` — the same self-healing rule, aimed at the gateway. An
INBOUND `SIP` call (a brigade's `CALL_IN`) is rung by this tick as before: its `voice:join` is what
makes the gateway ring the softphone, and the gateway's `leg UP` is then the trainee's `answer`.

`end_live_calls` is SYSTEM's `hang_up` (`ABORT`) of every live call of a session, shared by
`closeDdsIncident` and `abortSession` (§80.3.2 "session abort, stage completion"): both end the
line in their own Unit of Work and publish `voice:cancel` after their commit, so no call outlives
its session.

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
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.voice_signal_publisher import VoiceSignalPublisher
from app.application.reference.card_schemas import session_pack_id
from app.application.reference.queries import reference_catalog
from app.application.simulation.sim_time import running_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import SessionId
from app.domain.common.state_machine import GuardRuntime
from app.domain.dds.call import (
    DDS_CALL_EVENT_TYPES,
    CallEndpoint,
    CallSelectionReason,
    DdsCall,
    DdsCallDirection,
    DdsCallEndReason,
    DdsCallKind,
    DdsCallState,
    fire_call_trigger,
)
from app.domain.dds.personas import DEFAULT_ANSWER_AFTER_MS, Persona
from app.domain.enums import ActorType, DDSStageState, RoleType, SessionState
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.session.session import SimulationSession
from app.domain.session.variants import DdsBrigadeCall

__all__ = [
    "DEFAULT_ANSWER_AFTER_MS",
    "DEFAULT_RING_TIMEOUT_MS",
    "AdvanceDdsCalls",
    "CallSignal",
    "agent_joined_call",
    "awaits_gateway_leg",
    "call_persona",
    "claimant_busy",
    "end_live_calls",
    "join_extra",
    "line_owner_username",
    "publish_signals",
    "ring_now",
]

logger = logging.getLogger(__name__)

DEFAULT_RING_TIMEOUT_MS = 30_000
"""How long a call rings before `no_answer` (§80.3.2: a `no_answer` persona, an unanswered
INBOUND call)."""

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)
_SYSTEM = ActorRef(actor_type=ActorType.SYSTEM)
_LIVE_112_PHASES = frozenset({CallPhase.RINGING, CallPhase.CONNECTED})
_CALL_HOLDING_STATES = frozenset({DDSStageState.RECEIVED, DDSStageState.ACKNOWLEDGED})
"""The DDS stage states a ДДС call may stay live in — the ones `call_claimant` is offered in."""


@dataclass(frozen=True)
class CallSignal:
    """One Redis signal owed after a commit: `voice:join` or `voice:cancel` for one ДДС call.

    `sip_user` is the line owner's `users.username` for a `SIP`-endpoint call (I3 E6e): the SIP
    gateway rings that user's softphone on `voice:join`."""

    call: DdsCall
    cancel_reason: str | None = None
    at_offset_ms: int = 0
    sip_user: str | None = None


def join_extra(call: DdsCall, sip_user: str | None = None) -> Mapping[str, str | None]:
    """`voice:join`'s additive keys for a ДДС call (HLD 80 §80.3.6; `direction` since I3 E6c, so
    the head of an INBOUND call knows it is the one reporting; `sip_user` for a `SIP`-endpoint
    call since I3 E6e — absent otherwise, so a browser call's payload is unchanged)."""
    extra: dict[str, str | None] = {
        "call_kind": call.kind.value,
        "assignment_id": None if call.assignment_id is None else str(call.assignment_id).lower(),
        "persona_id": call.persona_id,
        "endpoint": call.endpoint.value,
        "direction": call.direction.value,
    }
    if call.endpoint is CallEndpoint.SIP and sip_user is not None:
        extra["sip_user"] = sip_user
    return extra


def awaits_gateway_leg(call: DdsCall) -> bool:
    """An OUTBOUND `SIP` call that only the gateway's `leg UP` may ring (I3 E6e, §80.3.2)."""
    return call.endpoint is CallEndpoint.SIP and call.direction is DdsCallDirection.OUTBOUND


async def line_owner_username(uow: UnitOfWork, call: DdsCall) -> str | None:
    """The `users.username` of the trainee on a `SIP` call's line (the gateway's `sip_user`);
    `None` for a browser call, whose `voice:join` carries no `sip_user`."""
    if call.endpoint is not CallEndpoint.SIP or call.actor_user_id is None:
        return None
    user = await uow.users.get(call.actor_user_id)
    return None if user is None else user.username


def call_persona(
    reference: ReferencePort | None, log: Sequence[SessionEvent], call: DdsCall
) -> Persona | None:
    """The persona recorded on the call (`DDS_CALL_STARTED.persona_id`, P4), read from the session's
    recorded pack; `None` for a claimant call or a pack without it."""
    if call.persona_id is None:
        return None
    personas = reference_catalog(reference).personas(session_pack_id(log))
    return None if personas is None else personas.get(call.persona_id)


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
    persona: Persona | None = None,
    leg_up: bool = False,
) -> tuple[DdsCall, list[DomainEvent]]:
    """`ring` a `DIALING` call when the transport is up, then — for a claimant whose 112 call is
    live, or a persona marked `busy` (I3 E6c) — `busy`. Returns the call as it now stands and the
    events to append (none for `ring`).

    An OUTBOUND `SIP` call also needs the gateway's `leg UP` (`leg_up`, I3 E6e): only
    `reportSipLeg` passes it.

    Persists the moved call through `uow.dds_calls`; the caller appends the events.
    """
    if call.state is not DdsCallState.DIALING or not transport_ready:
        return call, []
    if awaits_gateway_leg(call) and not leg_up:
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
    busy = rung.kind is DdsCallKind.CLAIMANT and claimant_busy(log)
    if busy or (persona is not None and persona.busy):
        rung, ended = fire_call_trigger(rung, "busy", actor=_SIMULATION, now_ms=now_ms)
        assert ended is not None
        events.append(ended)
    await uow.dds_calls.save(rung)
    return rung, events


async def end_live_calls(
    uow: UnitOfWork,
    session_id: SessionId,
    now_ms: int,
    *,
    reason: DdsCallEndReason = DdsCallEndReason.ABORT,
) -> tuple[list[DomainEvent], list[CallSignal]]:
    """SYSTEM's `hang_up` of every live ДДС call of the session (§80.3.2 "session abort, stage
    completion"). Saves the ended calls; returns their `DDS_CALL_ENDED` events, for the caller to
    append in its own Unit of Work, and the `voice:cancel` signals owed after its commit."""
    events: list[DomainEvent] = []
    signals: list[CallSignal] = []
    for call in await uow.dds_calls.list_live(session_id):
        ended, event = fire_call_trigger(
            call, "hang_up", actor=_SYSTEM, now_ms=now_ms, end_reason=reason
        )
        await uow.dds_calls.save(ended)
        assert event is not None
        events.append(event)
        signals.append(CallSignal(ended, cancel_reason=reason.value, at_offset_ms=now_ms))
    return events, signals


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
                extra=join_extra(signal.call, signal.sip_user),
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
        ring_timeout_ms: int = DEFAULT_RING_TIMEOUT_MS,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._call_transport = call_transport
        self._voice_signals = voice_signals
        self._answer_after_ms = answer_after_ms
        self._join_retry_ms = join_retry_ms
        self._ring_timeout_ms = ring_timeout_ms
        self._reference = reference
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
                    signals.append(
                        CallSignal(moved, sip_user=await line_owner_username(uow, moved))
                    )
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
        """Ring a `DIALING` call, let the AI callee answer a `RINGING` OUTBOUND one, or give up on
        a call that rang out (a `no_answer` persona, an INBOUND call nobody answered)."""
        persona = call_persona(self._reference, log, call)
        if call.state is DdsCallState.DIALING:
            return await ring_now(
                uow,
                call,
                now_ms=now_ms,
                transport_ready=transport_ready,
                log=log,
                persona=persona,
            )
        if call.state is not DdsCallState.RINGING:
            return call, []
        rings_out = call.direction is DdsCallDirection.INBOUND or (
            persona is not None and persona.no_answer
        )
        if rings_out:
            if now_ms < call.started_at_offset_ms + self._ring_timeout_ms:
                return call, []
            ended, event = fire_call_trigger(call, "no_answer", actor=_SIMULATION, now_ms=now_ms)
            await uow.dds_calls.save(ended)
            return ended, [] if event is None else [event]
        answer_after_ms = self._answer_after_ms if persona is None else persona.answer_after_ms
        if now_ms >= call.started_at_offset_ms + answer_after_ms:
            if call.kind is DdsCallKind.CLAIMANT and claimant_busy(log):
                ended, event = fire_call_trigger(call, "busy", actor=_SIMULATION, now_ms=now_ms)
                await uow.dds_calls.save(ended)
                return ended, [] if event is None else [event]
            answered, event = fire_call_trigger(call, "answer", actor=_SIMULATION, now_ms=now_ms)
            await uow.dds_calls.save(answered)
            return answered, [] if event is None else [event]
        return call, []

    def _join_due(self, call: DdsCall, log: Sequence[SessionEvent]) -> bool:
        """§40.6's per-call retry: live, no agent yet, `join_retry_ms` since the last publish —
        and (I3 E6e) a browser-button `SIP` call still `DIALING`, whose `voice:join` is what tells
        the gateway to ring the softphone; the gateway's `leg UP` (the `ring`) ends that retry."""
        if self._voice_signals is None:
            return False
        waiting_for_gateway = (
            call.state is DdsCallState.DIALING
            and awaits_gateway_leg(call)
            and call.selection_reason is CallSelectionReason.BROWSER_BUTTON
        )
        if not waiting_for_gateway and call.state not in (
            DdsCallState.RINGING,
            DdsCallState.CONNECTED,
        ):
            return False
        last = self._last_join_ms.get(call.call_id)
        if last is not None and self._clock.monotonic_ms() - last < self._join_retry_ms:
            return False
        return waiting_for_gateway or not agent_joined_call(log, call.call_id)


def _stage_holds_calls(session: SimulationSession) -> bool:
    """The session's active stage is its DDS stage in a state a ДДС call may stay live in."""
    stage = session.current_stage
    if stage is None or stage.role_type is not RoleType.DDS:
        return False
    return stage.state in _CALL_HOLDING_STATES
