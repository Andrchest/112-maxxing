"""`hangUpDdsCall` — the ДДС trainee puts the receiver down (I3 E6b, HLD `80-telephony.md` §80.3.2,
`openapi.yaml`).

Fires `hang_up` (TRAINEE ⇒ `end_reason HANGUP`) from `DIALING`, `RINGING` or `CONNECTED` and appends
`DDS_CALL_ENDED`; an `ENDED` call is the machine's `409 INVALID_TRANSITION`. After the commit,
`voice:cancel:{session_id} {call_id, reason: HANGUP}` tells the voice agent to leave that call's
room — the agent's other pipelines (the 112 call's) read the same channel and ignore a `call_id`
that is not theirs.

**The gate.** `hang_up` is an action of the call (`DdsCallView.available_actions`), not of the
stage, so this is not `DdsCommandGate`'s stage-action check — the pipeline order is kept all the
same: the session row lock first (`get_for_update`), `ACTIVE` (`409 SESSION_NOT_ACTIVE`), a
participant (`403 PARTICIPANT_NOT_ASSIGNED`), a `TRAINEE` account playing the ДДС (`403
FORBIDDEN_FOR_ROLE`), a call of this session (`404`), and the line is the caller's own — another
trainee's call is not theirs to end (`403 FORBIDDEN_FOR_ROLE`).
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.dds_call_flow import CallSignal, publish_signals
from app.application.dds.dds_call_views import DdsCallNotFoundError, DdsCallView, dds_call_view
from app.application.operator.command_context import SessionNotActiveError
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.user_repository import UserRole
from app.application.ports.voice_signal_publisher import VoiceSignalPublisher
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.application.simulation.sim_time import running_ms
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.dds.call import DdsCallEndReason, fire_call_trigger
from app.domain.enums import ActorType, SessionState

_SYSTEM = ActorRef(actor_type=ActorType.SYSTEM)

__all__ = ["ACTION_ID", "EndDdsCallBySystem", "HangUpDdsCall"]

ACTION_ID = "hang_up"
"""`openapi.yaml`'s `x-action` for `hangUpDdsCall`."""

_CANCEL_REASON = "HANGUP"
"""§40.6's `voice:cancel` reason for a trainee's hang-up."""


class HangUpDdsCall:
    """`hangUpDdsCall` (`openapi.yaml`)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        voice_signals: VoiceSignalPublisher | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._voice_signals = voice_signals

    async def __call__(
        self, session_id: SessionId, call_id: UUID, user: AuthenticatedUser
    ) -> DdsCallView:
        """End the caller's call; publish `voice:cancel` after the commit."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if session.state is not SessionState.ACTIVE:
                raise SessionNotActiveError(session_id, session.state)
            participant = resolve_participant(session, user)
            if user.user_role is not UserRole.TRAINEE or not session.plays_dds(participant.user_id):
                raise ForbiddenForRoleError(
                    f"only a ДДС trainee of session {session_id} may hang up a ДДС call"
                )
            call = await uow.dds_calls.get(session_id, call_id)
            if call is None:
                raise DdsCallNotFoundError(call_id)
            if call.actor_user_id != user.user_id:
                raise ForbiddenForRoleError(f"ДДС call {call_id} is another trainee's line")
            now_ms = running_ms(session, self._clock.now())
            ended, event = fire_call_trigger(
                call,
                ACTION_ID,
                actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=user.user_id),
                now_ms=now_ms,
            )
            await uow.dds_calls.save(ended)
            assert event is not None
            await uow.events.append(session_id, [event])
            await uow.commit()
        await publish_signals(
            self._voice_signals,
            session_id,
            [CallSignal(ended, cancel_reason=_CANCEL_REASON, at_offset_ms=now_ms)],
        )
        return dds_call_view(ended, user)


class EndDdsCallBySystem:
    """SYSTEM's `hang_up` of one ДДС call — `TRANSPORT_LOST` from the voice agent (§80.3.2).

    The voice agent's pipeline ends a call whose media plane stayed away longer than
    `reconnect_grace_s` (SPEC §39 item 5); for the 112 call that is the pipeline's own
    `CALL_ENDED`, for a ДДС call it is this `DDS_CALL_ENDED {reason: TRANSPORT_LOST}` — the same
    Unit of Work discipline, appended through the one event store (D9). Idempotent: a call already
    `ENDED` (the trainee hung up first) is left alone and `False` is returned.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self,
        session_id: SessionId,
        call_id: UUID,
        reason: DdsCallEndReason = DdsCallEndReason.TRANSPORT_LOST,
    ) -> bool:
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                return False
            call = await uow.dds_calls.get(session_id, call_id)
            if call is None or not call.live:
                return False
            ended, event = fire_call_trigger(
                call,
                ACTION_ID,
                actor=_SYSTEM,
                now_ms=running_ms(session, self._clock.now()),
                end_reason=reason,
            )
            await uow.dds_calls.save(ended)
            assert event is not None
            await uow.events.append(session_id, [event])
            await uow.commit()
        return True
