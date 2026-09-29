"""`TypicalErrors` (I7 E54, G11) — `getTypicalErrors`'s wire schema, and `getLessonReport`'s own
`typical_errors` field (`app.api.schemas.lessons.LessonReportSchema`).

Property names copied literally from `docs/hld/openapi.yaml` (`TypicalErrorRow`, `TypicalErrors`).
"""

from __future__ import annotations

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.statistics.typical_errors import TypicalErrorRowView, TypicalErrorsView
from app.domain.enums import ScoringCategory

__all__ = [
    "TypicalErrorRowSchema",
    "TypicalErrorsSchema",
    "typical_error_row_schema",
    "typical_errors_schema",
]


class TypicalErrorRowSchema(ApiModel):
    """`TypicalErrorRow`: one rule, worst (most failed sessions) first."""

    rule_id: str
    name_ru: str
    category: ScoringCategory
    failed_session_count: int = Field(ge=0)
    session_count: int = Field(ge=0)
    share_percent: float = Field(ge=0, le=100)


class TypicalErrorsSchema(ApiModel):
    """`TypicalErrors`: `getTypicalErrors`, and `LessonReport.typical_errors`."""

    rows: list[TypicalErrorRowSchema]


def typical_error_row_schema(row: TypicalErrorRowView) -> TypicalErrorRowSchema:
    return TypicalErrorRowSchema(
        rule_id=row.rule_id,
        name_ru=row.name_ru,
        category=row.category,
        failed_session_count=row.failed_session_count,
        session_count=row.session_count,
        share_percent=row.share_percent,
    )


def typical_errors_schema(view: TypicalErrorsView) -> TypicalErrorsSchema:
    return TypicalErrorsSchema(rows=[typical_error_row_schema(row) for row in view.rows])
