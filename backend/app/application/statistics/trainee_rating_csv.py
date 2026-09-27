"""`getTraineeRatingCsv` — `getTraineeRating`'s rows as a file (I5 E36, Q-E12-2).

The same view, the same numbers, `reports.csv_export`'s format (UTF-8 with BOM, `;`, Russian
headers, decimal comma) — `render_csv` and `csv_number`, exactly like `statistics_csv`. (I5 E38,
Q-E9b-3) «Сдано» / «Доля сдачи, %» are the additional columns; the order is the rating's own.
"""

from __future__ import annotations

from app.application.reports.csv_export import csv_number, render_csv
from app.application.statistics.trainee_rating import TraineeRatingView

__all__ = ["TRAINEE_RATING_CSV_HEADER", "trainee_rating_csv"]

TRAINEE_RATING_CSV_HEADER: tuple[str, ...] = (
    "Место",
    "Обучаемый",
    "Идентификатор",
    "Средний процент",
    "Сдано",
    "Доля сдачи, %",
)


def trainee_rating_csv(view: TraineeRatingView) -> bytes:
    """One line per row of `view`, in its rank order."""
    return render_csv(
        TRAINEE_RATING_CSV_HEADER,
        (
            [
                str(row.rank),
                row.display_name_ru,
                str(row.trainee_user_id),
                csv_number(row.average_percent),
                str(row.pass_count),
                csv_number(row.pass_rate),
            ]
            for row in view.rows
        ),
    )
