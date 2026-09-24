"""`startLesson` — `CREATED --start--> ACTIVE` (HLD 70 §70.3.2, D15).

One Unit of Work: the lesson row lock, the creator-or-ADMIN check, the plan sessions' states
projected for `guard_every_plan_session_ready`, `start` (sets `started_at` — the origin of the
lesson's wall clock, against which every arrival is measured), write back. The `LessonRunner`
then starts the cards by arrival; the router adopts the lesson after this commit, exactly as
`startSession` adopts a session (D7).
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.lessons.errors import LessonNotFoundError, require_creator_or_admin
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.actors import ActorRef
from app.domain.common.ids import LessonId
from app.domain.enums import ActorType
from app.domain.lesson.lesson import Lesson

__all__ = ["StartLesson"]


class StartLesson:
    """`startLesson` (INSTRUCTOR — the creator — or ADMIN)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(self, lesson_id: LessonId, user: AuthenticatedUser) -> Lesson:
        async with self._unit_of_work() as uow:
            lesson = await uow.lessons.get_for_update(lesson_id)
            if lesson is None:
                raise LessonNotFoundError(lesson_id)
            require_creator_or_admin(lesson, user)
            cards = await uow.lessons.list_cards(lesson_id)
            started = lesson.start(
                self._clock.now(),
                actor=ActorRef(actor_type=ActorType.INSTRUCTOR, actor_id=user.user_id),
                plan_session_states=[card.state for card in cards],
            )
            await uow.lessons.save(started)
            await uow.commit()
        return started
