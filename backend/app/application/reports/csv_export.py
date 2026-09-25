"""CSV for the lesson report and the statistics (I4 E33, HLD 71 §71.10; ТЗ ¶360 REQ-2299,
¶379 REQ-2313: «CSV для выгрузки отчетов и статистики»).

One format for every file: stdlib `csv`, UTF-8 **with BOM**, `;` as the separator, `\\r\\n` line
ends, Russian column headers. The BOM and the `;` are what a Russian-locale spreadsheet expects to
open a file with a double click; for the same reason a fractional number is written with a decimal
comma (`2,5`). Integers are written as they are; a value that was not measured is an empty cell,
never `0`. Floats are written with `repr`, so a file read back gives exactly the numbers of the
JSON it was rendered from — the file is a rendering of the same view, never a second computation
(D11).

`lesson_report_csv` renders `getLessonReport`'s view: one row per card and norm (a card with no
norm, e.g. an unscored one, still gets its one row), then the weighted total. The statistics' file
is rendered in `app.application.statistics.statistics_csv` with the same helpers.
"""

from __future__ import annotations

import codecs
import csv
import io
from collections.abc import Iterable, Mapping, Sequence

from app.application.lessons.lesson_report import LessonReportCard, LessonReportView
from app.application.reports.norms import CardNorm, NormKind
from app.domain.enums import SessionState

__all__ = [
    "CSV_MEDIA_TYPE",
    "LESSON_REPORT_CSV_HEADER",
    "NORM_KIND_LABELS_RU",
    "csv_number",
    "lesson_report_csv",
    "render_csv",
]

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"

NORM_KIND_LABELS_RU: Mapping[NormKind, str] = {
    NormKind.ACCEPT: "Принятие решения службой",
    NormKind.FILL: "Заполнение карточки 112",
}
"""What each interval is (module doc of `norms`); neither is called «время реакции» (Q-E12-1)."""

_STATE_LABELS_RU: Mapping[SessionState, str] = {
    SessionState.COMPLETED: "Завершено",
    SessionState.ABORTED: "Прервано",
}

LESSON_REPORT_CSV_HEADER: tuple[str, ...] = (
    "Позиция",
    "Сессия",
    "Состояние",
    "Вес",
    "Баллы",
    "Максимум баллов",
    "Нарушено правил",
    "Критических ошибок",
    "Норматив",
    "Служба",
    "Время, мс",
    "Норма, мс",
    "Отклонение от нормы, мс",
)

_TOTAL_LABEL = "Итого (с учётом весов)"


def csv_number(value: float | int | None) -> str:
    """A cell: `""` for `None`, an integer as is, a fraction with a decimal comma (`repr`)."""
    if value is None:
        return ""
    if isinstance(value, bool):  # pragma: no cover - no boolean column exists
        raise TypeError("a boolean is not a CSV number")
    if isinstance(value, int):
        return str(value)
    if value.is_integer():
        return str(int(value))
    return repr(value).replace(".", ",")


def render_csv(header: Sequence[str], rows: Iterable[Sequence[str]]) -> bytes:
    """The file: BOM, `;`, `\\r\\n`, every cell quoted only when it has to be."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return codecs.BOM_UTF8 + buffer.getvalue().encode("utf-8")


def lesson_report_csv(view: LessonReportView) -> bytes:
    """`getLessonReportCsv`: the rows of `view`, then the weighted total."""
    rows: list[list[str]] = []
    for card in view.cards:
        norms: Sequence[CardNorm | None] = (
            card.report.norms if card.report is not None and card.report.norms else (None,)
        )
        rows.extend(_card_row(card, norm) for norm in norms)
    rows.append(
        [
            _TOTAL_LABEL,
            "",
            "",
            "",
            csv_number(view.weighted_total),
            csv_number(view.weighted_max),
            *[""] * (len(LESSON_REPORT_CSV_HEADER) - 6),
        ]
    )
    return render_csv(LESSON_REPORT_CSV_HEADER, rows)


def _card_row(card: LessonReportCard, norm: CardNorm | None) -> list[str]:
    report = card.report
    state = SessionState.COMPLETED if report is not None else _unscored_state(card)
    services = {} if report is None or report.service_names_ru is None else report.service_names_ru
    return [
        str(card.position),
        str(card.session_id),
        _STATE_LABELS_RU.get(state, state.value),
        csv_number(card.weight),
        "" if report is None else csv_number(report.score_report.total_points),
        "" if report is None else csv_number(report.score_report.total_max_points),
        "" if report is None else str(report.failed_rule_count),
        "" if report is None else str(report.critical_error_count),
        "" if norm is None else NORM_KIND_LABELS_RU[norm.kind],
        ""
        if norm is None or norm.service_id is None
        else services.get(norm.service_id, norm.service_id),
        "" if norm is None else csv_number(norm.measured_ms),
        "" if norm is None else csv_number(norm.norm_ms),
        "" if norm is None else csv_number(norm.deviation_ms),
    ]


def _unscored_state(card: LessonReportCard) -> SessionState:
    return SessionState.ABORTED if card.unscored is None else card.unscored.state
