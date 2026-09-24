"""The lesson aggregate, its plan and the arrival evaluation (HLD 70 §70.3.1-§70.3.3, I3 E4a).

The arrival table is tested allow **and** deny per kind: every kind is shown not holding one
millisecond before it is due (or while its condition is unknown) and holding at the instant it is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import LessonId, ScenarioVersionId, UserId
from app.domain.enums import ActorType, RoleType, SessionMode, SessionState
from app.domain.lesson.lesson import Lesson, LessonState, create_lesson
from app.domain.lesson.plan import (
    Arrival,
    ArrivalKind,
    LessonParticipant,
    LessonPlanError,
    PlanEntry,
    PreviousCard,
    arrival_due_offset_ms,
    arrival_holds,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
INSTRUCTOR = ActorRef(actor_type=ActorType.INSTRUCTOR, actor_id=UserId(uuid4()))
SYSTEM = ActorRef(actor_type=ActorType.SYSTEM)


def _entry(position: int, arrival: Arrival) -> PlanEntry:
    return PlanEntry(
        position=position,
        scenario_version_id=ScenarioVersionId(uuid4()),
        arrival=arrival,
    )


def _lesson(*entries: PlanEntry) -> Lesson:
    return create_lesson(
        lesson_id=LessonId(uuid4()),
        title_ru="Занятие",
        created_by=UserId(uuid4()),
        session_mode=SessionMode.SINGLE_ROLE,
        participants=[LessonParticipant(user_id=UserId(uuid4()), assigned_role_type=RoleType.DDS)],
        scenario_plan=entries or (_entry(1, Arrival(kind=ArrivalKind.AT_OFFSET, offset_ms=0)),),
        created_at=NOW,
    )


# -- arrivals ----------------------------------------------------------------------------------


def test_at_offset_denies_before_and_allows_at_offset_plus_delay() -> None:
    arrival = Arrival(kind=ArrivalKind.AT_OFFSET, offset_ms=60_000, delay_ms=5_000)
    assert arrival_due_offset_ms(arrival, None) == 65_000
    assert not arrival_holds(arrival, None, 64_999)
    assert arrival_holds(arrival, None, 65_000)


def test_after_previous_112_stage_denies_until_the_handoff_and_its_delay() -> None:
    arrival = Arrival(kind=ArrivalKind.AFTER_PREVIOUS_112_STAGE, delay_ms=10_000)
    assert not arrival_holds(arrival, None, 10**9), "no previous card: never"
    assert not arrival_holds(arrival, PreviousCard(), 10**9), "not handed off yet"
    handed = PreviousCard(handed_off_at_ms=40_000)
    assert not arrival_holds(arrival, handed, 49_999)
    assert arrival_holds(arrival, handed, 50_000)


def test_after_previous_session_denies_until_it_ends_and_its_delay() -> None:
    arrival = Arrival(kind=ArrivalKind.AFTER_PREVIOUS_SESSION)
    handed_but_running = PreviousCard(handed_off_at_ms=40_000)
    assert not arrival_holds(arrival, handed_but_running, 10**9)
    ended = PreviousCard(handed_off_at_ms=40_000, ended_at_ms=90_000)
    assert not arrival_holds(arrival, ended, 89_999)
    assert arrival_holds(arrival, ended, 90_000)


@pytest.mark.parametrize(
    ("kind", "offset_ms"),
    [
        (ArrivalKind.AT_OFFSET, None),
        (ArrivalKind.AFTER_PREVIOUS_SESSION, 1_000),
        (ArrivalKind.AFTER_PREVIOUS_112_STAGE, 0),
    ],
)
def test_offset_is_required_for_at_offset_and_forbidden_otherwise(
    kind: ArrivalKind, offset_ms: int | None
) -> None:
    with pytest.raises(ValidationError):
        Arrival(kind=kind, offset_ms=offset_ms)


# -- the plan ----------------------------------------------------------------------------------


def test_the_plan_is_put_in_position_order() -> None:
    lesson = _lesson(
        _entry(2, Arrival(kind=ArrivalKind.AFTER_PREVIOUS_SESSION)),
        _entry(1, Arrival(kind=ArrivalKind.AT_OFFSET, offset_ms=0)),
    )
    assert [entry.position for entry in lesson.scenario_plan] == [1, 2]
    assert lesson.state is LessonState.CREATED


@pytest.mark.parametrize(
    "positions", [(1, 1), (1, 3), (2,), (0, 1)], ids=["duplicate", "gap", "no-1", "zero"]
)
def test_positions_must_be_exactly_one_to_n(positions: tuple[int, ...]) -> None:
    entries = [
        PlanEntry.model_construct(
            position=position,
            scenario_version_id=ScenarioVersionId(uuid4()),
            arrival=Arrival(kind=ArrivalKind.AT_OFFSET, offset_ms=0),
            variants=None,
            participants=None,
            weight=1.0,
        )
        for position in positions
    ]
    with pytest.raises(LessonPlanError):
        _lesson(*entries)


def test_position_one_must_arrive_at_an_offset() -> None:
    with pytest.raises(LessonPlanError):
        _lesson(_entry(1, Arrival(kind=ArrivalKind.AFTER_PREVIOUS_SESSION)))


# -- LESSON_TRANSITIONS, with their guards -----------------------------------------------------


def test_start_needs_every_plan_session_ready() -> None:
    lesson = _lesson()
    with pytest.raises(InvalidTransitionError):
        lesson.start(NOW, actor=INSTRUCTOR, plan_session_states=[SessionState.CREATED])
    started = lesson.start(NOW, actor=INSTRUCTOR, plan_session_states=[SessionState.READY])
    assert started.state is LessonState.ACTIVE
    assert started.started_at == NOW
    assert lesson.state is LessonState.CREATED, "the aggregate is frozen"


def test_only_an_instructor_starts_and_only_the_system_completes() -> None:
    lesson = _lesson()
    with pytest.raises(InvalidTransitionError):
        lesson.start(NOW, actor=SYSTEM, plan_session_states=[SessionState.READY])
    active = lesson.start(NOW, actor=INSTRUCTOR, plan_session_states=[SessionState.READY])
    with pytest.raises(InvalidTransitionError):
        active.complete(NOW, actor=INSTRUCTOR, plan_session_states=[SessionState.COMPLETED])


def test_complete_needs_every_plan_session_terminal() -> None:
    active = _lesson().start(NOW, actor=INSTRUCTOR, plan_session_states=[SessionState.READY])
    with pytest.raises(InvalidTransitionError):
        active.complete(NOW, actor=SYSTEM, plan_session_states=[SessionState.ACTIVE])
    done = active.complete(NOW, actor=SYSTEM, plan_session_states=[SessionState.ABORTED])
    assert done.state is LessonState.COMPLETED
    assert done.completed_at == NOW


def test_abort_from_created_and_active_and_never_from_a_terminal_state() -> None:
    lesson = _lesson()
    assert lesson.abort(NOW, actor=INSTRUCTOR).state is LessonState.ABORTED
    active = lesson.start(NOW, actor=INSTRUCTOR, plan_session_states=[SessionState.READY])
    aborted = active.abort(NOW, actor=SYSTEM)
    assert aborted.state is LessonState.ABORTED
    with pytest.raises(InvalidTransitionError):
        aborted.abort(NOW, actor=INSTRUCTOR)


def test_the_release_keeps_the_first_one() -> None:
    first_user, second_user = UserId(uuid4()), UserId(uuid4())
    released = _lesson().release_report(NOW, released_by=first_user)
    again = released.release_report(datetime(2027, 1, 1, tzinfo=UTC), released_by=second_user)
    assert again.report_released_at == NOW
    assert again.report_released_by_user_id == first_user
