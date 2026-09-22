"""`advance_call_flow` — the two stage triggers the SIMULATION fires, not the trainee (§10.8, D7).

Two rows of `OPERATOR_112_TRANSITIONS` have `allowed_actors = {SIMULATION}`:

* `WAITING_FOR_CALL --ring--> RINGING`, guard `guard_session_active_and_transport_ready` — the
  call starts when the media plane can carry it, not when a trainee presses a button;
* `CONNECTED --begin_interview--> INTERVIEW`, guard `guard_first_finalized_turn` — the interview
  begins when the first `ASR_FINAL` lands, i.e. when the caller has actually said something.

Neither is an endpoint, and neither may be: a trainee who could fire `ring` would be starting
their own call. They are driven by the simulation loop instead — `SimulationRunner` runs this as
an `after_tick` hook (D7: "ticks every `SIM_TICK_MS` and immediately after each command"), which
is why `app.application.simulation.runner` must not import this module. The hook is injected by
the composition root; `backend/tests/unit/application/simulation/` asserts the runner's import
list stays free of `app.application.operator`.

**This module never answers the call, never edits the card and never ends the call.** Those are
trainee actions and SPEC §7 says the simulation does not complete them. It fires two triggers and
appends the events they owe, in one Unit of Work transaction, and does nothing else.

**The trainee's phone widget shows a neutral caller line, never the persona's identity** — see
`CALLER_DISPLAY_RU` below for why (D3's layer separation, SPEC §21).

**The order of a call (D9, §40.6, E11).** `ring` is guarded on `transport_ready` — the LiveKit
server is reachable and the voice-agent heartbeat is present — and *then* `CALL_RINGING` names the
room. Only after that transaction has committed does the backend publish `voice:join`, which is
what brings the agent into the room; the trainee answers over REST and the frontend joins with a
token `createVoiceToken` mints. Publishing before the commit would be able to send an agent into a
room whose `CALL_RINGING` a rollback then erased, so the signal is published by the caller of the
Unit of Work, never inside it.

§40.6 also makes `voice:join` self-healing: "Loss ⇒ the agent never joins; the backend
re-publishes every `VOICE_JOIN_RETRY_MS` (default 2000) until the agent has joined." That retry is
this same `after_tick` hook: every tick on which the call is still live, no agent has joined it and
`VOICE_JOIN_RETRY_MS` has elapsed since the last publish re-sends the same payload.

**What stops the retry is the agent, not the trainee (R2, E19-E3 finding E20-1).** Until E20 the
retry ran only while the *stage* was `RINGING`, so the answer stopped it: a trainee (or a script)
that answered within a tick silenced the only self-healing signal the session ever emits, and a
voice agent that was still starting, reconnecting or re-adopting that session never heard about the
room again. The call sat `CONNECTED` with nobody in the room and no error anywhere — E19's
benchmark had to sleep 15 s before answering to work around it. The retry now runs while the call
phase is `RINGING` **or** `CONNECTED` and stops on the first event the agent itself appended for
that call (`_agent_joined` below), or when the call reaches `ENDED`. Re-publishing at a joined
agent costs nothing: `VoiceAgent._on_join` returns early for a session it already serves, which is
the same idempotence the RINGING retry always relied on.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.application.operator.views import (
    CallPhase,
    CallStateView,
    project_call_state,
    write_call_state_cache,
)
from app.application.ports.call_state_cache import CallStateCache
from app.application.ports.call_transport_status import CallTransportStatus
from app.application.ports.clock import Clock
from app.application.ports.id_generator import IdGenerator
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.voice_signal_publisher import VoiceSignalPublisher
from app.application.sessions.guard_context import build_guard_runtime
from app.application.simulation.sim_time import running_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import RoleStageId, SessionId
from app.domain.common.state_machine import GuardRuntime
from app.domain.enums import ActorType, Operator112StageState, RoleType, SessionState
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.session.session import SimulationSession

__all__ = ["CALLER_DISPLAY_RU", "AdvanceCallFlow", "room_name_for"]

logger = logging.getLogger(__name__)

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)
"""Both triggers are `SIMULATION`-fired (§10.8); no user id is involved."""

CALLER_DISPLAY_RU = "Входящий вызов 112"
"""What the trainee's phone widget shows for an incoming call — a neutral constant, by ruling.

It is deliberately **not** `CallerProfile.identity_ru`. In the demo scenario that string is
"Соседка Ирина Петровна из квартиры 41": the caller's name and her flat number are facts the
trainee is scored on *obtaining by asking* (`caller.full_name` and `address.apartment` are catalog
facts with disclosure policies), so printing them on the widget the moment the phone rings would
hand the trainee two answers before the call starts and would merge the Caller Knowledge layer
into the Operator view — which D3 separates and `openapi.yaml`'s own `CallStateView` description
rules out in as many words ("nothing about the caller's hidden knowledge appears here").

`ScenarioVersionSummary.caller_display_ru` is a *different* field on a *different*, instructor-
facing schema (the scenario catalogue), and it does stay `CallerProfile.identity_ru`
(`app.application.scenarios.queries`). Same property name, two audiences.

A real 112 console shows the incoming line, not a name it could not know yet; this constant is the
simulator's stand-in for that. Because it is a constant, nothing here reads the scenario at all —
there is no lookup that could leak.
"""


_LIVE_CALL_PHASES = frozenset({CallPhase.RINGING, CallPhase.CONNECTED})
"""The phases in which an agent still has something to join (R2). `ENDED` needs nobody."""

_BACKEND_CALL_EVENTS = frozenset(
    {EventType.CALL_RINGING, EventType.CALL_ANSWERED, EventType.CALL_ENDED}
)
"""The three `call_id`-carrying events the BACKEND appends; everything else is the agent's.

`CALL_RINGING` is this module's, `CALL_ANSWERED` is `answer_call`'s and `CALL_ENDED` is
`end_call`'s (the agent writes one too, but only to say the call is over, which already stops the
retry through the phase). Every other event that names a `call_id` —
`USER_SPEECH_STARTED`/`_ENDED`, `ASR_PARTIAL`/`_FINAL`, `CALLER_TTS_STARTED`/`_ENDED`,
`CALLER_UTTERANCE_INTERRUPTED`, `DIALOGUE_INTERPRETED`, `FACTS_DELIVERED`, `MODEL_ERROR`,
`MODEL_FALLBACK_USED`, `TRANSPORT_DISCONNECTED`/`_RECONNECTED` — is written by the voice agent's
own `VoiceEventAppender`, over the D5 event store and never over REST (D9). So the presence of any
of them for a call is proof that an agent adopted it, and that is the only ack available: the agent
appends nothing at the moment it joins (`TransportEventType.CONNECTED` has no persisted domain
event), and adding a new `EventType` for one would change the §8 event catalogue — see this task's
report under "HLD gaps".
"""


def _agent_joined(log: Sequence[SessionEvent], call_id: UUID) -> bool:
    """True once the voice agent has appended anything of its own for this call (R2)."""
    wanted = str(call_id).lower()
    for event in log:
        if event.event_type in _BACKEND_CALL_EVENTS:
            continue
        raw = event.payload.get("call_id")
        if raw is not None and str(raw).lower() == wanted:
            return True
    return False


def room_name_for(session_id: SessionId) -> str:
    """The call's room name: `session-{session_id}` (§40.6 placeholder rules).

    One room per session, named from the session id in canonical lowercase form with no braces —
    the same substitution §40.6 mandates for `session:{session_id}:events`, so a room name can be
    read back to a session by eye and no second naming scheme exists. The backend chooses it
    because it is the backend that publishes `voice:join` and mints the join tokens; the transport
    is told the name, it does not invent one.
    """
    return f"session-{str(session_id).lower()}"


class AdvanceCallFlow:
    """Fire whichever of `ring` / `begin_interview` the session is now due, or nothing."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        call_transport: CallTransportStatus,
        ids: IdGenerator,
        voice_signals: VoiceSignalPublisher | None = None,
        call_state_cache: CallStateCache | None = None,
        *,
        join_retry_ms: int = 2000,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._call_transport = call_transport
        self._ids = ids
        self._voice_signals = voice_signals
        self._call_state_cache = call_state_cache
        self._join_retry_ms = join_retry_ms
        #: `session_id -> monotonic ms of the last `voice:join` publish`. In-process and
        #: deliberately so: it is a rate limiter for a self-healing signal, not state. Losing it
        #: (a restart, another instance) costs one extra publish, which the agent ignores.
        self._last_join_ms: dict[SessionId, int] = {}

    async def __call__(self, session_id: SessionId) -> bool:
        """One transaction; `True` when a trigger fired. Never raises for an ineligible session."""
        signal: _JoinSignal | None = None
        state: CallStateView | None = None
        fired = False
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None or session.state is not SessionState.ACTIVE:
                return False
            stage = session.current_stage
            if stage is None or stage.role_type is not RoleType.OPERATOR_112:
                return False

            log = await uow.events.read(session_id)
            now_ms = running_ms(session, self._clock.now())

            # §40.6's retry, evaluated for every stage state and not just `RINGING` (R2): what
            # ends it is the agent's own first event for the call, or the call ending — never the
            # trainee's answer. See this module's docstring.
            signal = self._retry_join(session_id, log)

            if stage.state is Operator112StageState.WAITING_FOR_CALL:
                transport_ready = await self._call_transport.transport_ready(session_id)
                if transport_ready:
                    runtime = build_guard_runtime(
                        log, scenario_valid=True, inference_ready=True, transport_ready=True
                    )
                    rung = await self._ring(uow, session, stage.role_stage_id, now_ms, log, runtime)
                    if rung is not None:
                        signal, state = rung.signal, rung.call_state
                        fired = True
            elif stage.state is Operator112StageState.CONNECTED:
                # `guard_first_finalized_turn` is answered by the log alone, so the cheap half is
                # checked first and the transport is read only on the tick that actually fires —
                # a probe is a network round trip and this hook runs every `SIM_TICK_MS`.
                if build_guard_runtime(
                    log, scenario_valid=True, inference_ready=True
                ).first_finalized_turn:
                    runtime = build_guard_runtime(
                        log,
                        scenario_valid=True,
                        inference_ready=True,
                        transport_ready=await self._call_transport.transport_ready(session_id),
                    )
                    fired = await self._begin_interview(
                        uow, session, stage.role_stage_id, now_ms, runtime
                    )

            if not fired and signal is None:
                return False
            if fired:
                await uow.commit()

        # After the commit, never inside it (see this module's docstring).
        if signal is not None:
            await self._publish_join(session_id, signal)
        if state is not None:
            await write_call_state_cache(
                self._call_state_cache, session_id, state, self._clock.now()
            )
        return fired

    # -- the two triggers ------------------------------------------------------------------------

    async def _ring(
        self,
        uow: UnitOfWork,
        session: SimulationSession,
        stage_id: RoleStageId,
        now_ms: int,
        log: Sequence[SessionEvent],
        runtime: GuardRuntime,
    ) -> _Rung | None:
        """`WAITING_FOR_CALL --ring--> RINGING`, then `CALL_RINGING` and `STAGE_STATE_CHANGED`."""
        try:
            updated, stage_events = session.fire_stage_trigger(
                stage_id, "ring", actor=_SIMULATION, now_ms=now_ms, runtime=runtime
            )
        except InvalidTransitionError:
            # The guard read the world differently from the check above (a concurrent command
            # moved the stage). Losing the trigger costs one tick, never correctness.
            logger.debug("session %s: `ring` was refused by its guard", session.id)
            return None
        await uow.sessions.save(updated)
        call_id = UUID(str(self._ids.new()))
        room_name = room_name_for(session.id)
        ringing = DomainEvent(
            event_type=EventType.CALL_RINGING,
            actor=_SIMULATION,
            monotonic_offset_ms=now_ms,
            payload={
                "call_id": call_id,
                "room_name": room_name,
                "caller_display_ru": CALLER_DISPLAY_RU,
                "at_offset_ms": now_ms,
            },
        )
        stored = await uow.events.append(session.id, [ringing, *stage_events])
        return _Rung(
            signal=_JoinSignal(room=room_name, call_id=call_id),
            call_state=project_call_state([*log, *stored]),
        )

    async def _begin_interview(
        self,
        uow: UnitOfWork,
        session: SimulationSession,
        stage_id: RoleStageId,
        now_ms: int,
        runtime: GuardRuntime,
    ) -> bool:
        """`CONNECTED --begin_interview--> INTERVIEW`; `emits` is `None` — only the state event."""
        try:
            updated, stage_events = session.fire_stage_trigger(
                stage_id, "begin_interview", actor=_SIMULATION, now_ms=now_ms, runtime=runtime
            )
        except InvalidTransitionError:
            logger.debug("session %s: `begin_interview` was refused by its guard", session.id)
            return False
        await uow.sessions.save(updated)
        await uow.events.append(session.id, stage_events)
        return True

    # -- §40.6's two side effects, both after the commit ------------------------------------------

    def _retry_join(self, session_id: SessionId, log: Sequence[SessionEvent]) -> _JoinSignal | None:
        """The `voice:join` re-publish of §40.6, at most once per `VOICE_JOIN_RETRY_MS`.

        The timer is checked before the fold because this runs on every tick of every session and
        the fold walks the whole log; the two state questions — is the call still live, and has the
        agent joined it — are only asked on a tick that could actually publish.
        """
        if self._voice_signals is None:
            return None
        last = self._last_join_ms.get(session_id)
        now = self._clock.monotonic_ms()
        if last is not None and now - last < self._join_retry_ms:
            return None
        call = project_call_state(log)
        if call.phase not in _LIVE_CALL_PHASES or call.call_id is None or call.room_name is None:
            return None
        if _agent_joined(log, call.call_id):
            return None
        return _JoinSignal(room=call.room_name, call_id=call.call_id)

    async def _publish_join(self, session_id: SessionId, signal: _JoinSignal) -> None:
        """Publish `voice:join` and remember when, so the retry timer starts from this publish."""
        if self._voice_signals is None:
            return
        await self._voice_signals.publish_join(session_id, room=signal.room, call_id=signal.call_id)
        self._last_join_ms[session_id] = self._clock.monotonic_ms()


@dataclass(frozen=True)
class _JoinSignal:
    """The `voice:join` payload of one call — `{room, call_id}` beside the session id (§40.6)."""

    room: str
    call_id: UUID


@dataclass(frozen=True)
class _Rung:
    """What one successful `ring` produced: the signal to publish and the state to cache."""

    signal: _JoinSignal
    call_state: CallStateView
