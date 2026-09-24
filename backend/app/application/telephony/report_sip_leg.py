"""`reportSipLeg` — the SIP gateway reports its softphone leg of a `SIP`-endpoint call (I3 E6e, HLD
`80-telephony.md` §80.2.3 steps 2–5, §80.3.2, `openapi.yaml`).

Three states, each one §80.3.2 trigger (or none):

* `UP` — the gateway is in the call's room with the softphone connected.
  - An OUTBOUND call still `DIALING` is `ring`ed (SIMULATION): `guard_dds_call_transport_ready`
    now has the gateway's leg as well as the transport (LiveKit ∧ agent heartbeat). `voice:join`
    follows the commit, so the agent joins, and the AI callee answers `answer_after_ms` later on
    the tick (`AdvanceDdsCalls`); the gateway sends the softphone its `200 OK` on
    `DDS_CALL_ANSWERED`. A transport not ready yet leaves the call `DIALING`: the gateway re-reports
    `UP` until it rings.
  - An INBOUND call `RINGING` (a brigade's `CALL_IN`, rung on the softphone) is `answer`ed by the
    TRAINEE on the line — picking up the softphone is the trainee's `answer` (§80.2.3 step 5).
  - Anything else (already rung / connected) is a no-op: `UP` is idempotent.
* `FAILED` — the softphone did not answer a click-to-call (or an inbound ring) within 30 s, or
  rejected it: `hang_up` by SYSTEM, `end_reason ABORT`.
* `DOWN` — `BYE` or `CANCEL` from the softphone: `hang_up` by the TRAINEE on the line, `end_reason
  HANGUP`.

A report on an `ENDED` call is accepted and ignored (`200`), so a late `BYE` never fails; so is one
on a session that is no longer `ACTIVE` (its calls were ended by `closeDdsIncident` /
`abortSession`). A `BROWSER` call has no gateway leg: `409 INVALID_TRANSITION`. After the commit:
`voice:join` for a call that was just rung, `voice:cancel {call_id, reason}` for one just ended (the
agent leaves the room).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.application.dds.dds_call_flow import (
    CallSignal,
    call_persona,
    line_owner_username,
    publish_signals,
    ring_now,
)
from app.application.dds.dds_call_views import (
    DdsCallNotFoundError,
    DdsCallView,
    dds_call_view,
    persona_title_of,
    session_personas,
)
from app.application.ports.call_transport_status import CallTransportStatus
from app.application.ports.clock import Clock
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.voice_signal_publisher import VoiceSignalPublisher
from app.application.simulation.sim_time import running_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import SessionId
from app.domain.dds.call import (
    CallEndpoint,
    DdsCall,
    DdsCallDirection,
    DdsCallEndReason,
    DdsCallState,
    fire_call_trigger,
)
from app.domain.enums import ActorType, SessionState
from app.domain.events.session_event import DomainEvent, SessionEvent

__all__ = ["ReportSipLeg", "SipLegReportResult", "SipLegState"]

_SYSTEM = ActorRef(actor_type=ActorType.SYSTEM)


class SipLegState(str, Enum):
    """`openapi.yaml`'s `SipLegReport.state`."""

    UP = "UP"
    FAILED = "FAILED"
    DOWN = "DOWN"


@dataclass(frozen=True)
class SipLegReportResult:
    """The call after the report, and the session it belongs to (for the router's tick)."""

    view: DdsCallView
    session_id: SessionId


class ReportSipLeg:
    """`reportSipLeg` (`openapi.yaml`)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        call_transport: CallTransportStatus,
        voice_signals: VoiceSignalPublisher | None = None,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._call_transport = call_transport
        self._voice_signals = voice_signals
        self._reference = reference

    async def __call__(
        self, call_id: UUID, state: SipLegState, sip_status: int | None = None
    ) -> SipLegReportResult:
        del sip_status  # recorded by the gateway's log only; the event carries `ABORT`
        signals: list[CallSignal] = []
        async with self._unit_of_work() as uow:
            found = await uow.dds_calls.get_by_id(call_id)
            if found is None:
                raise DdsCallNotFoundError(call_id)
            session_id = found.session_id
            session = await uow.sessions.get_for_update(session_id)
            if session is None:  # pragma: no cover - the FK cascades the call away with it
                raise DdsCallNotFoundError(call_id)
            # Re-read under the session's row lock: a concurrent hang-up may have ended it.
            call = await uow.dds_calls.get(session_id, call_id) or found
            if call.endpoint is not CallEndpoint.SIP:
                raise InvalidTransitionError(
                    "DDS_CALL_TRANSITIONS",
                    call.state.value,
                    f"leg {state.value}",
                    f"a {call.endpoint.value} call has no SIP leg",
                )
            log = list(await uow.events.read(session_id))
            if call.live and session.state is SessionState.ACTIVE:
                now_ms = running_ms(session, self._clock.now())
                moved, events = await self._apply(uow, call, state, now_ms, log)
                if events:
                    log.extend(await uow.events.append(session_id, events))
                if moved.state is DdsCallState.RINGING and call.state is DdsCallState.DIALING:
                    signals.append(
                        CallSignal(moved, sip_user=await line_owner_username(uow, moved))
                    )
                elif not moved.live and call.live:
                    signals.append(
                        CallSignal(
                            moved,
                            cancel_reason=(moved.end_reason or DdsCallEndReason.ABORT).value,
                            at_offset_ms=now_ms,
                        )
                    )
                call = moved
            personas = session_personas(self._reference, log)
            await uow.commit()
        await publish_signals(self._voice_signals, session_id, signals)
        return SipLegReportResult(
            dds_call_view(call, None, persona_title_ru=persona_title_of(call, personas)),
            session_id,
        )

    async def _apply(
        self,
        uow: UnitOfWork,
        call: DdsCall,
        state: SipLegState,
        now_ms: int,
        log: Sequence[SessionEvent],
    ) -> tuple[DdsCall, list[DomainEvent]]:
        """The trigger this report fires on a live call, and its events (see the docstring)."""
        if state is SipLegState.UP:
            if call.direction is DdsCallDirection.OUTBOUND:
                return await ring_now(
                    uow,
                    call,
                    now_ms=now_ms,
                    transport_ready=await self._call_transport.transport_ready(call.session_id),
                    log=log,
                    persona=call_persona(self._reference, log, call),
                    leg_up=True,
                )
            if call.state is not DdsCallState.RINGING:
                return call, []
            actor = ActorRef(actor_type=ActorType.TRAINEE, actor_id=call.actor_user_id)
            answered, event = fire_call_trigger(call, "answer", actor=actor, now_ms=now_ms)
        elif state is SipLegState.FAILED:
            answered, event = fire_call_trigger(
                call, "hang_up", actor=_SYSTEM, now_ms=now_ms, end_reason=DdsCallEndReason.ABORT
            )
        else:
            actor = ActorRef(actor_type=ActorType.TRAINEE, actor_id=call.actor_user_id)
            answered, event = fire_call_trigger(call, "hang_up", actor=actor, now_ms=now_ms)
        await uow.dds_calls.save(answered)
        return answered, [] if event is None else [event]
