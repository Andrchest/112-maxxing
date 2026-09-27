"""`getTraineeRating` (and its CSV) — trainees ranked by their average score percent (I5 E36,
Q-E12-2; ТЗ §07-qna: «кто в лидерах обучающихся, кто двоечник»).

**Read, never re-scored (D11).** The row per trainee is exactly `trainee_statistics.statistics_row`
— the same aggregate `getTraineeStatistics` shows — over the same filters that page already has
(`StatisticsFilter`: one trainee, one group, a `completed_at` window). Unscored/aborted cards are
already excluded there (`StatisticsReader.scored_sessions` reads only `COMPLETED` sessions with
stored results; an `ABORTED` card is never scored, SPEC §28) — the same rule the lesson report's
weighted sum applies, so the rating agrees with the report on which cards count.

**The ranking (Q-E12-2's answer: sort by the mean score percent).** Trainees with no qualifying
session (`average_percent is None`) have nothing to rank and are left out, never given a rank —
"кто в лидерах, кто двоечник" answers for trainees who have done something. Sorted by
`average_percent` descending, ties broken by `display_name_ru` (then `trainee_user_id` for a
name collision) — ranks are the plain sequence `1..N`, not a competition rank (a tie is still two
different numbers). A negative total already reads 0 % (`session_percent`'s clamp, Q-E33-1) before
it ever reaches this module.

**Who sees it.** INSTRUCTOR / ADMIN only (`403 FORBIDDEN_FOR_ROLE` for a TRAINEE) — the rating is
an instructor's view of the whole class, never a trainee's own.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.statistics.ports import StatisticsFilter, StatisticsReader
from app.application.statistics.trainee_statistics import (
    StatisticsSubjectNotFoundError,
    TraineeStatisticsRowView,
    statistics_row,
    took_part,
)
from app.domain.common.ids import UserId

__all__ = ["GetTraineeRating", "TraineeRatingRowView", "TraineeRatingView"]


@dataclass(frozen=True, slots=True)
class TraineeRatingRowView:
    """One ranked trainee: `TraineeRatingRow`."""

    rank: int
    trainee_user_id: UserId
    display_name_ru: str
    average_percent: float


@dataclass(frozen=True, slots=True)
class TraineeRatingView:
    """`TraineeRating`."""

    rows: tuple[TraineeRatingRowView, ...]


class GetTraineeRating:
    """`getTraineeRating` (and, rendered, `getTraineeRatingCsv`) — INSTRUCTOR / ADMIN only."""

    def __init__(self, reader: StatisticsReader) -> None:
        self._reader = reader

    async def __call__(self, query: StatisticsFilter, user: AuthenticatedUser) -> TraineeRatingView:
        if not user.is_instructor_or_admin:
            raise ForbiddenForRoleError("the trainee rating is INSTRUCTOR / ADMIN only")
        if query.group_id is not None and not await self._reader.group_exists(query.group_id):
            raise StatisticsSubjectNotFoundError(f"no trainee group {query.group_id}")
        trainees = await self._reader.trainees(query)
        if query.trainee_id is not None and not trainees:
            raise StatisticsSubjectNotFoundError(f"no trainee account {query.trainee_id}")
        sessions = await self._reader.scored_sessions(
            [trainee.user_id for trainee in trainees],
            from_utc=query.from_utc,
            to_utc=query.to_utc,
        )
        rows = [
            statistics_row(
                trainee, [session for session in sessions if took_part(session, trainee.user_id)]
            )
            for trainee in trainees
        ]
        return TraineeRatingView(rows=_ranked(rows))


def _ranked(rows: list[TraineeStatisticsRowView]) -> tuple[TraineeRatingRowView, ...]:
    """Sorted by `average_percent` desc, ties by name; a trainee with none is left out."""
    scored: list[tuple[TraineeStatisticsRowView, float]] = [
        (row, row.average_percent) for row in rows if row.average_percent is not None
    ]
    ordered = sorted(
        scored,
        key=lambda pair: (-pair[1], pair[0].display_name_ru, str(pair[0].trainee_user_id)),
    )
    return tuple(
        TraineeRatingRowView(
            rank=index + 1,
            trainee_user_id=row.trainee_user_id,
            display_name_ru=row.display_name_ru,
            average_percent=percent,
        )
        for index, (row, percent) in enumerate(ordered)
    )
