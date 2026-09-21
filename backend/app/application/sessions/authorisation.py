"""Session-level authorisation — the first of D8's two gates (E7, D8, `openapi.yaml`).

D8: "Authorisation of every command is two-gated: the caller's participant record must be assigned
to the session's active `RoleStage`, **and** the stage's `RoleModule` must permit the action in the
current stage state. A failure of the first gate is `403 FORBIDDEN_FOR_ROLE`; of the second,
`409 ACTION_NOT_AVAILABLE`."

This module owns the *first* gate only, and owns it for every slice: E7-B's operator commands and
E7-C's snapshot and event page call the same two functions rather than each re-deriving who may
act. The second gate is the `RoleModule`'s and is fired where the command is fired.

`resolve_participant` answers "which `SessionParticipant` is this caller?" and raises
`ParticipantNotAssignedError` when there is none — `openapi.yaml`'s `PARTICIPANT_NOT_ASSIGNED`,
which the API renders as `403`, exactly as the `Forbidden` response describes.

`can_observe` is the weaker, read-side question: a participant may observe their own session, and
an `INSTRUCTOR` or `ADMIN` may observe any session (that is what `listSessions`' `scope=ALL` and
the instructor console are for). A `TRAINEE` who is neither participant nor creator may not see
that the session exists at all — the session list filters on this and `getSession` refuses on it.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId
from app.domain.session.session import SessionParticipant, SimulationSession

__all__ = ["ParticipantNotAssignedError", "can_observe", "resolve_participant"]


class ParticipantNotAssignedError(DomainError):
    """The caller holds no `session_participants` row for this session (`403`, D8)."""

    code = "PARTICIPANT_NOT_ASSIGNED"

    def __init__(self, session_id: SessionId) -> None:
        self.session_id = session_id
        super().__init__(f"the caller is not a participant of session {session_id}")


def resolve_participant(session: SimulationSession, user: AuthenticatedUser) -> SessionParticipant:
    """This caller's participant record; raises `ParticipantNotAssignedError` when there is none.

    Deliberately not weakened for `INSTRUCTOR`/`ADMIN`: an instructor observes a session without
    *playing* it, and a trainee command must be attributable to the participant who issued it
    (SPEC §8). A caller who needs the read-side question asks `can_observe`.
    """
    for participant in session.participants:
        if participant.user_id == user.user_id:
            return participant
    raise ParticipantNotAssignedError(session.id)


def can_observe(session: SimulationSession, user: AuthenticatedUser) -> bool:
    """May this caller see that this session exists (`listSessions`, `getSession`)?

    True for a participant, for the instructor who created it, and for any `INSTRUCTOR` or
    `ADMIN`. False for every other `TRAINEE` — `openapi.yaml`'s `scope=MINE` is "the sessions the
    caller participates in or created", and a trainee asking for `scope=ALL` is refused outright.
    """
    if user.is_instructor_or_admin:
        return True
    if session.created_by_user_id == user.user_id:
        return True
    return any(participant.user_id == user.user_id for participant in session.participants)
