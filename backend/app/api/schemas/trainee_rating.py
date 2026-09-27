"""`TraineeRating` (I5 E36, Q-E12-2) — `getTraineeRating`'s wire schema.

Property names copied literally from `docs/hld/openapi.yaml` (`TraineeRatingRow`,
`TraineeRating`). The mapping function is the only bridge to the application view.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.statistics.trainee_rating import TraineeRatingView

__all__ = ["TraineeRatingRowSchema", "TraineeRatingSchema", "trainee_rating_schema"]


class TraineeRatingRowSchema(ApiModel):
    """`TraineeRatingRow`: one ranked trainee."""

    rank: int = Field(ge=1)
    trainee_user_id: UUID
    display_name_ru: str
    average_percent: float = Field(ge=0, le=100)


class TraineeRatingSchema(ApiModel):
    """`TraineeRating`: `getTraineeRating`."""

    rows: list[TraineeRatingRowSchema]


def trainee_rating_schema(view: TraineeRatingView) -> TraineeRatingSchema:
    return TraineeRatingSchema(
        rows=[
            TraineeRatingRowSchema(
                rank=row.rank,
                trainee_user_id=UUID(str(row.trainee_user_id)),
                display_name_ru=row.display_name_ru,
                average_percent=row.average_percent,
            )
            for row in view.rows
        ]
    )
