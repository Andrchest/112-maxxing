"""`abortLesson` — `CREATED | ACTIVE --abort--> ABORTED`, then every card (HLD 70 §70.3.2).

Two steps, in this order:

1. one Unit of Work fires `abort` on the lesson and commits. From that moment the `LessonRunner`
   sees a lesson that is no longer `ACTIVE` and starts nothing more;
2. every plan session that is not already `COMPLETED` or `ABORTED` is aborted through the existing
   `abortSession` use case — each in its own Unit of Work, each appending its own
   `SESSION_ABORTED` (and its stages' `STAGE_STATE_CHANGED`) exactly as a hand abort would. The
   cards are listed *after* step 1 commits, so a card the runner started in between is caught.

An illegal abort (a lesson already `COMPLETED` or `ABORTED`) raises `InvalidTransitionError` in
step 1 and touches no session.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.lessons.errors import (
    TERMINAL_SESSION_STATES,
    LessonNotFoundError,
    require_creator_or_admin,
)
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.abort_session import AbortSession
from app.domain.common.actors import ActorRef
from app.domain.common.ids import LessonId, SessionId
from app.domain.enums import ActorType
from app.domain.lesson.lesson import Lesson

__all__ = ["AbortLesson"]


class AbortLesson:
    """`abortLesson` (INSTRUCTOR — the creator — or ADMIN)."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, clock: Clock, abort_session: AbortSession
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._abort_session = abort_session

    async def __call__(
        self, lesson_id: LessonId, user: AuthenticatedUser, reason: str
    ) -> tuple[Lesson, tuple[SessionId, ...]]:
        """Abort the lesson and its running cards; returns the lesson and the sessions aborted."""
        actor = ActorRef(actor_type=ActorType.INSTRUCTOR, actor_id=user.user_id)
        async with self._unit_of_work() as uow:
            lesson = await uow.lessons.get_for_update(lesson_id)
            if lesson is None:
                raise LessonNotFoundError(lesson_id)
            require_creator_or_admin(lesson, user)
            aborted = lesson.abort(self._clock.now(), actor=actor)
            await uow.lessons.save(aborted)
            await uow.commit()

        async with self._unit_of_work() as uow:
            cards = await uow.lessons.list_cards(lesson_id)
            await uow.commit()
        stopped: list[SessionId] = []
        for card in cards:
            if card.state in TERMINAL_SESSION_STATES:
                continue
            await self._abort_session(card.session_id, actor, reason)
            stopped.append(card.session_id)
        return aborted, tuple(stopped)
