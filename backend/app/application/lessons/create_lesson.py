"""`createLesson` — a lesson and every one of its cards, in one Unit of Work (HLD 70 §70.3.2, D15).

1. build the `Lesson` (`create_lesson` checks the plan: positions `1..N`, position 1 `AT_OFFSET`,
   at least one participant) and insert its row first — the sessions reference it;
2. for each plan entry, in `position` order, create an ordinary session through the existing
   `createSession` path (`CreateSession.create_in`), with:
   - the lesson's participants, or the entry's subset (`PlanEntry.participants`, E9a's hook),
     each with its ДДС service binding (`assigned_service_id`, HLD 70 §70.4.5, I3 E5b),
   - the lesson-wide variants request overridden switch by switch by the entry's,
   - `lesson_id` / `lesson_position` set,
   so each card is validated exactly as a single session would be (version valid, variants
   implemented and supported, participants assignable under `session_mode`) and ends `READY`;
3. commit — or, when any entry is refused, roll everything back: no lesson row, no session.

A refusal is `createSession`'s own for the offending entry (`LessonPlanEntryRefusedError`, same
`ProblemCode`, `detail` naming the position). Nothing ticks until `startLesson`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.application.lessons.errors import LessonPlanEntryRefusedError
from app.application.ports.clock import Clock
from app.application.ports.id_generator import IdGenerator
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.create_session import CreateSession, CreateSessionCommand
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import LessonId
from app.domain.enums import SessionMode
from app.domain.lesson.lesson import Lesson, create_lesson
from app.domain.lesson.plan import LessonParticipant, LessonPlanError, PlanEntry
from app.domain.session.variants import SWITCHES, PartialVariants

__all__ = ["CreateLesson", "CreateLessonCommand", "merge_variants"]


@dataclass(frozen=True)
class CreateLessonCommand:
    """`LessonCreateRequest` plus the authenticated instructor."""

    title_ru: str
    session_mode: SessionMode
    actor: ActorRef
    participants: Sequence[LessonParticipant]
    scenario_plan: Sequence[PlanEntry]
    variants: PartialVariants = field(default_factory=PartialVariants)
    time_scale: float = 1.0


def merge_variants(lesson: PartialVariants, entry: PartialVariants | None) -> PartialVariants:
    """The request a card is created with: the entry's value per switch, else the lesson's."""
    if entry is None:
        return lesson
    return PartialVariants.model_validate(
        {
            switch: (
                getattr(entry, switch)
                if getattr(entry, switch) is not None
                else getattr(lesson, switch)
            )
            for switch in SWITCHES
        }
    )


def _card_participants(lesson: Lesson, entry: PlanEntry) -> tuple[LessonParticipant, ...]:
    """The card's participants: the lesson's, or the entry's subset (E9a's hook)."""
    if entry.participants is None:
        chosen = lesson.participants
    else:
        known = {participant.user_id: participant for participant in lesson.participants}
        unknown = [str(user_id) for user_id in entry.participants if user_id not in known]
        if unknown:
            raise LessonPlanError(
                f"scenario_plan position {entry.position} names participants that are not "
                f"lesson participants: {', '.join(unknown)}"
            )
        chosen = tuple(known[user_id] for user_id in entry.participants)
    return chosen


class CreateLesson:
    """Create a lesson and all of its sessions, atomically."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        create_session: CreateSession,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ids = ids
        self._clock = clock
        self._create_session = create_session

    async def __call__(self, command: CreateLessonCommand) -> Lesson:
        created_by = command.actor.actor_id
        if created_by is None:
            raise ValueError("createLesson needs an actor carrying an actor_id")
        lesson = create_lesson(
            lesson_id=LessonId(self._ids.new()),
            title_ru=command.title_ru,
            created_by=created_by,
            session_mode=command.session_mode,
            participants=command.participants,
            scenario_plan=command.scenario_plan,
            created_at=self._clock.now(),
            variants=command.variants,
        )
        async with self._unit_of_work() as uow:
            await uow.lessons.add(lesson)
            for entry in lesson.scenario_plan:
                chosen = _card_participants(lesson, entry)
                card = CreateSessionCommand(
                    scenario_version_id=entry.scenario_version_id,
                    session_mode=lesson.session_mode,
                    actor=command.actor,
                    participants=tuple(
                        (participant.user_id, participant.assigned_role_type)
                        for participant in chosen
                    ),
                    assigned_services={
                        participant.user_id: participant.assigned_service_id
                        for participant in chosen
                        if participant.assigned_service_id is not None
                    },
                    time_scale=command.time_scale,
                    variants=merge_variants(lesson.variants, entry.variants),
                    lesson_id=lesson.lesson_id,
                    lesson_position=entry.position,
                )
                try:
                    await self._create_session.create_in(uow, card)
                except LessonPlanError:
                    raise
                except DomainError as exc:
                    raise LessonPlanEntryRefusedError(entry.position, exc) from exc
            await uow.commit()
        return lesson
