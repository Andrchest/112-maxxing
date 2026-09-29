"""«Случайный порядок карточек» — `shuffle_plan` (I7 E53, G12a; ТЗ ¶340).

* the same seed gives the same order, and the order is a permutation of the cards;
* positions, arrivals and participants stay where they are — only the cards move;
* a card moves only among the slots of its own participant set (each trainee keeps their cards);
* `create_lesson` applies it once with the seed and records the seed; without one, nothing moves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.common.ids import LessonId, ScenarioVersionId, UserId
from app.domain.enums import RoleType, SessionMode
from app.domain.lesson.lesson import Lesson, create_lesson
from app.domain.lesson.plan import Arrival, ArrivalKind, LessonParticipant, PlanEntry
from app.domain.lesson.shuffle import shuffle_plan

NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
ALICE = UserId(UUID("00000000-0000-4000-8000-00000000a11c"))
BOB = UserId(UUID("00000000-0000-4000-8000-000000000b0b"))


Owners = list[tuple[UserId, ...] | None]


def _plan(size: int, participants: Owners | None = None) -> list[PlanEntry]:
    entries = []
    for index in range(size):
        arrival = (
            Arrival(kind=ArrivalKind.AT_OFFSET, offset_ms=index * 1_000)
            if index % 2 == 0
            else Arrival(kind=ArrivalKind.AFTER_PREVIOUS_SESSION, delay_ms=index)
        )
        entries.append(
            PlanEntry(
                position=index + 1,
                scenario_version_id=ScenarioVersionId(uuid4()),
                arrival=arrival,
                weight=float(index + 1),
                participants=None if participants is None else participants[index],
            )
        )
    return entries


def test_the_same_seed_gives_the_same_permutation_of_the_cards() -> None:
    plan = _plan(8)

    first = shuffle_plan(plan, 12345)
    second = shuffle_plan(list(reversed(plan)), 12345)

    assert first == second
    assert sorted(entry.weight for entry in first) == [entry.weight for entry in plan]
    assert {entry.scenario_version_id for entry in first} == {
        entry.scenario_version_id for entry in plan
    }


def test_different_seeds_give_different_orders() -> None:
    plan = _plan(8)
    orders = {tuple(entry.weight for entry in shuffle_plan(plan, seed)) for seed in range(20)}
    assert len(orders) > 1


def test_slots_keep_their_position_arrival_and_participants() -> None:
    plan = _plan(6)

    shuffled = shuffle_plan(plan, 7)

    assert [entry.position for entry in shuffled] == [1, 2, 3, 4, 5, 6]
    assert [entry.arrival for entry in shuffled] == [entry.arrival for entry in plan]
    assert [entry.participants for entry in shuffled] == [entry.participants for entry in plan]
    assert shuffled[0].arrival.kind is ArrivalKind.AT_OFFSET


def test_a_card_moves_only_among_its_own_participants_slots() -> None:
    owners: Owners = [(ALICE,), (BOB,), (ALICE,), (BOB,), (ALICE,), None]
    plan = _plan(6, owners)
    cards_of = {
        owner: {entry.weight for entry in plan if entry.participants == owner}
        for owner in ((ALICE,), (BOB,), None)
    }

    for seed in range(10):
        shuffled = shuffle_plan(plan, seed)
        for owner, weights in cards_of.items():
            assert {e.weight for e in shuffled if e.participants == owner} == weights
        assert shuffled[5].weight == 6.0, "the only everyone-card has nowhere to move"


def _lesson(plan: list[PlanEntry], seed: int | None) -> Lesson:
    return create_lesson(
        lesson_id=LessonId(uuid4()),
        title_ru="Занятие",
        created_by=UserId(uuid4()),
        session_mode=SessionMode.SINGLE_ROLE,
        participants=[LessonParticipant(user_id=ALICE, assigned_role_type=RoleType.DDS)],
        scenario_plan=plan,
        created_at=NOW,
        shuffle_seed=seed,
    )


def test_create_lesson_shuffles_once_with_the_seed_and_records_it() -> None:
    plan = _plan(5)

    lesson = _lesson(plan, 99)

    assert lesson.shuffle_seed == 99
    assert lesson.scenario_plan == shuffle_plan(plan, 99)


def test_create_lesson_without_a_seed_keeps_the_instructors_order() -> None:
    plan = _plan(5)

    lesson = _lesson(plan, None)

    assert lesson.shuffle_seed is None
    assert lesson.scenario_plan == tuple(plan)
