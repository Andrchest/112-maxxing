"""`getTraineeStatisticsCsv` — `getTraineeStatistics`' rows as a file (I4 E33, HLD 71 §71.10;
I5 E36; ТЗ ¶360, ¶379).

The same view, the same numbers, rendered with `reports.csv_export`'s format (UTF-8 with BOM,
`;`, Russian headers, decimal comma). One column per `ScoringCategory`, in the enum's order, so
every file has the same columns whether or not a category has a failure (`0`, not empty: a count
of none is a count).

(I5 E36, Q-E12-3) «Рабочее место» is the trainee's login (`TraineeAccount.username`), CSV-only
(the JSON `TraineeStatisticsRow` does not carry it — item 4's decision names only this file, the
lesson report table and its CSV). (I5 E36, Q-E12-1) The two reaction-time averages ride beside the
existing deviation averages; no `DDS_FILL` average — see `trainee_statistics`'s module doc.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.application.reports.csv_export import csv_number, render_csv
from app.application.statistics.trainee_statistics import TraineeStatisticsView
from app.domain.enums import ScoringCategory

__all__ = ["SCORING_CATEGORY_LABELS_RU", "STATISTICS_CSV_HEADER", "statistics_csv"]

SCORING_CATEGORY_LABELS_RU: Mapping[ScoringCategory, str] = {
    ScoringCategory.INFORMATION_GATHERING: "Сбор информации",
    ScoringCategory.CARD_QUALITY: "Качество карточки",
    ScoringCategory.SERVICE_ROUTING: "Маршрутизация служб",
    ScoringCategory.TIMELINESS: "Своевременность",
    ScoringCategory.WORKFLOW: "Порядок действий",
    ScoringCategory.RESOURCE_MANAGEMENT: "Управление ресурсами",
    ScoringCategory.COMMUNICATION: "Коммуникация",
}
"""The frontend's labels (`ru.ts` `scoringCategory*`), verbatim."""

STATISTICS_CSV_HEADER: tuple[str, ...] = (
    "Обучаемый",
    "Идентификатор",
    "Рабочее место",
    "Сессий",
    "Занятий",
    "Средний процент",
    "Среднее отклонение принятия решения, мс",
    "Среднее отклонение заполнения карточки, мс",
    "Среднее время реакции: открытие карточки, мс",
    "Среднее время реакции: первый статус, мс",
    *(f"Нарушено правил: {SCORING_CATEGORY_LABELS_RU[c]}" for c in ScoringCategory),
)


def statistics_csv(view: TraineeStatisticsView) -> bytes:
    """One line per row of `view`, in its order."""
    return render_csv(
        STATISTICS_CSV_HEADER,
        (
            [
                row.display_name_ru,
                str(row.trainee_user_id),
                row.username,
                str(row.session_count),
                str(row.lesson_count),
                csv_number(row.average_percent),
                csv_number(row.accept_deviation_ms_avg),
                csv_number(row.fill_deviation_ms_avg),
                csv_number(row.reaction_to_open_ms_avg),
                csv_number(row.reaction_to_status_ms_avg),
                *(
                    str(row.failed_rules_by_category.get(category.value, 0))
                    for category in ScoringCategory
                ),
            ]
            for row in view.rows
        ),
    )
