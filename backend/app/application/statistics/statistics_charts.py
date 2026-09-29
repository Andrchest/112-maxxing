"""`getStatisticsCharts` (I7 E46a, owner item 6: «простые бонусы без ML») — the two analytic
charts on the instructor statistics page that need server-side aggregation:

* `score_timeline` — «Средний балл по занятиям»: one point per scored session in scope, oldest
  first, its own `session_percent` (the same clamp `getTraineeStatistics` uses). Filtering to one
  `trainee_id` plots that trainee's own sessions; a `group_id` (or no filter) plots every distinct
  scored session the scope's trainees took part in — the bar chart on the same page needs no
  backend change (it buckets `TraineeStatistics.rows[].average_percent`, already on the page).
* `error_heatmap` — «Ошибки по критериям»: one row per trainee in scope × every `ScoringCategory`,
  each cell the share (0…100 %, `None` without a `score_results` row in that category) of that
  trainee's checks in that category that failed.

**Deterministic, no ML, D11.** Both are folds over stored `score_results` — no evaluator runs and
no score moves.

**Scope.** Same filter as `getTraineeStatistics` (`StatisticsFilter`: one trainee, one group, a
`completed_at` window). Ownership like `getTypicalErrors` (I7 E54, G11) — the brief's own wording
for this endpoint: an INSTRUCTOR's scope is their own lessons' sessions only, an ADMIN's is every
scored session. A TRAINEE gets `403 FORBIDDEN_FOR_ROLE`: these are instructor-facing analytics,
unlike the trainee's own `/history` line chart (`getMyHistory`, untouched by this epic).

**Crew-attributed, like `failed_rules_by_category`.** `score_results` carries no per-participant
assignment, so a session's rows count for every trainee who took part in it — the same reading
`TraineeStatisticsRow.failed_rules_by_category` already established (I4 E33).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.statistics.ports import (
    ErrorHeatmapCellRow,
    StatisticsFilter,
    StatisticsReader,
    TraineeAccount,
)
from app.application.statistics.trainee_statistics import StatisticsSubjectNotFoundError
from app.domain.common.ids import SessionId, UserId
from app.domain.enums import ScoringCategory
from app.domain.session.pass_criteria import score_percent

__all__ = [
    "ErrorHeatmapCellView",
    "ErrorHeatmapRowView",
    "ErrorHeatmapView",
    "GetStatisticsCharts",
    "ScoreTimelinePointView",
    "ScoreTimelineView",
    "StatisticsChartsView",
]

_CATEGORIES: tuple[ScoringCategory, ...] = tuple(ScoringCategory)


@dataclass(frozen=True, slots=True)
class ScoreTimelinePointView:
    """One scored session in scope, its own `session_percent`."""

    at: datetime
    score_percent: float


@dataclass(frozen=True, slots=True)
class ScoreTimelineView:
    """`score_timeline` — oldest first."""

    points: tuple[ScoreTimelinePointView, ...]


@dataclass(frozen=True, slots=True)
class ErrorHeatmapCellView:
    """One `(trainee, category)` cell: `None` without a `score_results` row in scope."""

    category: ScoringCategory
    share_percent: float | None


@dataclass(frozen=True, slots=True)
class ErrorHeatmapRowView:
    """One trainee's row — `cells` is `ErrorHeatmapView.categories`' own order."""

    trainee_user_id: UserId
    display_name_ru: str
    cells: tuple[ErrorHeatmapCellView, ...]


@dataclass(frozen=True, slots=True)
class ErrorHeatmapView:
    """`error_heatmap` — one row per trainee in scope (module doc; the same trainees
    `getTraineeStatistics` would list for this filter, including a trainee with no session in
    scope: an all-`None` row, exactly like that endpoint's zero-session row)."""

    categories: tuple[ScoringCategory, ...]
    rows: tuple[ErrorHeatmapRowView, ...]


@dataclass(frozen=True, slots=True)
class StatisticsChartsView:
    """`StatisticsCharts`."""

    score_timeline: ScoreTimelineView
    error_heatmap: ErrorHeatmapView


class GetStatisticsCharts:
    """`getStatisticsCharts` — INSTRUCTOR / ADMIN only, same reader as the rest of E33/E36/E54."""

    def __init__(self, reader: StatisticsReader) -> None:
        self._reader = reader

    async def __call__(
        self, query: StatisticsFilter, user: AuthenticatedUser
    ) -> StatisticsChartsView:
        if not user.is_instructor_or_admin:
            raise ForbiddenForRoleError("statistics charts is INSTRUCTOR / ADMIN only")
        if query.group_id is not None and not await self._reader.group_exists(query.group_id):
            raise StatisticsSubjectNotFoundError(f"no trainee group {query.group_id}")
        trainees = await self._reader.trainees(query)
        if query.trainee_id is not None and not trainees:
            raise StatisticsSubjectNotFoundError(f"no trainee account {query.trainee_id}")
        owner_id = None if user.user_role is UserRole.ADMIN else user.user_id
        session_ids = await self._reader.scoped_session_ids(
            user_ids=[trainee.user_id for trainee in trainees],
            owner_id=owner_id,
            from_utc=query.from_utc,
            to_utc=query.to_utc,
        )
        return StatisticsChartsView(
            score_timeline=await self._score_timeline(session_ids),
            error_heatmap=await self._error_heatmap(trainees, session_ids),
        )

    async def _score_timeline(self, session_ids: Sequence[SessionId]) -> ScoreTimelineView:
        if not session_ids:
            return ScoreTimelineView(points=())
        rows = await self._reader.score_timeline(session_ids)
        points: list[ScoreTimelinePointView] = []
        for row in rows:
            percent = score_percent(row.total_points, row.total_max_points)
            if percent is not None:
                points.append(ScoreTimelinePointView(at=row.completed_at, score_percent=percent))
        return ScoreTimelineView(points=tuple(points))

    async def _error_heatmap(
        self, trainees: Sequence[TraineeAccount], session_ids: Sequence[SessionId]
    ) -> ErrorHeatmapView:
        cells_by_trainee: dict[UserId, dict[ScoringCategory, ErrorHeatmapCellRow]] = {}
        if session_ids and trainees:
            rows = await self._reader.error_heatmap_cells(
                session_ids, [trainee.user_id for trainee in trainees]
            )
            for row in rows:
                cells_by_trainee.setdefault(row.user_id, {})[ScoringCategory(row.category)] = row
        rows_view = tuple(
            ErrorHeatmapRowView(
                trainee_user_id=trainee.user_id,
                display_name_ru=trainee.display_name_ru,
                cells=tuple(
                    ErrorHeatmapCellView(
                        category=category,
                        share_percent=_share(
                            cells_by_trainee.get(trainee.user_id, {}).get(category)
                        ),
                    )
                    for category in _CATEGORIES
                ),
            )
            for trainee in trainees
        )
        return ErrorHeatmapView(categories=_CATEGORIES, rows=rows_view)


def _share(cell: ErrorHeatmapCellRow | None) -> float | None:
    if cell is None or cell.total_count == 0:
        return None
    return 100.0 * cell.failed_count / cell.total_count
