"""The lesson use cases' own refusals (HLD 70 §70.3; `i3-openapi-delta.yaml`)."""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.sessions.queries import ForbiddenForRoleError
from app.domain.common.errors import DomainError, InvalidTransitionError, ScenarioValidationError
from app.domain.common.ids import LessonId
from app.domain.enums import SessionState
from app.domain.lesson.lesson import Lesson, LessonState

__all__ = [
    "TERMINAL_SESSION_STATES",
    "LessonNotFoundError",
    "LessonPlanEntryRefusedError",
    "LessonReportNotReadyError",
    "NotALessonParticipantError",
    "require_creator_or_admin",
]


class LessonNotFoundError(DomainError):
    """No `lessons` row with the requested id (`404 NOT_FOUND`)."""

    code = "NOT_FOUND"

    def __init__(self, lesson_id: LessonId) -> None:
        self.lesson_id = lesson_id
        super().__init__(f"no lesson {lesson_id}")


class NotALessonParticipantError(DomainError):
    """A TRAINEE reading a lesson they do not take part in (`403 PARTICIPANT_NOT_ASSIGNED`)."""

    code = "PARTICIPANT_NOT_ASSIGNED"

    def __init__(self, lesson_id: LessonId) -> None:
        self.lesson_id = lesson_id
        super().__init__(f"the caller is not a participant of lesson {lesson_id}")


class LessonReportNotReadyError(DomainError):
    """The lesson has not ended, so it has no report yet (`409 REPORT_NOT_READY`)."""

    code = "REPORT_NOT_READY"

    def __init__(self, lesson_id: LessonId, state: LessonState) -> None:
        self.lesson_id = lesson_id
        super().__init__(f"lesson {lesson_id} is {state.value}; its report is not ready")


class LessonPlanEntryRefusedError(DomainError):
    """`createSession` refused one plan entry: the same refusal, with `detail` naming its position.

    `code` is the refusal's own `ProblemCode`, so `createLesson` answers exactly what
    `createSession` would have for that entry (`i3-openapi-delta.yaml` `createLesson`).
    """

    def __init__(self, position: int, cause: DomainError) -> None:
        self.position = position
        self.cause = cause
        self.code = _code_of(cause)
        super().__init__(f"scenario_plan position {position}: {cause}")


def _code_of(cause: DomainError) -> str:
    code = getattr(cause, "code", None)
    if isinstance(code, str):
        return code
    if isinstance(cause, InvalidTransitionError):
        return "INVALID_TRANSITION"
    if isinstance(cause, ScenarioValidationError):
        return "SCENARIO_INVALID"
    return "VALIDATION_ERROR"


def require_creator_or_admin(lesson: Lesson, user: AuthenticatedUser) -> None:
    """`startLesson` / `abortLesson`: the instructor who created the lesson, or an ADMIN (§70.3.2).

    An instructor who is not the creator is refused with `403 FORBIDDEN_FOR_ROLE`: the lesson's
    cards act as its creator (`ActorRef(INSTRUCTOR, created_by_user_id)`), and a second instructor
    starting or stopping them would act under somebody else's name.
    """
    if user.user_role is UserRole.ADMIN:
        return
    if user.user_role is UserRole.INSTRUCTOR and user.user_id == lesson.created_by_user_id:
        return
    raise ForbiddenForRoleError(
        f"lesson {lesson.lesson_id} may be started or aborted by its creator or an ADMIN only"
    )


TERMINAL_SESSION_STATES: frozenset[SessionState] = frozenset(
    {SessionState.COMPLETED, SessionState.ABORTED}
)
