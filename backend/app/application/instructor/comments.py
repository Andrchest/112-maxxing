"""`listSessionComments` / `createSessionComment` / `listLessonComments` / `createLessonComment`
(I4 E32, HLD `71-i4-wave4.md` §71.9, ТЗ ¶236, ¶237, ¶267).

Instructor feedback on a result, append-only: an edit is a new row whose `replaces_comment_id`
points at the row it supersedes (`ResultCommentRepository` has no update method at all). No
instructor isolation (Q-E9b-4, D-g): any `INSTRUCTOR`/`ADMIN` may read or write any session's or
lesson's comments — the account-role gate (`AdminOrInstructorDep`) is the whole check on the write
side.

**Read-side gate.** A trainee sees comments exactly when they could open the report they are
attached to:

* a session comment — `app.application.reports.visibility.report_visibility`, the identical gate
  `getSessionReport` uses (a stranger to the session is `403 PARTICIPANT_NOT_ASSIGNED`, and a
  participant whose mode needs a release and has not had one is `403 REPORT_NOT_RELEASED`);
* a lesson comment — "the lesson equivalent" (openapi.yaml): a lesson participant is refused
  `403 REPORT_NOT_RELEASED` until `Lesson.report_released_at` is set (there is no per-card release
  a lesson comment could ride on the way a card's report can).

Neither read requires the session to be `COMPLETED` or scored: a comment is free-text feedback,
not a scored artefact, and an instructor may leave one on a session that is still running or that
ended early (D11 — comments carry no points and reach no score table).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.lessons.errors import (
    LessonNotFoundError,
    LessonReportNotReleasedError,
    NotALessonParticipantError,
)
from app.application.ports.audit_changes import NO_AUDIT_CHANGES, AuditChangeCollector
from app.application.ports.clock import Clock
from app.application.ports.id_generator import IdGenerator
from app.application.ports.result_comment_repository import (
    NewResultComment,
    ResultCommentRepository,
    StoredResultComment,
)
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.reports.visibility import report_visibility
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.errors import DomainError
from app.domain.common.ids import LessonId, SessionId
from app.domain.lesson.lesson import Lesson

__all__ = [
    "CommentNotFoundError",
    "CreateLessonComment",
    "CreateSessionComment",
    "ListLessonComments",
    "ListSessionComments",
    "NewCommentRequest",
]


class CommentNotFoundError(DomainError):
    """`replaces_comment_id` names no comment of this same session/lesson (`404 NOT_FOUND`)."""

    code = "NOT_FOUND"

    def __init__(self, comment_id: UUID) -> None:
        self.comment_id = comment_id
        super().__init__(f"no comment {comment_id} on this session/lesson to replace")


@dataclass(frozen=True, slots=True)
class NewCommentRequest:
    """`ResultCommentRequest` — the two writers share this shape."""

    text: str
    replaces_comment_id: UUID | None


async def _check_replaces(
    comments: ResultCommentRepository,
    replaces_comment_id: UUID,
    *,
    session_id: SessionId | None = None,
    lesson_id: LessonId | None = None,
) -> StoredResultComment:
    """Refuse an edit that does not point at a comment of this same session/lesson; the comment
    it replaces otherwise."""
    existing = await comments.get(replaces_comment_id)
    if existing is None:
        raise CommentNotFoundError(replaces_comment_id)
    if session_id is not None and existing.session_id != session_id:
        raise CommentNotFoundError(replaces_comment_id)
    if lesson_id is not None and existing.lesson_id != lesson_id:
        raise CommentNotFoundError(replaces_comment_id)
    return existing


def _record_comment(
    changes: AuditChangeCollector, replaced: StoredResultComment | None, stored: StoredResultComment
) -> None:
    """`comment.text` «было → стало» (I7 E43): an edit shows the text it replaces."""
    changes.record("comment", "text", replaced.text if replaced is not None else None, stored.text)


# ---------------------------------------------------------------------------------------------
# Session comments
# ---------------------------------------------------------------------------------------------


class ListSessionComments:
    """`listSessionComments`."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser
    ) -> list[StoredResultComment]:
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not user.is_instructor_or_admin:
                resolve_participant(session, user)
                released = await uow.sessions.get_report_release(session_id) is not None
                # Raises `ReportNotReleasedError` when this viewer's mode needs a release and has
                # not had one; the returned `ReportVisibility` itself is unused — comments are an
                # all-or-nothing read, never filtered per role the way report sections are (R3).
                report_visibility(session, user, released=released)
            comments = await uow.result_comments.list_for_session(session_id)
            await uow.commit()
        return comments


class CreateSessionComment:
    """`createSessionComment` (INSTRUCTOR / ADMIN — the router's `AdminOrInstructorDep` gate)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        *,
        changes: AuditChangeCollector = NO_AUDIT_CHANGES,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids
        self._changes = changes  # I7 E43

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, request: NewCommentRequest
    ) -> StoredResultComment:
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            replaced = (
                await _check_replaces(
                    uow.result_comments, request.replaces_comment_id, session_id=session_id
                )
                if request.replaces_comment_id is not None
                else None
            )
            comment_id = await uow.result_comments.add(
                NewResultComment(
                    id=self._ids.new(),
                    session_id=session_id,
                    lesson_id=None,
                    author_user_id=user.user_id,
                    text=request.text,
                    replaces_comment_id=request.replaces_comment_id,
                    created_at=self._clock.now(),
                )
            )
            stored = await uow.result_comments.get(comment_id)
            await uow.commit()
        assert stored is not None
        _record_comment(self._changes, replaced, stored)
        return stored


# ---------------------------------------------------------------------------------------------
# Lesson comments
# ---------------------------------------------------------------------------------------------


class ListLessonComments:
    """`listLessonComments` — "the lesson equivalent of listSessionComments"."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, lesson_id: LessonId, user: AuthenticatedUser
    ) -> list[StoredResultComment]:
        async with self._unit_of_work() as uow:
            lesson = await uow.lessons.get(lesson_id)
            if lesson is None:
                raise LessonNotFoundError(lesson_id)
            if not user.is_instructor_or_admin:
                _require_lesson_participant(lesson, user)
                if lesson.report_released_at is None:
                    raise LessonReportNotReleasedError(lesson_id)
            comments = await uow.result_comments.list_for_lesson(lesson_id)
            await uow.commit()
        return comments


class CreateLessonComment:
    """`createLessonComment` (INSTRUCTOR / ADMIN — the router's `AdminOrInstructorDep` gate)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        *,
        changes: AuditChangeCollector = NO_AUDIT_CHANGES,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids
        self._changes = changes  # I7 E43

    async def __call__(
        self, lesson_id: LessonId, user: AuthenticatedUser, request: NewCommentRequest
    ) -> StoredResultComment:
        async with self._unit_of_work() as uow:
            lesson = await uow.lessons.get(lesson_id)
            if lesson is None:
                raise LessonNotFoundError(lesson_id)
            replaced = (
                await _check_replaces(
                    uow.result_comments, request.replaces_comment_id, lesson_id=lesson_id
                )
                if request.replaces_comment_id is not None
                else None
            )
            comment_id = await uow.result_comments.add(
                NewResultComment(
                    id=self._ids.new(),
                    session_id=None,
                    lesson_id=lesson_id,
                    author_user_id=user.user_id,
                    text=request.text,
                    replaces_comment_id=request.replaces_comment_id,
                    created_at=self._clock.now(),
                )
            )
            stored = await uow.result_comments.get(comment_id)
            await uow.commit()
        assert stored is not None
        _record_comment(self._changes, replaced, stored)
        return stored


def _require_lesson_participant(lesson: Lesson, user: AuthenticatedUser) -> None:
    if not any(participant.user_id == user.user_id for participant in lesson.participants):
        raise NotALessonParticipantError(lesson.lesson_id)
