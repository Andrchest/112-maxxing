"""The `Lesson` aggregate and `LESSON_TRANSITIONS` (HLD 70 §70.3.1, §70.3.2, D15).

* `CREATED --start--> ACTIVE` — INSTRUCTOR; `guard_every_plan_session_ready`; sets `started_at`;
* `ACTIVE --complete--> COMPLETED` — SYSTEM (LessonRunner); `guard_every_plan_session_terminal`;
* `CREATED | ACTIVE --abort--> ABORTED` — INSTRUCTOR, SYSTEM (the use case aborts the sessions);
* `COMPLETED`, `ABORTED` — terminal.

"The creator or an ADMIN" narrows INSTRUCTOR for `start` and `abort`; that is an account fact
the machine cannot see, so the use cases check it (`403 FORBIDDEN_FOR_ROLE`).

The guards read `LessonGuardFacts` — the states of the plan's sessions, projected by the
application — through `GuardContext.session`, exactly as the session guards read their aggregate.
A lesson emits no events: it is scheduling, not simulation, and every card's own log is complete
without it. Every behaviour returns a new frozen value; an illegal trigger raises
`InvalidTransitionError` and returns nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.actors import ActorRef
from app.domain.common.ids import LessonId, UserId
from app.domain.common.state_machine import (
    GuardContext,
    StateMachine,
    Transition,
    TransitionTable,
)
from app.domain.enums import ActorType, SessionMode, SessionState
from app.domain.lesson.plan import LessonParticipant, LessonPlanError, PlanEntry, validate_plan
from app.domain.session.variants import PartialVariants

__all__ = [
    "LESSON_GUARDS",
    "LESSON_STATE_MACHINE",
    "LESSON_TRANSITIONS",
    "TERMINAL_LESSON_STATES",
    "Lesson",
    "LessonGuardFacts",
    "LessonState",
    "create_lesson",
]


class LessonState(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


TERMINAL_LESSON_STATES: frozenset[LessonState] = frozenset(
    {LessonState.COMPLETED, LessonState.ABORTED}
)

_TERMINAL_SESSION_STATES = frozenset({SessionState.COMPLETED, SessionState.ABORTED})


def _row(
    source: LessonState,
    trigger: str,
    target: LessonState,
    actors: frozenset[ActorType],
    guard: str | None = None,
) -> tuple[tuple[LessonState, str], Transition[LessonState]]:
    return (source, trigger), Transition(
        source=source, trigger=trigger, target=target, allowed_actors=actors, guard_name=guard
    )


_INSTRUCTOR = frozenset({ActorType.INSTRUCTOR})
_SYSTEM = frozenset({ActorType.SYSTEM})
_INSTRUCTOR_OR_SYSTEM = frozenset({ActorType.INSTRUCTOR, ActorType.SYSTEM})

LESSON_TRANSITIONS: TransitionTable[LessonState] = dict(
    [
        _row(
            LessonState.CREATED,
            "start",
            LessonState.ACTIVE,
            _INSTRUCTOR,
            "guard_every_plan_session_ready",
        ),
        _row(
            LessonState.ACTIVE,
            "complete",
            LessonState.COMPLETED,
            _SYSTEM,
            "guard_every_plan_session_terminal",
        ),
        _row(LessonState.CREATED, "abort", LessonState.ABORTED, _INSTRUCTOR_OR_SYSTEM),
        _row(LessonState.ACTIVE, "abort", LessonState.ABORTED, _INSTRUCTOR_OR_SYSTEM),
    ]
)
"""§70.3.2, one row per `(source, trigger)`; `COMPLETED` and `ABORTED` have no outgoing row."""


class LessonGuardFacts(BaseModel):
    """What the lesson guards need: the state of every plan session, in `position` order."""

    model_config = ConfigDict(frozen=True)

    plan_session_states: tuple[SessionState, ...]


def _facts(ctx: GuardContext) -> LessonGuardFacts | None:
    facts = ctx.session
    return facts if isinstance(facts, LessonGuardFacts) else None


def guard_every_plan_session_ready(ctx: GuardContext) -> bool:
    """`start`: every plan session is `READY` (and there is at least one)."""
    facts = _facts(ctx)
    return (
        facts is not None
        and bool(facts.plan_session_states)
        and all(state is SessionState.READY for state in facts.plan_session_states)
    )


def guard_every_plan_session_terminal(ctx: GuardContext) -> bool:
    """`complete`: every plan session is `COMPLETED` or `ABORTED`."""
    facts = _facts(ctx)
    return (
        facts is not None
        and bool(facts.plan_session_states)
        and all(state in _TERMINAL_SESSION_STATES for state in facts.plan_session_states)
    )


LESSON_GUARDS: Mapping[str, Callable[[GuardContext], bool]] = {
    "guard_every_plan_session_ready": guard_every_plan_session_ready,
    "guard_every_plan_session_terminal": guard_every_plan_session_terminal,
}

LESSON_STATE_MACHINE: StateMachine[LessonState] = StateMachine(LESSON_TRANSITIONS, LESSON_GUARDS)


class Lesson(BaseModel):
    """One `lessons` row (§70.3.1, §70.8 `0011_lessons`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lesson_id: LessonId
    title_ru: str = Field(min_length=1)
    created_by_user_id: UserId
    session_mode: SessionMode
    variants: PartialVariants = PartialVariants()
    """The lesson-wide variants request, resolved per card (a `PlanEntry.variants` overrides)."""
    participants: tuple[LessonParticipant, ...]
    scenario_plan: tuple[PlanEntry, ...]
    state: LessonState = LessonState.CREATED
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    """When the lesson reached `COMPLETED` or `ABORTED`."""
    report_released_at: datetime | None = None
    report_released_by_user_id: UserId | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_LESSON_STATES

    def entry(self, position: int) -> PlanEntry:
        """The plan entry at `position`; `KeyError` when there is none."""
        for entry in self.scenario_plan:
            if entry.position == position:
                return entry
        raise KeyError(f"lesson {self.lesson_id} has no plan position {position}")

    def _fire(
        self, trigger: str, actor: ActorRef, plan_session_states: Sequence[SessionState]
    ) -> LessonState:
        ctx = GuardContext(
            actor=actor, session=LessonGuardFacts(plan_session_states=tuple(plan_session_states))
        )
        return LESSON_STATE_MACHINE.fire(self.state, trigger, ctx)

    def start(
        self,
        started_at: datetime,
        *,
        actor: ActorRef,
        plan_session_states: Sequence[SessionState],
    ) -> Lesson:
        """`CREATED --start--> ACTIVE` (INSTRUCTOR); sets `started_at`."""
        state = self._fire("start", actor, plan_session_states)
        return self.model_copy(update={"state": state, "started_at": started_at})

    def complete(
        self,
        completed_at: datetime,
        *,
        actor: ActorRef,
        plan_session_states: Sequence[SessionState],
    ) -> Lesson:
        """`ACTIVE --complete--> COMPLETED` (SYSTEM, the LessonRunner)."""
        state = self._fire("complete", actor, plan_session_states)
        return self.model_copy(update={"state": state, "completed_at": completed_at})

    def abort(self, aborted_at: datetime, *, actor: ActorRef) -> Lesson:
        """`CREATED | ACTIVE --abort--> ABORTED` (INSTRUCTOR, SYSTEM)."""
        state = self._fire("abort", actor, ())
        return self.model_copy(update={"state": state, "completed_at": aborted_at})

    def release_report(self, released_at: datetime, *, released_by: UserId) -> Lesson:
        """Record the lesson-level release, idempotently (the first release is kept)."""
        if self.report_released_at is not None:
            return self
        return self.model_copy(
            update={"report_released_at": released_at, "report_released_by_user_id": released_by}
        )


def create_lesson(
    *,
    lesson_id: LessonId,
    title_ru: str,
    created_by: UserId,
    session_mode: SessionMode,
    participants: Sequence[LessonParticipant],
    scenario_plan: Sequence[PlanEntry],
    created_at: datetime,
    variants: PartialVariants | None = None,
) -> Lesson:
    """A `CREATED` lesson with its plan checked and put in `position` order (`LessonPlanError`)."""
    if not participants:
        raise LessonPlanError("a lesson needs at least one participant")
    return Lesson(
        lesson_id=lesson_id,
        title_ru=title_ru,
        created_by_user_id=created_by,
        session_mode=session_mode,
        variants=variants if variants is not None else PartialVariants(),
        participants=tuple(participants),
        scenario_plan=validate_plan(tuple(scenario_plan)),
        created_at=created_at,
    )
