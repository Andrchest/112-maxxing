"""`getTraineeStatistics` as an `ExportDocument` (I7 E46b) — the Excel/PDF twin of
`statistics_csv`, same rows, same columns (`STATISTICS_CSV_HEADER`), typed cells instead of the
CSV's pre-formatted strings so `openpyxl` writes real numbers."""

from __future__ import annotations

from datetime import datetime

from app.application.ports.report_exporter import ExportDocument, ExportTable
from app.application.statistics.statistics_csv import STATISTICS_CSV_HEADER
from app.application.statistics.trainee_statistics import TraineeStatisticsView
from app.domain.enums import ScoringCategory

__all__ = ["statistics_export_document"]


def statistics_export_document(
    view: TraineeStatisticsView, *, filters_line: str, generated_at: datetime
) -> ExportDocument:
    rows = [
        [
            row.display_name_ru,
            str(row.trainee_user_id),
            row.username,
            row.session_count,
            row.lesson_count,
            row.average_percent,
            row.pass_count,
            row.pass_rate,
            row.accept_deviation_ms_avg,
            row.fill_deviation_ms_avg,
            row.reaction_to_open_ms_avg,
            row.reaction_to_status_ms_avg,
            *(row.failed_rules_by_category.get(category.value, 0) for category in ScoringCategory),
        ]
        for row in view.rows
    ]
    return ExportDocument(
        title="Статистика обучаемых",
        filters_line=filters_line,
        generated_at=generated_at,
        tables=[ExportTable(title="Статистика", header=STATISTICS_CSV_HEADER, rows=rows)],
    )
