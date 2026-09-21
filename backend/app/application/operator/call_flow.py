"""`advance_call_flow` — the two stage triggers the SIMULATION fires, not the trainee (§10.8, D7).

Two rows of `OPERATOR_112_TRANSITIONS` have `allowed_actors = {SIMULATION}`:

* `WAITING_FOR_CALL --ring--> RINGING`, guard `guard_session_active_and_transport_ready` — the
  call starts when the caller is present on the transport, not when a trainee presses a button;
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

TODO(E11): `CALL_RINGING.room_name` and `caller_display_ru` are placeholders until the LiveKit
transport of D9 exists — a room this backend opened would have a name that transport chose, and a
caller display name comes from the scenario's caller profile. `call_id` is a real, fresh id: it
is what every later call event correlates on, so it must be allocated here whatever the transport
turns out to be.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.application.ports.call_transport_status import CallTransportStatus
from app.application.ports.clock import Clock
from app.application.ports.id_generator import IdGenerator
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.sessions.guard_context import build_guard_runtime
from app.application.timebase import session_offset_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import RoleStageId, SessionId
from app.domain.common.state_machine import GuardRuntime
from app.domain.enums import ActorType, Operator112StageState, RoleType, SessionState
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.session.session import SimulationSession

__all__ = ["CALLER_DISPLAY_RU", "AdvanceCallFlow", "room_name_for"]

logger = logging.getLogger(__name__)

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)
"""Both triggers are `SIMULATION`-fired (§10.8); no user id is involved."""

CALLER_DISPLAY_RU = "Неизвестный абонент"
"""What the phone widget shows until the caller profile supplies a name — TODO(E11)."""


def room_name_for(session_id: SessionId) -> str:
    """The call's room name (§40.6 placeholder rules: canonical lowercase UUID, no braces).

    TODO(E11): the LiveKit transport names the room it opens; this is the local stand-in that
    keeps `CALL_RINGING.room_name` a real, session-unique string rather than an empty one.
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
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._call_transport = call_transport
        self._ids = ids

    async def __call__(self, session_id: SessionId) -> bool:
        """One transaction; `True` when a trigger fired. Never raises for an ineligible session."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None or session.state is not SessionState.ACTIVE:
                return False
            stage = session.current_stage
            if stage is None or stage.role_type is not RoleType.OPERATOR_112:
                return False

            log = await uow.events.read(session_id)
            now_ms = session_offset_ms(self._clock.now(), session.started_at)
            transport_ready = await self._call_transport.caller_joined(session_id)
            runtime = build_guard_runtime(
                log,
                scenario_valid=True,
                inference_ready=True,
                transport_ready=transport_ready,
            )

            if stage.state is Operator112StageState.WAITING_FOR_CALL:
                if not transport_ready:
                    return False
                fired = await self._ring(uow, session, stage.role_stage_id, now_ms, runtime)
            elif stage.state is Operator112StageState.CONNECTED:
                if not runtime.first_finalized_turn:
                    return False
                fired = await self._begin_interview(
                    uow, session, stage.role_stage_id, now_ms, runtime
                )
            else:
                return False

            if not fired:
                return False
            await uow.commit()
            return True

    # -- the two triggers ------------------------------------------------------------------------

    async def _ring(
        self,
        uow: UnitOfWork,
        session: SimulationSession,
        stage_id: RoleStageId,
        now_ms: int,
        runtime: GuardRuntime,
    ) -> bool:
        """`WAITING_FOR_CALL --ring--> RINGING`, then `CALL_RINGING` and `STAGE_STATE_CHANGED`."""
        try:
            updated, stage_events = session.fire_stage_trigger(
                stage_id, "ring", actor=_SIMULATION, now_ms=now_ms, runtime=runtime
            )
        except InvalidTransitionError:
            # The guard read the world differently from the check above (a concurrent command
            # moved the stage). Losing the trigger costs one tick, never correctness.
            logger.debug("session %s: `ring` was refused by its guard", session.id)
            return False
        await uow.sessions.save(updated)
        ringing = DomainEvent(
            event_type=EventType.CALL_RINGING,
            actor=_SIMULATION,
            monotonic_offset_ms=now_ms,
            payload={
                "call_id": UUID(str(self._ids.new())),
                "room_name": room_name_for(session.id),
                "caller_display_ru": CALLER_DISPLAY_RU,
                "at_offset_ms": now_ms,
            },
        )
        await uow.events.append(session.id, [ringing, *stage_events])
        return True

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
