"""`releaseLessonReport` — release every card report of a lesson (HLD 70 §70.3.6, §70.4.6).

It calls the existing per-session `releaseReportToTrainee` for every `COMPLETED` card (an aborted
card has no report), which sets each card's `incidents.card_status` to `CHECKED` where the
projection allows it, and then records the lesson-level release on the lesson row. Idempotent —
the per-session release keeps its first release, and so does the lesson — and it emits no event
(HLD 20 §20.3: the logs are closed).
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.lessons.errors import (
    LessonNotFoundError,
    LessonReportNotReadyError,
    require_creator_or_admin,
)
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.reports.release_report import ReleaseReportToTrainee
from app.application.sessions.queries import ForbiddenForRoleError
from app.domain.common.ids import LessonId
from app.domain.enums import SessionState
from app.domain.lesson.lesson import Lesson

__all__ = ["ReleaseLessonReport"]


class ReleaseLessonReport:
    """`releaseLessonReport` (INSTRUCTOR — the creator (I5 E39) — or ADMIN)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        release_session: ReleaseReportToTrainee,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._release_session = release_session

    async def __call__(self, lesson_id: LessonId, user: AuthenticatedUser) -> Lesson:
        if not user.is_instructor_or_admin:
            raise ForbiddenForRoleError(
                f"the caller may not release the report of lesson {lesson_id}: "
                "INSTRUCTOR/ADMIN only"
            )
        async with self._unit_of_work() as uow:
            lesson = await uow.lessons.get(lesson_id)
            if lesson is None:
                raise LessonNotFoundError(lesson_id)
            require_creator_or_admin(lesson, user)  # I5 E39: NOT_RESOURCE_OWNER
            if not lesson.is_terminal:
                raise LessonReportNotReadyError(lesson_id, lesson.state)
            cards = await uow.lessons.list_cards(lesson_id)
            await uow.commit()

        for card in cards:
            if card.state is SessionState.COMPLETED:
                await self._release_session(card.session_id, user)

        async with self._unit_of_work() as uow:
            current = await uow.lessons.get_for_update(lesson_id)
            if current is None:  # pragma: no cover - read a moment ago; lessons are never deleted
                raise LessonNotFoundError(lesson_id)
            released = current.release_report(self._clock.now(), released_by=user.user_id)
            await uow.lessons.save(released)
            await uow.commit()
        return released
