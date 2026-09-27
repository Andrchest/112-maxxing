"""«Сдал / не сдал» read at report time (I5 E38, Q-E9b-3) — without a database.

* the criteria are read from `SESSION_CREATED.pass_criteria`; a log without the key (a session
  created before I5 E38) gets the defaults;
* the trainee statistics count the sessions judged «сдал» under each session's own recorded
  criteria (`pass_count`, `pass_rate`), and the statistics CSV carries the same numbers;
* the rating carries the same two numbers as an additional column — the ranking is unchanged —
  and so does its CSV.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.application.reports.pass_verdict import recorded_pass_criteria, session_pass_verdict
from app.application.statistics.ports import (
    ScoredSession,
    StatisticsEvent,
    StatisticsFilter,
    StatisticsParticipant,
    TraineeAccount,
)
from app.application.statistics.statistics_csv import statistics_csv
from app.application.statistics.trainee_rating import GetTraineeRating
from app.application.statistics.trainee_rating_csv import trainee_rating_csv
from app.application.statistics.trainee_statistics import (
    GetTraineeStatistics,
    TraineeStatisticsView,
    statistics_row,
)
from app.domain.common.ids import SessionId, UserId
from app.domain.dds.card_status import DEFAULT_CARD_TIMERS
from app.domain.enums import SessionMode
from app.domain.events.types import EventType
from app.domain.session.pass_criteria import DEFAULT_PASS_CRITERIA, PassCriteria, PassCriterion

from tests.unit.application.statistics.test_trainee_rating import INSTRUCTOR, FakeReader

TRAINEE = UserId(UUID(int=1))
OTHER = UserId(UUID(int=2))
DONE = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
STRICT = {"min_score_percent": 90, "max_failed_rules": None, "fail_on_critical": True}
LENIENT = {"min_score_percent": None, "max_failed_rules": 5, "fail_on_critical": False}


def _created(**payload: Any) -> StatisticsEvent:
    return StatisticsEvent(
        event_type=EventType.SESSION_CREATED,
        payload={"role_chain": ["DDS"], **payload},
        monotonic_offset_ms=0,
    )


def _session(
    user_id: UserId,
    points: float,
    *,
    criteria: dict[str, Any] | None,
    failed: int = 0,
    critical: int = 0,
) -> ScoredSession:
    payload = {} if criteria is None else {"pass_criteria": criteria}
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
        total_max_points=100.0,
        failed_by_category={"WORKFLOW": failed} if failed else {},
        failed_rule_count=failed,
        critical_error_count=critical,
        events=(_created(**payload),),
    )


# -- the recorded criteria --------------------------------------------------------------------


def test_the_recorded_criteria_are_read_from_session_created() -> None:
    assert recorded_pass_criteria([_created(pass_criteria=STRICT)]) == PassCriteria(**STRICT)


def test_a_log_without_recorded_criteria_gets_the_defaults() -> None:
    assert recorded_pass_criteria([_created()]) == DEFAULT_PASS_CRITERIA
    assert recorded_pass_criteria([]) == DEFAULT_PASS_CRITERIA


def test_the_same_numbers_pass_or_fail_by_the_recorded_criteria_only() -> None:
    numbers = {
        "total_points": 80.0,
        "total_max_points": 100.0,
        "failed_rule_count": 2,
        "critical_error_count": 0,
    }
    strict = session_pass_verdict([_created(pass_criteria=STRICT)], **numbers)
    lenient = session_pass_verdict([_created(pass_criteria=LENIENT)], **numbers)
    old = session_pass_verdict([_created()], **numbers)
    assert (strict.passed, strict.failed_criteria) == (False, (PassCriterion.MIN_SCORE_PERCENT,))
    assert (lenient.passed, lenient.failed_criteria) == (True, ())
    assert (old.passed, old.criteria) == (True, DEFAULT_PASS_CRITERIA)


# -- statistics and rating --------------------------------------------------------------------


def _sessions() -> list[ScoredSession]:
    return [
        _session(TRAINEE, 95.0, criteria=STRICT),  # сдал
        _session(TRAINEE, 80.0, criteria=STRICT),  # не сдал: below 90 %
        _session(TRAINEE, 10.0, criteria=LENIENT, failed=3, critical=1),  # сдал
        _session(TRAINEE, 75.0, criteria=None, critical=1),  # не сдал: defaults, critical
        _session(OTHER, 99.0, criteria=None),  # сдал (another trainee)
    ]


def test_the_statistics_row_counts_each_session_under_its_own_criteria() -> None:
    mine = [s for s in _sessions() if s.participants[0].user_id == TRAINEE]
    row = statistics_row(TraineeAccount(TRAINEE, "Первый"), mine)
    assert (row.session_count, row.pass_count, row.pass_rate) == (4, 2, 50.0)


def test_a_trainee_without_sessions_has_no_pass_rate() -> None:
    row = statistics_row(TraineeAccount(TRAINEE, "Первый"), [])
    assert (row.pass_count, row.pass_rate) == (0, None)


async def test_the_statistics_csv_carries_the_pass_numbers() -> None:
    view = await GetTraineeStatistics(FakeReader(_sessions()))(StatisticsFilter(), INSTRUCTOR)
    lines = _csv_rows(statistics_csv(view))
    by_id = {line["Идентификатор"]: line for line in lines}
    for row in _rows_with_sessions(view):
        line = by_id[str(row.trainee_user_id)]
        assert int(line["Сдано"]) == row.pass_count
        assert _number(line["Доля сдачи, %"]) == row.pass_rate


async def test_the_rating_carries_the_pass_numbers_and_keeps_its_order() -> None:
    view = await GetTraineeRating(FakeReader(_sessions()))(StatisticsFilter(), INSTRUCTOR)
    # still by average percent: OTHER 99 % before TRAINEE's (95 + 80 + 10 + 75) / 4 = 65 %
    assert [row.trainee_user_id for row in view.rows] == [OTHER, TRAINEE]
    assert [(row.pass_count, row.pass_rate) for row in view.rows] == [(1, 100.0), (2, 50.0)]
    lines = _csv_rows(trainee_rating_csv(view))
    for line, row in zip(lines, view.rows, strict=True):
        assert int(line["Место"]) == row.rank
        assert int(line["Сдано"]) == row.pass_count
        assert _number(line["Доля сдачи, %"]) == row.pass_rate


def _rows_with_sessions(view: TraineeStatisticsView) -> list[Any]:
    return [row for row in view.rows if row.session_count]


def _csv_rows(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))


def _number(cell: str) -> float | None:
    return None if cell == "" else float(cell.replace(",", "."))
