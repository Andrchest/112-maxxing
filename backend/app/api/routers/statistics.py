"""`statistics` router — `getTraineeStatistics`, `getTraineeStatisticsCsv`, `getMyHistory`
(I4 E33, HLD 71 §71.10) and `getTraineeRating` / `getTraineeRatingCsv` (I5 E36, Q-E12-2).

Every number is read from stored rows (D11). INSTRUCTOR / ADMIN see every trainee; a TRAINEE sees
themselves only (another `trainee_id` is `403 FORBIDDEN_FOR_ROLE`). The rating is INSTRUCTOR /
ADMIN only. Each CSV is its JSON's own view rendered as a file.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import ContainerDep
from app.api.schemas.statistics import (
    MyHistorySchema,
    TraineeStatisticsSchema,
    my_history_schema,
    trainee_statistics_schema,
)
from app.api.schemas.trainee_rating import TraineeRatingSchema, trainee_rating_schema
from app.api.security import CurrentUserDep
from app.application.reports.csv_export import CSV_MEDIA_TYPE
from app.application.statistics.ports import StatisticsFilter
from app.application.statistics.statistics_csv import statistics_csv
from app.application.statistics.trainee_rating_csv import trainee_rating_csv
from app.domain.common.ids import TraineeGroupId, UserId

router = APIRouter(prefix="/api/v1", tags=["statistics"])

TraineeIdQuery = Annotated[UUID | None, Query()]
GroupIdQuery = Annotated[UUID | None, Query()]
FromQuery = Annotated[datetime | None, Query(alias="from", description="Inclusive (UTC).")]
ToQuery = Annotated[datetime | None, Query(alias="to", description="Exclusive (UTC).")]


def _filter(
    trainee_id: UUID | None,
    group_id: UUID | None,
    from_utc: datetime | None,
    to_utc: datetime | None,
) -> StatisticsFilter:
    return StatisticsFilter(
        trainee_id=None if trainee_id is None else UserId(trainee_id),
        group_id=None if group_id is None else TraineeGroupId(group_id),
        from_utc=from_utc,
        to_utc=to_utc,
    )


@router.get(
    "/statistics",
    operation_id="getTraineeStatistics",
    summary="Per-trainee statistics across sessions and lessons.",
    response_model=TraineeStatisticsSchema,
    status_code=200,
)
async def get_trainee_statistics(
    container: ContainerDep,
    user: CurrentUserDep,
    trainee_id: TraineeIdQuery = None,
    group_id: GroupIdQuery = None,
    from_utc: FromQuery = None,
    to_utc: ToQuery = None,
) -> TraineeStatisticsSchema:
    view = await container.get_trainee_statistics()(
        _filter(trainee_id, group_id, from_utc, to_utc), user
    )
    return trainee_statistics_schema(view)


@router.get(
    "/statistics.csv",
    operation_id="getTraineeStatisticsCsv",
    summary="getTraineeStatistics as CSV (same access, same numbers).",
    status_code=200,
    response_class=Response,
)
async def get_trainee_statistics_csv(
    container: ContainerDep,
    user: CurrentUserDep,
    trainee_id: TraineeIdQuery = None,
    group_id: GroupIdQuery = None,
    from_utc: FromQuery = None,
    to_utc: ToQuery = None,
) -> Response:
    view = await container.get_trainee_statistics()(
        _filter(trainee_id, group_id, from_utc, to_utc), user
    )
    return Response(
        content=statistics_csv(view),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="statistics.csv"'},
    )


@router.get(
    "/me/history",
    operation_id="getMyHistory",
    summary="The caller's own statistics plus their completed sessions with score and date.",
    response_model=MyHistorySchema,
    status_code=200,
)
async def get_my_history(container: ContainerDep, user: CurrentUserDep) -> MyHistorySchema:
    return my_history_schema(await container.get_my_history()(user))


@router.get(
    "/statistics/rating",
    operation_id="getTraineeRating",
    summary="(I5 E36) Trainees ranked by their average score percent (INSTRUCTOR / ADMIN).",
    response_model=TraineeRatingSchema,
    status_code=200,
)
async def get_trainee_rating(
    container: ContainerDep,
    user: CurrentUserDep,
    trainee_id: TraineeIdQuery = None,
    group_id: GroupIdQuery = None,
    from_utc: FromQuery = None,
    to_utc: ToQuery = None,
) -> TraineeRatingSchema:
    view = await container.get_trainee_rating()(
        _filter(trainee_id, group_id, from_utc, to_utc), user
    )
    return trainee_rating_schema(view)


@router.get(
    "/statistics/rating.csv",
    operation_id="getTraineeRatingCsv",
    summary="getTraineeRating as CSV (same access, same numbers).",
    status_code=200,
    response_class=Response,
)
async def get_trainee_rating_csv(
    container: ContainerDep,
    user: CurrentUserDep,
    trainee_id: TraineeIdQuery = None,
    group_id: GroupIdQuery = None,
    from_utc: FromQuery = None,
    to_utc: ToQuery = None,
) -> Response:
    view = await container.get_trainee_rating()(
        _filter(trainee_id, group_id, from_utc, to_utc), user
    )
    return Response(
        content=trainee_rating_csv(view),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="trainee-rating.csv"'},
    )
