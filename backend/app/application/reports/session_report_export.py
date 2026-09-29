"""`getSessionReport` as an `ExportDocument` (I7 E46b, owner item 6) — the session report has no
CSV to extend, so this is its first file export. Four sections/sheets, the report's own numbers,
nothing recomputed (D11):

* «Сводка» — the session id, checksum, totals, percent and «сдал/не сдал»;
* «Категории» — the score by `ScoringCategory` (`SessionReportView.score_report.by_category`);
* «Оценка» — the visible rule results (`score_report.results`, already filtered per viewer by
  `assemble_report._visible_report`);
* «Хронология» — the visible timeline (`SessionReportView.timeline`, already filtered per viewer);
* «Нормативы и время реакции» — `norms` / `reaction_times`, already gated per viewer.

Nested, free-text sections (the final card's own field values, the transcript, ДДС decisions'
dispatch/status sub-lists, text quality's spans) stay JSON/UI-only for this first cut — a tabular
export of those adds little over reading the screen the export is downloaded from, and the four
sections above are SPEC §29's scored, numeric core (statistics/rating/lesson report's own scope).
"""

from __future__ import annotations

from datetime import datetime

from app.application.ports.report_exporter import (
    MOSCOW_TZ,
    ExportCell,
    ExportDocument,
    ExportTable,
)
from app.application.reports.assemble_report import SessionReportView
from app.application.reports.csv_export import NORM_KIND_LABELS_RU
from app.application.statistics.statistics_csv import SCORING_CATEGORY_LABELS_RU

__all__ = ["session_report_export_document"]

_SUMMARY_HEADER = ("Показатель", "Значение")
_CATEGORIES_HEADER = ("Категория", "Баллы", "Максимум баллов")
_RESULTS_HEADER = ("Правило", "Категория", "Баллы", "Максимум баллов", "Критично")
_TIMELINE_HEADER = ("Время (МСК)", "Тип события", "Кто", "Описание")
_NORMS_HEADER = ("Норматив", "Время, мс", "Норма, мс", "Отклонение от нормы, мс")


def session_report_export_document(
    view: SessionReportView, *, filters_line: str, generated_at: datetime
) -> ExportDocument:
    percent = (
        None
        if view.score_report.total_max_points <= 0
        else round(100 * view.score_report.total_points / view.score_report.total_max_points, 1)
    )
    summary_rows: list[list[ExportCell]] = [
        ["Сессия", str(view.session_id)],
        ["Контрольная сумма", view.checksum],
        ["Рабочие места", ", ".join(view.workstations) or None],
        ["Баллы", view.score_report.total_points],
        ["Максимум баллов", view.score_report.total_max_points],
        ["Процент", percent],
        [
            "Сдал / не сдал",
            (
                None
                if view.pass_verdict is None
                else ("Сдал" if view.pass_verdict.passed else "Не сдал")
            ),
        ],
        ["Нарушено правил", view.failed_rule_count],
        ["Критических ошибок", view.critical_error_count],
        ["Учтено событий", view.score_report.computed_from_event_count],
    ]
    categories_rows: list[list[ExportCell]] = [
        [
            SCORING_CATEGORY_LABELS_RU.get(total.category, total.category.value),
            total.points_awarded,
            total.max_points,
        ]
        for total in view.score_report.by_category
    ]
    rule_names = {rule.rule_id: rule.name_ru for rule in view.scoring_rules}
    rule_categories = {rule.rule_id: rule.category for rule in view.scoring_rules}
    results_rows: list[list[ExportCell]] = [
        [
            rule_names.get(result.rule_id, result.rule_id),
            SCORING_CATEGORY_LABELS_RU.get(
                rule_categories.get(result.rule_id, result.category), result.category.value
            ),
            result.points_awarded,
            result.max_points,
            "Да" if result.critical_failure else "Нет",
        ]
        for result in view.score_report.results
    ]
    timeline_rows: list[list[ExportCell]] = [
        [
            # Moscow wall time (the document's own "Сформировано" convention) — Excel's date
            # cell has no timezone concept at all, so this is also where the UTC-stored instant
            # becomes the time a Russian reader expects to see (`xlsx_exporter` only strips the
            # tzinfo, it does not shift the clock).
            entry.timestamp_utc.astimezone(MOSCOW_TZ),
            entry.event_type.value,
            entry.call_party_ru,
            entry.summary_ru,
        ]
        for entry in view.timeline
    ]
    norms_rows: list[list[ExportCell]] = [
        [NORM_KIND_LABELS_RU[norm.kind], norm.measured_ms, norm.norm_ms, norm.deviation_ms]
        for norm in view.norms
    ]
    norms_rows.extend(_reaction_rows(view))
    return ExportDocument(
        title="Отчёт по сессии",
        filters_line=filters_line,
        generated_at=generated_at,
        tables=[
            ExportTable(title="Сводка", header=_SUMMARY_HEADER, rows=summary_rows),
            ExportTable(title="Категории", header=_CATEGORIES_HEADER, rows=categories_rows),
            ExportTable(title="Оценка", header=_RESULTS_HEADER, rows=results_rows),
            ExportTable(title="Хронология", header=_TIMELINE_HEADER, rows=timeline_rows),
            ExportTable(title="Нормативы и время реакции", header=_NORMS_HEADER, rows=norms_rows),
        ],
    )


def _reaction_rows(view: SessionReportView) -> list[list[ExportCell]]:
    """(I5 E36, Q-E12-1) The two per-leg reaction times, no norm — same convention as
    `csv_export.lesson_report_csv`'s expansion."""
    rows: list[list[ExportCell]] = []
    for reaction in view.reaction_times:
        rows.append(["Время реакции: открытие карточки", reaction.to_open_ms, None, None])
        rows.append(["Время реакции: первый статус", reaction.to_first_status_ms, None, None])
    return rows
