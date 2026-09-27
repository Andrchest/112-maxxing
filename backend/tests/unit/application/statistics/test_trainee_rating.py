"""`getTraineeRating` and its CSV (I5 E36, Q-E12-2) — without a database.

* trainees are ranked by `average_percent` descending, ties broken by name;
* a trainee with no qualifying (scored, COMPLETED) session is left out of the ranking entirely —
  the same exclusion rule the weighted sum and `getTraineeStatistics` already apply;
* a TRAINEE is refused; INSTRUCTOR / ADMIN see the whole ranking;
* the CSV carries the same rows, in rank order.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.statistics.ports import (
    ScoredSession,
    StatisticsFilter,
    StatisticsParticipant,
    TraineeAccount,
)
from app.application.statistics.trainee_rating import GetTraineeRating
from app.application.statistics.trainee_rating_csv import (
    TRAINEE_RATING_CSV_HEADER,
    trainee_rating_csv,
)
from app.application.statistics.trainee_statistics import StatisticsSubjectNotFoundError
from app.domain.common.ids import SessionId, TraineeGroupId, UserId
from app.domain.dds.card_status import DEFAULT_CARD_TIMERS
from app.domain.enums import SessionMode

FIRST = UserId(UUID(int=1))
SECOND = UserId(UUID(int=2))
TIED_A = UserId(UUID(int=3))
TIED_B = UserId(UUID(int=4))
IDLE = UserId(UUID(int=5))
DONE = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _session(user_id: UserId, points: float, max_points: float = 40.0) -> ScoredSession:
    return ScoredSession(
        session_id=SessionId(uuid4()),
        lesson_id=None,
        session_mode=SessionMode.SINGLE_ROLE,
        completed_at=DONE,
        report_released=True,
        scenario_title_ru="Пожар",
        scenario_timers=DEFAULT_CARD_TIMERS,
        participants=(StatisticsParticipant(user_id, None),),
        total_points=points,
        total_max_points=max_points,
        failed_by_category={},
        failed_rule_count=0,
        critical_error_count=0,
        events=(),
    )


def _user(user_id: UserId, role: UserRole = UserRole.TRAINEE) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id, username=str(user_id), display_name_ru="x", user_role=role
    )


INSTRUCTOR = _user(UserId(UUID(int=99)), UserRole.INSTRUCTOR)


class FakeReader:
    def __init__(self, sessions: Sequence[ScoredSession]) -> None:
        self.sessions = tuple(sessions)
        self.accounts_by_id = {
            FIRST: TraineeAccount(FIRST, "Первый"),
            SECOND: TraineeAccount(SECOND, "Второй"),
            TIED_A: TraineeAccount(TIED_A, "Иванов"),
            TIED_B: TraineeAccount(TIED_B, "Петров"),
            IDLE: TraineeAccount(IDLE, "Незанятый"),
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
        return False

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
        )


async def test_trainees_are_ranked_by_average_percent_descending() -> None:
    sessions = [_session(FIRST, 20, 40), _session(SECOND, 30, 40)]  # 50 %, 75 %
    view = await GetTraineeRating(FakeReader(sessions))(StatisticsFilter(), INSTRUCTOR)
    assert [(row.rank, row.trainee_user_id, row.average_percent) for row in view.rows] == [
        (1, SECOND, 75.0),
        (2, FIRST, 50.0),
    ]


async def test_a_tie_is_broken_by_name_and_still_ranked_1_and_2() -> None:
    sessions = [_session(TIED_A, 20, 40), _session(TIED_B, 20, 40)]  # both 50 %
    view = await GetTraineeRating(FakeReader(sessions))(StatisticsFilter(), INSTRUCTOR)
    assert [(row.rank, row.display_name_ru) for row in view.rows] == [
        (1, "Иванов"),
        (2, "Петров"),
    ]
    assert view.rows[0].average_percent == view.rows[1].average_percent == 50.0


async def test_a_trainee_with_no_qualifying_session_is_left_out_of_the_ranking() -> None:
    sessions = [_session(FIRST, 20, 40)]
    view = await GetTraineeRating(FakeReader(sessions))(
        StatisticsFilter(trainee_id=None), INSTRUCTOR
    )
    assert IDLE not in {row.trainee_user_id for row in view.rows}


async def test_a_trainee_is_refused() -> None:
    with pytest.raises(ForbiddenForRoleError):
        await GetTraineeRating(FakeReader([]))(StatisticsFilter(), _user(FIRST))


async def test_an_unknown_trainee_or_group_is_not_found() -> None:
    with pytest.raises(StatisticsSubjectNotFoundError):
        await GetTraineeRating(FakeReader([]))(
            StatisticsFilter(trainee_id=UserId(uuid4())), INSTRUCTOR
        )
    with pytest.raises(StatisticsSubjectNotFoundError):
        await GetTraineeRating(FakeReader([]))(
            StatisticsFilter(group_id=TraineeGroupId(uuid4())), INSTRUCTOR
        )


async def test_the_rating_csv_carries_the_rows_in_rank_order() -> None:
    sessions = [_session(FIRST, 20, 40), _session(SECOND, 30, 40)]
    view = await GetTraineeRating(FakeReader(sessions))(StatisticsFilter(), INSTRUCTOR)
    text = trainee_rating_csv(view).decode("utf-8-sig")
    header, *lines = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert tuple(header) == TRAINEE_RATING_CSV_HEADER
    assert len(lines) == len(view.rows)
    for line, row in zip(lines, view.rows, strict=True):
        cells = dict(zip(header, line, strict=True))
        assert int(cells["Место"]) == row.rank
        assert cells["Обучаемый"] == row.display_name_ru
        assert cells["Идентификатор"] == str(row.trainee_user_id)
        assert _number(cells["Средний процент"]) == row.average_percent


def _number(cell: str) -> float | None:
    return None if cell == "" else float(cell.replace(",", "."))
