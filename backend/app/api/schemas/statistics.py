"""`statistics` schemas and the lesson report's `NormView` (I4 E33, HLD 71 §71.10; I5 E36).

Property names copied literally from `docs/hld/openapi.yaml` (`NormView`, `LegReactionTimeView`,
`TraineeStatisticsRow`, `TraineeStatistics`, `MyHistorySession`, `MyHistory`). The mapping
functions are the only bridge between the application views and the wire.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.reports.norms import CardNorm, LegReactionTime
from app.application.statistics.trainee_statistics import (
    MyHistoryView,
    TraineeStatisticsRowView,
    TraineeStatisticsView,
)

__all__ = [
    "LegReactionTimeViewSchema",
    "MyHistorySchema",
    "MyHistorySessionSchema",
    "NormViewSchema",
    "TraineeStatisticsRowSchema",
    "TraineeStatisticsSchema",
    "leg_reaction_time_schema",
    "my_history_schema",
    "norm_view_schema",
    "trainee_statistics_schema",
]


class NormViewSchema(ApiModel):
    """`NormView`: one measured interval against the session's recorded timer."""

    kind: Literal["ACCEPT", "FILL", "DDS_FILL"]
    service_id: str | None
    measured_ms: int | None = Field(ge=0)
    norm_ms: int = Field(ge=0)
    deviation_ms: int | None


class LegReactionTimeViewSchema(ApiModel):
    """(I5 E36, Q-E12-1) `LegReactionTimeView`: a leg's two reaction times, no norm."""

    service_id: str | None
    to_open_ms: int | None = Field(ge=0)
    to_first_status_ms: int | None = Field(ge=0)


class TraineeStatisticsRowSchema(ApiModel):
    """`TraineeStatisticsRow`."""

    trainee_user_id: UUID
    display_name_ru: str
    session_count: int = Field(ge=0)
    lesson_count: int = Field(ge=0)
    average_percent: float | None = Field(ge=0, le=100)
    failed_rules_by_category: dict[str, int]
    accept_deviation_ms_avg: float | None
    fill_deviation_ms_avg: float | None
    reaction_to_open_ms_avg: float | None
    """(I5 E36, Q-E12-1) The mean of delivery → `DDS_CARD_OPENED` over the legs this trainee
    played."""
    reaction_to_status_ms_avg: float | None
    """(I5 E36, Q-E12-1) The mean of delivery → the leg's first primary decision."""
    pass_count: int = Field(ge=0)
    """(I5 E38, Q-E9b-3) The sessions whose «сдал / не сдал» verdict is «сдал»."""
    pass_rate: float | None = Field(ge=0, le=100)
    """(I5 E38) `100 · pass_count / session_count`; `null` without a session."""


class TraineeStatisticsSchema(ApiModel):
    """`TraineeStatistics`."""

    rows: list[TraineeStatisticsRowSchema]


class MyHistorySessionSchema(ApiModel):
    """`MyHistorySession`."""

    session_id: UUID
    lesson_id: UUID | None
    scenario_title_ru: str
    completed_at: datetime
    score_percent: float | None = Field(ge=0, le=100)
    failed_rule_count: int | None = Field(ge=0)
    passed: bool | None = None
    """ADDITIVE (I7 E50, ТЗ ¶265): «сдал / не сдал»; `null` until the report is visible."""
    reaction_open_ms: int | None = Field(default=None, ge=0)
    """ADDITIVE (I7 E50): delivery → first `DDS_CARD_OPENED` of the caller's own leg(s)."""
    reaction_first_status_ms: int | None = Field(default=None, ge=0)
    """ADDITIVE (I7 E50): delivery → the caller's own leg(s)' first primary decision."""
    text_quality_issue_count: int | None = Field(default=None, ge=0)
    """ADDITIVE (I7 E50): «Грамотность и адреса» flagged-item count; `null` when the checker is
    unavailable or the report is not visible yet."""


class MyHistorySchema(ApiModel):
    """`MyHistory`."""

    statistics: TraineeStatisticsRowSchema
    sessions: list[MyHistorySessionSchema]


def norm_view_schema(norm: CardNorm) -> NormViewSchema:
    return NormViewSchema(
        kind=norm.kind.value,
        service_id=norm.service_id,
        measured_ms=norm.measured_ms,
        norm_ms=norm.norm_ms,
        deviation_ms=norm.deviation_ms,
    )


def leg_reaction_time_schema(reaction: LegReactionTime) -> LegReactionTimeViewSchema:
    return LegReactionTimeViewSchema(
        service_id=reaction.service_id,
        to_open_ms=reaction.to_open_ms,
        to_first_status_ms=reaction.to_first_status_ms,
    )


def trainee_statistics_row_schema(row: TraineeStatisticsRowView) -> TraineeStatisticsRowSchema:
    return TraineeStatisticsRowSchema(
        trainee_user_id=UUID(str(row.trainee_user_id)),
        display_name_ru=row.display_name_ru,
        session_count=row.session_count,
        lesson_count=row.lesson_count,
        average_percent=row.average_percent,
        failed_rules_by_category=dict(row.failed_rules_by_category),
        accept_deviation_ms_avg=row.accept_deviation_ms_avg,
        fill_deviation_ms_avg=row.fill_deviation_ms_avg,
        reaction_to_open_ms_avg=row.reaction_to_open_ms_avg,
        reaction_to_status_ms_avg=row.reaction_to_status_ms_avg,
        pass_count=row.pass_count,
        pass_rate=row.pass_rate,
    )


def trainee_statistics_schema(view: TraineeStatisticsView) -> TraineeStatisticsSchema:
    return TraineeStatisticsSchema(rows=[trainee_statistics_row_schema(row) for row in view.rows])


def my_history_schema(view: MyHistoryView) -> MyHistorySchema:
    return MyHistorySchema(
        statistics=trainee_statistics_row_schema(view.statistics),
        sessions=[
            MyHistorySessionSchema(
                session_id=UUID(str(session.session_id)),
                lesson_id=None if session.lesson_id is None else UUID(str(session.lesson_id)),
                scenario_title_ru=session.scenario_title_ru,
                completed_at=session.completed_at,
                score_percent=session.score_percent,
                failed_rule_count=session.failed_rule_count,
                passed=session.passed,
                reaction_open_ms=session.reaction_open_ms,
                reaction_first_status_ms=session.reaction_first_status_ms,
                text_quality_issue_count=session.text_quality_issue_count,
            )
            for session in view.sessions
        ],
    )
