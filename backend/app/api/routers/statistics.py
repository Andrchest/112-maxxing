"""`statistics` router — `getTraineeStatistics`, `getTraineeStatisticsCsv`, `getMyHistory`
(I4 E33, HLD 71 §71.10) and `getTraineeRating` / `getTraineeRatingCsv` (I5 E36, Q-E12-2).

Every number is read from stored rows (D11). INSTRUCTOR / ADMIN see every trainee; a TRAINEE sees
themselves only (another `trainee_id` is `403 FORBIDDEN_FOR_ROLE`). The rating is INSTRUCTOR /
ADMIN only. Each CSV is its JSON's own view rendered as a file.

(I7 E46b, owner item 6) Both `.csv` endpoints also answer `?format=xlsx|pdf` — same view, same
filters, same auth, `format=csv` (the default) byte-identical to before this epic.

(I7 E54, G11) `getTypicalErrors` reuses the same filter — INSTRUCTOR / ADMIN only, an INSTRUCTOR's
own scope narrowed to lessons they created (`GetTypicalErrors`'s own reading), an ADMIN's not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import ContainerDep
from app.api.export_headers import content_disposition
from app.api.schemas.statistics import (
    MyHistorySchema,
    TraineeStatisticsSchema,
    my_history_schema,
    trainee_statistics_schema,
)
from app.api.schemas.statistics_charts import StatisticsChartsSchema, statistics_charts_schema
from app.api.schemas.trainee_rating import TraineeRatingSchema, trainee_rating_schema
from app.api.schemas.typical_errors import TypicalErrorsSchema, typical_errors_schema
from app.api.security import CurrentUserDep
from app.application.ports.report_exporter import (
    PDF_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    generated_at_moscow,
)
from app.application.reports.csv_export import CSV_MEDIA_TYPE
from app.application.statistics.ports import StatisticsFilter
from app.application.statistics.statistics_csv import statistics_csv
from app.application.statistics.statistics_export import statistics_export_document
from app.application.statistics.trainee_rating_csv import trainee_rating_csv
from app.application.statistics.trainee_rating_export import trainee_rating_export_document
from app.domain.common.ids import TraineeGroupId, UserId

router = APIRouter(prefix="/api/v1", tags=["statistics"])

TraineeIdQuery = Annotated[UUID | None, Query()]
GroupIdQuery = Annotated[UUID | None, Query()]
FromQuery = Annotated[datetime | None, Query(alias="from", description="Inclusive (UTC).")]
ToQuery = Annotated[datetime | None, Query(alias="to", description="Exclusive (UTC).")]
ExportFormatQuery = Annotated[
    Literal["csv", "xlsx", "pdf"], Query(description="I7 E46b: `csv` (default), `xlsx` or `pdf`.")
]


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


def _filters_line(query: StatisticsFilter) -> str:
    """(I7 E46b) The applied filters as one line of Russian text, for the Excel/PDF exports."""
    parts: list[str] = []
    if query.trainee_id is not None:
        parts.append(f"Обучаемый: {query.trainee_id}")
    if query.group_id is not None:
        parts.append(f"Группа: {query.group_id}")
    if query.from_utc is not None:
        parts.append(f"С: {query.from_utc.isoformat()}")
    if query.to_utc is not None:
        parts.append(f"По: {query.to_utc.isoformat()}")
    return "; ".join(parts)


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
    summary="getTraineeStatistics as CSV, Excel or PDF (`?format=`, same access, same numbers).",
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
    format: ExportFormatQuery = "csv",
) -> Response:
    query = _filter(trainee_id, group_id, from_utc, to_utc)
    view = await container.get_trainee_statistics()(query, user)
    if format == "csv":
        return Response(
            content=statistics_csv(view),
            media_type=CSV_MEDIA_TYPE,
            headers={"Content-Disposition": 'attachment; filename="statistics.csv"'},
        )
    document = statistics_export_document(
        view, filters_line=_filters_line(query), generated_at=generated_at_moscow(container.clock)
    )
    if format == "xlsx":
        return Response(
            content=container.report_exporter.render_xlsx(document),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition("Статистика.xlsx", "statistics.xlsx")
            },
        )
    return Response(
        content=container.report_exporter.render_pdf(document),
        media_type=PDF_MEDIA_TYPE,
        headers={"Content-Disposition": content_disposition("Статистика.pdf", "statistics.pdf")},
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
    summary="getTraineeRating as CSV, Excel or PDF (`?format=`, same access, same numbers).",
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
    format: ExportFormatQuery = "csv",
) -> Response:
    query = _filter(trainee_id, group_id, from_utc, to_utc)
    view = await container.get_trainee_rating()(query, user)
    if format == "csv":
        return Response(
            content=trainee_rating_csv(view),
            media_type=CSV_MEDIA_TYPE,
            headers={"Content-Disposition": 'attachment; filename="trainee-rating.csv"'},
        )
    document = trainee_rating_export_document(
        view, filters_line=_filters_line(query), generated_at=generated_at_moscow(container.clock)
    )
    if format == "xlsx":
        return Response(
            content=container.report_exporter.render_xlsx(document),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition("Рейтинг.xlsx", "trainee-rating.xlsx")
            },
        )
    return Response(
        content=container.report_exporter.render_pdf(document),
        media_type=PDF_MEDIA_TYPE,
        headers={"Content-Disposition": content_disposition("Рейтинг.pdf", "trainee-rating.pdf")},
    )


# --- I7 E54: «Типичные ошибки» (G11, ТЗ ¶233) ------------------------------------------------


@router.get(
    "/statistics/typical-errors",
    operation_id="getTypicalErrors",
    summary="(I7 E54) Top failed rules in scope (INSTRUCTOR/ADMIN; own lessons for an INSTRUCTOR).",
    response_model=TypicalErrorsSchema,
    status_code=200,
)
async def get_typical_errors(
    container: ContainerDep,
    user: CurrentUserDep,
    trainee_id: TraineeIdQuery = None,
    group_id: GroupIdQuery = None,
    from_utc: FromQuery = None,
    to_utc: ToQuery = None,
) -> TypicalErrorsSchema:
    view = await container.get_typical_errors()(
        _filter(trainee_id, group_id, from_utc, to_utc), user
    )
    return typical_errors_schema(view)


# --- I7 E46a: charts — «Средний балл по занятиям», «Ошибки по критериям» (owner item 6) --------


@router.get(
    "/statistics/charts",
    operation_id="getStatisticsCharts",
    summary="(I7 E46a) Score timeline and error heatmap (INSTRUCTOR/ADMIN; own lessons for an "
    "INSTRUCTOR).",
    response_model=StatisticsChartsSchema,
    status_code=200,
)
async def get_statistics_charts(
    container: ContainerDep,
    user: CurrentUserDep,
    trainee_id: TraineeIdQuery = None,
    group_id: GroupIdQuery = None,
    from_utc: FromQuery = None,
    to_utc: ToQuery = None,
) -> StatisticsChartsSchema:
    view = await container.get_statistics_charts()(
        _filter(trainee_id, group_id, from_utc, to_utc), user
    )
    return statistics_charts_schema(view)
