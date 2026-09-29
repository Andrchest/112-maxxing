"""`getTraineeRating` as an `ExportDocument` (I7 E46b) — the Excel/PDF twin of
`trainee_rating_csv`, same rows, same columns (`TRAINEE_RATING_CSV_HEADER`)."""

from __future__ import annotations

from datetime import datetime

from app.application.ports.report_exporter import ExportDocument, ExportTable
from app.application.statistics.trainee_rating import TraineeRatingView
from app.application.statistics.trainee_rating_csv import TRAINEE_RATING_CSV_HEADER

__all__ = ["trainee_rating_export_document"]


def trainee_rating_export_document(
    view: TraineeRatingView, *, filters_line: str, generated_at: datetime
) -> ExportDocument:
    rows = [
        [
            row.rank,
            row.display_name_ru,
            str(row.trainee_user_id),
            row.average_percent,
            row.pass_count,
            row.pass_rate,
        ]
        for row in view.rows
    ]
    return ExportDocument(
        title="Рейтинг обучаемых",
        filters_line=filters_line,
        generated_at=generated_at,
        tables=[ExportTable(title="Рейтинг", header=TRAINEE_RATING_CSV_HEADER, rows=rows)],
    )
