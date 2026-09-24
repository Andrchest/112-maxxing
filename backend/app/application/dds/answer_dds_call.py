"""`answerDdsCall` — the ДДС trainee answers a brigade's INBOUND call (I3 E6c, HLD `80-telephony.md`
§80.3.2, §80.3.3, `openapi.yaml`).

A step of the trainee's own leg written `report: CALL_IN` rings the ДДС when it falls due (stage
automation starts an INBOUND `DdsCall` on the workstation that plays the leg). This command fires
`answer` (TRAINEE) on it: `RINGING --answer--> CONNECTED` and `DDS_CALL_ANSWERED {answered_by:
TRAINEE}`. An OUTBOUND call, or a call in any other state, is the machine's `409
INVALID_TRANSITION` (INV 8). The answer carries the room-scoped token for the browser endpoint, so
the widget joins the call's room at once.

**The gate** is `hangUpDdsCall`'s, because `answer` is an action of the call, not of the stage:
the session row lock first, `ACTIVE` (`409 SESSION_NOT_ACTIVE`), a participant (`403`), a
`TRAINEE` account playing the ДДС (`403 FORBIDDEN_FOR_ROLE`), a call of this session (`404`), and
the ringing line must be the caller's own (`403 FORBIDDEN_FOR_ROLE`).
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.dds_call_views import (
    DdsCallNotFoundError,
    dds_call_view,
    persona_title_of,
    session_personas,
)
from app.application.dds.start_dds_call import StartedDdsCall
from app.application.operator.command_context import SessionNotActiveError
from app.application.ports.clock import Clock
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.user_repository import UserRole
from app.application.ports.voice_token_service import VoiceTokenService
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.application.simulation.sim_time import running_ms
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.dds.call import CallEndpoint, fire_call_trigger
from app.domain.enums import ActorType, SessionState

__all__ = ["ACTION_ID", "AnswerDdsCall"]

ACTION_ID = "answer"
"""`openapi.yaml`'s `x-action` for `answerDdsCall`."""


class AnswerDdsCall:
    """`answerDdsCall` (`openapi.yaml`)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        tokens: VoiceTokenService,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._tokens = tokens
        self._reference = reference

    async def __call__(
        self, session_id: SessionId, call_id: UUID, user: AuthenticatedUser
    ) -> StartedDdsCall:
        """Answer the caller's ringing INBOUND call; the view and the room token."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if session.state is not SessionState.ACTIVE:
                raise SessionNotActiveError(session_id, session.state)
            participant = resolve_participant(session, user)
            if user.user_role is not UserRole.TRAINEE or not session.plays_dds(participant.user_id):
                raise ForbiddenForRoleError(
                    f"only a ДДС trainee of session {session_id} may answer a ДДС call"
                )
            call = await uow.dds_calls.get(session_id, call_id)
            if call is None:
                raise DdsCallNotFoundError(call_id)
            if call.actor_user_id != user.user_id:
                raise ForbiddenForRoleError(f"ДДС call {call_id} rings another trainee's line")
            answered, event = fire_call_trigger(
                call,
                ACTION_ID,
                actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=user.user_id),
                now_ms=running_ms(session, self._clock.now()),
            )
            await uow.dds_calls.save(answered)
            assert event is not None
            await uow.events.append(session_id, [event])
            personas = session_personas(self._reference, await uow.events.read(session_id))
            await uow.commit()
        voice = (
            self._tokens.mint(room_name=answered.room, participant_identity=str(user.user_id))
            if answered.endpoint is CallEndpoint.BROWSER
            else None
        )
        return StartedDdsCall(
            call=dds_call_view(
                answered, user, persona_title_ru=persona_title_of(answered, personas)
            ),
            voice=voice,
        )
