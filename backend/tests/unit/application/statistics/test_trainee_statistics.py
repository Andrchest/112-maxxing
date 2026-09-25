"""Per-trainee statistics and the trainee's history (I4 E33, HLD 71 §71.10) — without a database.

* every number is an aggregate of stored rows; a norm deviation is attributed to the trainee who
  played that interval (the 112 desk's participant, a leg's bound player, never a scripted leg);
* a TRAINEE reads themselves only (`403` for another) and only the sessions whose report is
  visible to them; the history lists an unreleased session without its score;
* the statistics CSV carries the same numbers as the rows.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.statistics.ports import (
    ScoredSession,
    StatisticsEvent,
    StatisticsFilter,
    StatisticsParticipant,
    TraineeAccount,
)
from app.application.statistics.statistics_csv import STATISTICS_CSV_HEADER, statistics_csv
from app.application.statistics.trainee_statistics import (
    GetMyHistory,
    GetTraineeStatistics,
    StatisticsSubjectNotFoundError,
    session_percent,
    statistics_row,
)
from app.domain.common.ids import LessonId, SessionId, TraineeGroupId, UserId
from app.domain.dds.card_status import DEFAULT_CARD_TIMERS
from app.domain.enums import RoleType, SessionMode
from app.domain.events.types import EventType

OPERATOR = UserId(UUID(int=1))
DISPATCHER = UserId(UUID(int=2))
SOLO = UserId(UUID(int=3))
LESSON = LessonId(UUID(int=100))
DONE = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
TIMERS = {"accept_within_ms": 30_000, "fill_within_ms": 180_000, "not_completed_after_ms": 90_000}


def _event(event_type: EventType, offset_ms: int, **payload: Any) -> StatisticsEvent:
    return StatisticsEvent(event_type=event_type, payload=payload, monotonic_offset_ms=offset_ms)


def _log(chain: list[str]) -> tuple[StatisticsEvent, ...]:
    """112 fill 150 s (−30 s); legs: bound to DISPATCHER +10 s, unbound −20 s, scripted +50 s."""
    return (
        _event(EventType.SESSION_CREATED, 0, role_chain=chain, timers=TIMERS),
        _event(EventType.CALL_ANSWERED, 10_000),
        _event(EventType.HANDOFF_CREATED, 160_000),
        _event(
            EventType.HANDOFF_RECEIVED,
            160_000,
            assignment_id="a",
            service_type="FIRE_RESCUE",
            responder="TRAINEE",
            bound_user_id=str(DISPATCHER),
        ),
        _event(EventType.HANDOFF_RECEIVED, 160_000, assignment_id="b", service_type="POLICE"),
        _event(
            EventType.HANDOFF_RECEIVED,
            160_000,
            assignment_id="c",
            service_type="AMBULANCE",
            responder="SCRIPTED",
        ),
        _event(EventType.DDS_SERVICE_STATUS_SET, 200_000, assignment_id="a", new_status="ACCEPTED"),
        _event(EventType.DDS_SERVICE_STATUS_SET, 170_000, assignment_id="b", new_status="ACCEPTED"),
        _event(
            EventType.DDS_SERVICE_STATUS_SET, 240_000, assignment_id="c", new_status="NOT_ACCEPTED"
        ),
    )


def _memo_log(chain: list[str]) -> tuple[StatisticsEvent, ...]:
    _, *rest = _log(chain)
    memo = _event(
        EventType.SESSION_CREATED,
        0,
        role_chain=chain,
        timers=TIMERS,
        variants={"dds_mode": "MEMO_STATUSES"},
    )
    return (memo, *rest)


def _session(
    participants: Sequence[tuple[UserId, RoleType | None]],
    *,
    mode: SessionMode = SessionMode.MULTI_TRAINEE,
    released: bool = True,
    points: float = 30.0,
    max_points: float = 40.0,
    failed: dict[str, int] | None = None,
    lesson: LessonId | None = LESSON,
    completed_at: datetime = DONE,
    events: tuple[StatisticsEvent, ...] | None = None,
) -> ScoredSession:
    failed = {"TIMELINESS": 1, "WORKFLOW": 2} if failed is None else failed
    return ScoredSession(
        session_id=SessionId(uuid4()),
        lesson_id=lesson,
        session_mode=mode,
        completed_at=completed_at,
        report_released=released,
        scenario_title_ru="Пожар в квартире",
        scenario_timers=DEFAULT_CARD_TIMERS,
        participants=tuple(StatisticsParticipant(u, r) for u, r in participants),
        total_points=points,
        total_max_points=max_points,
        failed_by_category=failed,
        failed_rule_count=sum(failed.values()),
        critical_error_count=0,
        events=_memo_log(["OPERATOR_112", "DDS"]) if events is None else events,
    )


def _user(user_id: UserId, role: UserRole = UserRole.TRAINEE) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id, username=str(user_id), display_name_ru="x", user_role=role
    )


INSTRUCTOR = _user(UserId(UUID(int=99)), UserRole.INSTRUCTOR)


class FakeReader:
    def __init__(self, sessions: Sequence[ScoredSession], groups: set[UUID] | None = None) -> None:
        self.sessions = tuple(sessions)
        self.groups = groups or set()
        self.accounts_by_id = {
            OPERATOR: TraineeAccount(OPERATOR, "Оператор"),
            DISPATCHER: TraineeAccount(DISPATCHER, "Диспетчер"),
            SOLO: TraineeAccount(SOLO, "Один"),
        }

    async def trainees(self, query: StatisticsFilter) -> tuple[TraineeAccount, ...]:
        found = [
            account
            for user_id, account in self.accounts_by_id.items()
            if query.trainee_id is None or query.trainee_id == user_id
        ]
        return tuple(sorted(found, key=lambda account: account.display_name_ru))

    async def accounts(self, user_ids: Sequence[UserId]) -> tuple[TraineeAccount, ...]:
        return tuple(self.accounts_by_id[u] for u in user_ids if u in self.accounts_by_id)

    async def group_exists(self, group_id: TraineeGroupId) -> bool:
        return group_id in self.groups

    async def scored_sessions(
        self,
        user_ids: Sequence[UserId],
        *,
        from_utc: datetime | None = None,
        to_utc: datetime | None = None,
    ) -> tuple[ScoredSession, ...]:
        return tuple(
            session
            for session in self.sessions
            if any(p.user_id in user_ids for p in session.participants)
            and (from_utc is None or session.completed_at >= from_utc)
            and (to_utc is None or session.completed_at < to_utc)
        )


# -- the row ----------------------------------------------------------------------------------


def test_each_trainee_answers_for_the_intervals_they_played() -> None:
    session = _session([(OPERATOR, RoleType.OPERATOR_112), (DISPATCHER, RoleType.DDS)])
    operator = statistics_row(TraineeAccount(OPERATOR, "Оператор"), [session])
    dispatcher = statistics_row(TraineeAccount(DISPATCHER, "Диспетчер"), [session])

    assert operator.fill_deviation_ms_avg == -30_000
    assert operator.accept_deviation_ms_avg is None, "no leg is the 112 desk's"
    assert dispatcher.fill_deviation_ms_avg is None
    # its bound leg (+10 s) and the unbound one (−20 s); never the scripted one (+50 s)
    assert dispatcher.accept_deviation_ms_avg == -5_000
    assert operator.average_percent == dispatcher.average_percent == 75.0
    assert operator.failed_rules_by_category == {"TIMELINESS": 1, "WORKFLOW": 2}
    assert (operator.session_count, operator.lesson_count) == (1, 1)


def test_a_full_cycle_trainee_covers_the_whole_chain_and_a_bound_leg_stays_its_player_s() -> None:
    session = _session([(SOLO, None)], mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE)
    row = statistics_row(TraineeAccount(SOLO, "Один"), [session])
    assert row.fill_deviation_ms_avg == -30_000
    assert row.accept_deviation_ms_avg == -20_000, "the unbound leg only"


def test_the_averages_are_over_sessions_and_a_percent_stays_within_0_100() -> None:
    sessions = [
        _session([(OPERATOR, None)], points=30, max_points=40, lesson=None),
        _session([(OPERATOR, None)], points=-10, max_points=40, failed={"WORKFLOW": 1}),
        _session([(OPERATOR, None)], points=0, max_points=0, failed={}),
    ]
    assert [session_percent(s) for s in sessions] == [75.0, 0.0, None]
    row = statistics_row(TraineeAccount(OPERATOR, "Оператор"), sessions)
    assert row.average_percent == 37.5
    assert row.session_count == 3 and row.lesson_count == 1
    assert row.failed_rules_by_category == {"TIMELINESS": 1, "WORKFLOW": 3}


def test_a_trainee_without_sessions_has_no_averages() -> None:
    row = statistics_row(TraineeAccount(SOLO, "Один"), [])
    assert (row.session_count, row.average_percent, row.accept_deviation_ms_avg) == (0, None, None)
    assert row.failed_rules_by_category == {}


# -- who sees what ----------------------------------------------------------------------------


async def test_a_trainee_asking_for_someone_else_is_refused() -> None:
    use_case = GetTraineeStatistics(FakeReader([]))
    with pytest.raises(ForbiddenForRoleError):
        await use_case(StatisticsFilter(trainee_id=OPERATOR), _user(DISPATCHER))


async def test_a_trainee_reads_their_own_row_over_their_visible_sessions_only() -> None:
    released = _session([(DISPATCHER, RoleType.DDS)], points=40, max_points=40)
    hidden = _session([(DISPATCHER, RoleType.DDS)], released=False, points=0, max_points=40)
    free = _session(
        [(DISPATCHER, RoleType.DDS)], mode=SessionMode.SINGLE_ROLE, released=False, points=20
    )
    reader = FakeReader([released, hidden, free])

    own = await GetTraineeStatistics(reader)(StatisticsFilter(), _user(DISPATCHER))
    [row] = own.rows
    assert row.trainee_user_id == DISPATCHER
    assert row.session_count == 2, "the unreleased MULTI_TRAINEE session is not counted"
    assert row.average_percent == 75.0

    everyone = await GetTraineeStatistics(reader)(StatisticsFilter(), INSTRUCTOR)
    by_id = {r.trainee_user_id: r for r in everyone.rows}
    assert by_id[DISPATCHER].session_count == 3
    assert by_id[OPERATOR].session_count == 0


async def test_an_unknown_trainee_or_group_is_not_found() -> None:
    use_case = GetTraineeStatistics(FakeReader([]))
    with pytest.raises(StatisticsSubjectNotFoundError):
        await use_case(StatisticsFilter(trainee_id=UserId(uuid4())), INSTRUCTOR)
    with pytest.raises(StatisticsSubjectNotFoundError):
        await use_case(StatisticsFilter(group_id=TraineeGroupId(uuid4())), INSTRUCTOR)


async def test_the_window_is_passed_to_the_reader() -> None:
    old = _session([(OPERATOR, None)], completed_at=DONE - timedelta(days=2))
    new = _session([(OPERATOR, None)])
    view = await GetTraineeStatistics(FakeReader([old, new]))(
        StatisticsFilter(trainee_id=OPERATOR, from_utc=DONE - timedelta(days=1)), INSTRUCTOR
    )
    assert [row.session_count for row in view.rows] == [1]


async def test_the_history_lists_an_unreleased_session_without_its_score() -> None:
    released = _session([(DISPATCHER, RoleType.DDS)], completed_at=DONE - timedelta(hours=1))
    hidden = _session([(DISPATCHER, RoleType.DDS)], released=False)
    history = await GetMyHistory(FakeReader([released, hidden]))(_user(DISPATCHER))

    assert [s.session_id for s in history.sessions] == [hidden.session_id, released.session_id]
    newest, older = history.sessions
    assert (newest.score_percent, newest.failed_rule_count) == (None, None)
    assert (older.score_percent, older.failed_rule_count) == (75.0, 3)
    assert history.statistics.session_count == 1
    assert history.statistics.display_name_ru == "Диспетчер"


# -- the CSV ----------------------------------------------------------------------------------


async def test_the_statistics_csv_carries_the_rows_numbers() -> None:
    session = _session([(OPERATOR, RoleType.OPERATOR_112), (DISPATCHER, RoleType.DDS)])
    view = await GetTraineeStatistics(FakeReader([session]))(StatisticsFilter(), INSTRUCTOR)
    text = statistics_csv(view).decode("utf-8-sig")
    header, *lines = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert tuple(header) == STATISTICS_CSV_HEADER
    assert len(lines) == len(view.rows)
    for line, row in zip(lines, view.rows, strict=True):
        cells = dict(zip(header, line, strict=True))
        assert cells["Идентификатор"] == str(row.trainee_user_id)
        assert int(cells["Сессий"]) == row.session_count
        assert _number(cells["Средний процент"]) == row.average_percent
        assert _number(cells["Среднее отклонение принятия решения, мс"]) == (
            row.accept_deviation_ms_avg
        )
        assert _number(cells["Среднее отклонение заполнения карточки, мс"]) == (
            row.fill_deviation_ms_avg
        )
        assert int(cells["Нарушено правил: Порядок действий"]) == (
            row.failed_rules_by_category.get("WORKFLOW", 0)
        )


def _number(cell: str) -> float | None:
    return None if cell == "" else float(cell.replace(",", "."))
