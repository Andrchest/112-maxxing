"""`getLessonReport` as an `ExportDocument` (I7 E46b) — the Excel/PDF twin of
`csv_export.lesson_report_csv`, same numbers, two sheets/sections instead of the CSV's one wide
table (typed cells read better split than repeated across a norm/reaction expansion, D11's "a
rendering of the same view" still holds — nothing here is a second computation):

* «Карточки» — one row per card, its own totals and verdict;
* «Нормативы и время реакции» — one row per card norm or per-leg reaction time (I5 E36,
  Q-E12-1), the same rows `lesson_report_csv` expands into, minus the columns that do not apply
  to a norm/reaction row.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from app.application.lessons.lesson_report import LessonReportCard, LessonReportView
from app.application.ports.report_exporter import ExportCell, ExportDocument, ExportTable
from app.application.reports.csv_export import (
    NORM_KIND_LABELS_RU,
    PASS_VERDICT_LABELS_RU,
    REACTION_TO_OPEN_LABEL_RU,
    REACTION_TO_STATUS_LABEL_RU,
)
from app.application.reports.norms import CardNorm, LegReactionTime
from app.domain.enums import SessionState

__all__ = ["lesson_report_export_document"]

_STATE_LABELS_RU: Mapping[SessionState, str] = {
    SessionState.COMPLETED: "Завершено",
    SessionState.ABORTED: "Прервано",
}

_CARDS_HEADER = (
    "Позиция",
    "Сессия",
    "Рабочее место",
    "Состояние",
    "Вес",
    "Баллы",
    "Максимум баллов",
    "Нарушено правил",
    "Критических ошибок",
    "Итог",
)

_NORMS_HEADER = (
    "Позиция",
    "Сессия",
    "Норматив",
    "Служба",
    "Время, мс",
    "Норма, мс",
    "Отклонение от нормы, мс",
)


def lesson_report_export_document(
    view: LessonReportView, *, filters_line: str, generated_at: datetime
) -> ExportDocument:
    cards_rows = [_card_row(card) for card in view.cards]
    cards_rows.append(
        [
            "Итого (с учётом весов)",
            None,
            None,
            None,
            None,
            view.weighted_total,
            view.weighted_max,
            None,
            None,
            None,
        ]
    )
    norms_rows: list[list[ExportCell]] = []
    for card in view.cards:
        report = card.report
        if report is None:
            continue
        for norm in report.norms:
            norms_rows.append(_norm_row(card, norm))
        norms_rows.extend(_reaction_rows(card, report.reaction_times))
    return ExportDocument(
        title="Отчёт по занятию",
        filters_line=filters_line,
        generated_at=generated_at,
        tables=[
            ExportTable(title="Карточки", header=_CARDS_HEADER, rows=cards_rows),
            ExportTable(title="Нормативы и время реакции", header=_NORMS_HEADER, rows=norms_rows),
        ],
    )


def _card_row(card: LessonReportCard) -> list[ExportCell]:
    report = card.report
    state = SessionState.COMPLETED if report is not None else _unscored_state(card)
    return [
        card.position,
        str(card.session_id),
        None if report is None else ", ".join(report.workstations) or None,
        _STATE_LABELS_RU.get(state, state.value),
        card.weight,
        None if report is None else report.score_report.total_points,
        None if report is None else report.score_report.total_max_points,
        None if report is None else report.failed_rule_count,
        None if report is None else report.critical_error_count,
        (
            None
            if report is None or report.pass_verdict is None
            else PASS_VERDICT_LABELS_RU[report.pass_verdict.passed]
        ),
    ]


def _norm_row(card: LessonReportCard, norm: CardNorm) -> list[ExportCell]:
    report = card.report
    assert report is not None
    services = {} if report.service_names_ru is None else report.service_names_ru
    service = None if norm.service_id is None else services.get(norm.service_id, norm.service_id)
    return [
        card.position,
        str(card.session_id),
        NORM_KIND_LABELS_RU[norm.kind],
        service,
        norm.measured_ms,
        norm.norm_ms,
        norm.deviation_ms,
    ]


def _reaction_rows(
    card: LessonReportCard, reaction_times: tuple[LegReactionTime, ...]
) -> list[list[ExportCell]]:
    report = card.report
    assert report is not None
    services = {} if report.service_names_ru is None else report.service_names_ru
    rows: list[list[ExportCell]] = []
    for reaction in reaction_times:
        service = (
            None
            if reaction.service_id is None
            else services.get(reaction.service_id, reaction.service_id)
        )
        rows.append(
            [
                card.position,
                str(card.session_id),
                REACTION_TO_OPEN_LABEL_RU,
                service,
                reaction.to_open_ms,
                None,
                None,
            ]
        )
        rows.append(
            [
                card.position,
                str(card.session_id),
                REACTION_TO_STATUS_LABEL_RU,
                service,
                reaction.to_first_status_ms,
                None,
                None,
            ]
        )
    return rows


def _unscored_state(card: LessonReportCard) -> SessionState:
    return SessionState.ABORTED if card.unscored is None else card.unscored.state
