"""`createVoiceToken` — one room-scoped LiveKit token for one participant (D9, `openapi.yaml`).

`openapi.yaml`: "The backend is the only minter of LiveKit tokens (D9): the frontend never holds
the LiveKit API secret. The token grants join on exactly the room of this session's active call and
nothing else. Issued only while the session is `ACTIVE` and the caller is the participant assigned
to an `OPERATOR_112` stage."

The four refusals are `openapi.yaml`'s, in the order they are decided, and each is the code that
contract already documents for its status:

* no such session — `404 NOT_FOUND`;
* the session is not `ACTIVE` — `409 SESSION_NOT_ACTIVE`;
* the caller holds no participant row — `403 PARTICIPANT_NOT_ASSIGNED`;
* the caller is not the participant of the *active* `OPERATOR_112` stage — `403 FORBIDDEN_FOR_ROLE`;
* there is no call to join — `409 ACTION_NOT_AVAILABLE`.

"No call to join" is the `CallStateView` of `app.application.operator.views.project_call_state`
being in a phase other than `RINGING` or `CONNECTED`, read from the session's event log, which is
the audit source (SPEC §8). A token minted before `CALL_RINGING` would name a room the event log
has not yet chosen, and a token minted after `CALL_ENDED` would let a trainee re-enter a finished
call.

**Not a command.** `x-action` is `'-'` and `x-emits` is `[]`: this appends nothing, changes nothing
and therefore does not go through `OperatorCommandGate` (whose second gate asks the `RoleModule`
for an action id that does not exist here). It opens one read transaction for the aggregate and the
log, and mints outside it — signing a JWT is CPU work that has no business holding a transaction.

The minted token is never logged (SPEC §41).
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import (
    ActionNotAvailableError,
    SessionNotActiveError,
)
from app.application.operator.views import CallPhase, project_call_state
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.voice_token_service import MintedVoiceToken, VoiceTokenService
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import SessionId
from app.domain.enums import Operator112StageState, RoleType, SessionState

__all__ = ["ACTION_ID", "JOINABLE_PHASES", "CreateVoiceToken"]

ACTION_ID = "create_voice_token"
"""Not an `x-action` (`openapi.yaml` says `'-'`); the name the `409` problem detail reports."""

JOINABLE_PHASES: frozenset[CallPhase] = frozenset({CallPhase.RINGING, CallPhase.CONNECTED})
"""The two phases in which a room exists and is still live."""


class CreateVoiceToken:
    """`createVoiceToken` (`openapi.yaml`)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, tokens: VoiceTokenService) -> None:
        self._unit_of_work = unit_of_work
        self._tokens = tokens

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> MintedVoiceToken:
        """Check the five conditions of the module docstring, then mint."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if session.state is not SessionState.ACTIVE:
                raise SessionNotActiveError(session_id, session.state)

            participant = resolve_participant(session, user)
            stage = session.current_stage
            if (
                stage is None
                or stage.role_type is not RoleType.OPERATOR_112
                or stage.participant_user_id != participant.user_id
            ):
                raise ForbiddenForRoleError(
                    f"the caller is not the OPERATOR_112 participant of the active stage of "
                    f"session {session_id}"
                )
            stage_state = stage.state
            assert isinstance(stage_state, Operator112StageState)

            call = project_call_state(await uow.events.read(session_id))
            await uow.commit()

        if call.phase not in JOINABLE_PHASES or call.room_name is None:
            raise ActionNotAvailableError(ACTION_ID, stage_state)

        # `identity` is the account id, not the username: it is what `CALL_ANSWERED`'s
        # `answered_by_user_id` records, so a LiveKit participant maps onto the event log with no
        # second naming scheme (SPEC §8).
        return self._tokens.mint(room_name=call.room_name, participant_identity=str(user.user_id))
