"""`StatisticsCharts` (I7 E46a) — `getStatisticsCharts`'s wire schema.

Property names copied literally from `docs/hld/openapi.yaml` (`ScoreTimelinePoint`,
`ScoreTimeline`, `ErrorHeatmapCell`, `ErrorHeatmapRow`, `ErrorHeatmap`, `StatisticsCharts`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.statistics.statistics_charts import (
    ErrorHeatmapCellView,
    ErrorHeatmapRowView,
    ErrorHeatmapView,
    ScoreTimelinePointView,
    ScoreTimelineView,
    StatisticsChartsView,
)
from app.domain.enums import ScoringCategory

__all__ = [
    "ErrorHeatmapCellSchema",
    "ErrorHeatmapRowSchema",
    "ErrorHeatmapSchema",
    "ScoreTimelinePointSchema",
    "ScoreTimelineSchema",
    "StatisticsChartsSchema",
    "statistics_charts_schema",
]


class ScoreTimelinePointSchema(ApiModel):
    """`ScoreTimelinePoint`: one scored session in scope."""

    at: datetime
    score_percent: float = Field(ge=0, le=100)


class ScoreTimelineSchema(ApiModel):
    """`ScoreTimeline`: `getStatisticsCharts`'s «Средний балл по занятиям», oldest first."""

    points: list[ScoreTimelinePointSchema]


class ErrorHeatmapCellSchema(ApiModel):
    """`ErrorHeatmapCell`: one trainee's share of failed checks in one category."""

    category: ScoringCategory
    share_percent: float | None = Field(ge=0, le=100)


class ErrorHeatmapRowSchema(ApiModel):
    """`ErrorHeatmapRow`: one trainee, `cells` in `ErrorHeatmap.categories`' own order."""

    trainee_user_id: UUID
    display_name_ru: str
    cells: list[ErrorHeatmapCellSchema]


class ErrorHeatmapSchema(ApiModel):
    """`ErrorHeatmap`: `getStatisticsCharts`'s «Ошибки по критериям»."""

    categories: list[ScoringCategory]
    rows: list[ErrorHeatmapRowSchema]


class StatisticsChartsSchema(ApiModel):
    """`StatisticsCharts`: `getStatisticsCharts`."""

    score_timeline: ScoreTimelineSchema
    error_heatmap: ErrorHeatmapSchema


def _score_timeline_point_schema(point: ScoreTimelinePointView) -> ScoreTimelinePointSchema:
    return ScoreTimelinePointSchema(at=point.at, score_percent=point.score_percent)


def _score_timeline_schema(view: ScoreTimelineView) -> ScoreTimelineSchema:
    return ScoreTimelineSchema(
        points=[_score_timeline_point_schema(point) for point in view.points]
    )


def _error_heatmap_cell_schema(cell: ErrorHeatmapCellView) -> ErrorHeatmapCellSchema:
    return ErrorHeatmapCellSchema(category=cell.category, share_percent=cell.share_percent)


def _error_heatmap_row_schema(row: ErrorHeatmapRowView) -> ErrorHeatmapRowSchema:
    return ErrorHeatmapRowSchema(
        trainee_user_id=UUID(str(row.trainee_user_id)),
        display_name_ru=row.display_name_ru,
        cells=[_error_heatmap_cell_schema(cell) for cell in row.cells],
    )


def _error_heatmap_schema(view: ErrorHeatmapView) -> ErrorHeatmapSchema:
    return ErrorHeatmapSchema(
        categories=list(view.categories),
        rows=[_error_heatmap_row_schema(row) for row in view.rows],
    )


def statistics_charts_schema(view: StatisticsChartsView) -> StatisticsChartsSchema:
    return StatisticsChartsSchema(
        score_timeline=_score_timeline_schema(view.score_timeline),
        error_heatmap=_error_heatmap_schema(view.error_heatmap),
    )
