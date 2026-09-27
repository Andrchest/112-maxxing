"""CSV for the lesson report and the statistics (I4 E33, HLD 71 §71.10; I5 E36; ТЗ ¶360 REQ-2299,
¶379 REQ-2313: «CSV для выгрузки отчетов и статистики»).

One format for every file: stdlib `csv`, UTF-8 **with BOM**, `;` as the separator, `\\r\\n` line
ends, Russian column headers. The BOM and the `;` are what a Russian-locale spreadsheet expects to
open a file with a double click; for the same reason a fractional number is written with a decimal
comma (`2,5`). Integers are written as they are; a value that was not measured is an empty cell,
never `0`. Floats are written with `repr`, so a file read back gives exactly the numbers of the
JSON it was rendered from — the file is a rendering of the same view, never a second computation
(D11).

`lesson_report_csv` renders `getLessonReport`'s view: one row per card and norm (a card with no
norm, e.g. an unscored one, still gets its one row), plus one row per leg reaction time (I5 E36,
Q-E12-1 — the "Норматив" cell names which reaction it is and "Норма, мс" / "Отклонение от нормы,
мс" stay empty, a reaction time has neither), then the weighted total. Every row of a card repeats
its «Рабочее место» (I5 E36, Q-E12-3). Rows are built as `{column: cell}` maps and read out in
`LESSON_REPORT_CSV_HEADER`'s order (`_row`), so a column added or reordered cannot silently
misalign an existing one. The statistics' file is rendered in
`app.application.statistics.statistics_csv` with the same helpers.
"""

from __future__ import annotations

import codecs
import csv
import io
from collections.abc import Iterable, Mapping, Sequence

from app.application.lessons.lesson_report import LessonReportCard, LessonReportView
from app.application.reports.norms import CardNorm, LegReactionTime, NormKind
from app.domain.enums import SessionState

__all__ = [
    "CSV_MEDIA_TYPE",
    "LESSON_REPORT_CSV_HEADER",
    "NORM_KIND_LABELS_RU",
    "REACTION_TO_OPEN_LABEL_RU",
    "REACTION_TO_STATUS_LABEL_RU",
    "csv_number",
    "lesson_report_csv",
    "render_csv",
]

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"

NORM_KIND_LABELS_RU: Mapping[NormKind, str] = {
    NormKind.ACCEPT: "Принятие решения службой",
    NormKind.FILL: "Заполнение карточки 112",
    NormKind.DDS_FILL: "Заполнение карточки ДДС (3 мин)",
}
"""What each interval is (module doc of `norms`)."""

REACTION_TO_OPEN_LABEL_RU = "Время реакции: открытие карточки"
REACTION_TO_STATUS_LABEL_RU = "Время реакции: первый статус"
"""(I5 E36, Q-E12-1) The two reaction times' own row labels, in the «Норматив» column — they carry
no norm, so «Норма, мс» / «Отклонение от нормы, мс» are empty on their rows."""

_STATE_LABELS_RU: Mapping[SessionState, str] = {
    SessionState.COMPLETED: "Завершено",
    SessionState.ABORTED: "Прервано",
}

_POSITION = "Позиция"
_SESSION = "Сессия"
_WORKSTATION = "Рабочее место"
_STATE = "Состояние"
_WEIGHT = "Вес"
_POINTS = "Баллы"
_MAX_POINTS = "Максимум баллов"
_FAILED_RULES = "Нарушено правил"
_CRITICAL_ERRORS = "Критических ошибок"
_NORM_KIND = "Норматив"
_SERVICE = "Служба"
_MEASURED_MS = "Время, мс"
_NORM_MS = "Норма, мс"
_DEVIATION_MS = "Отклонение от нормы, мс"

LESSON_REPORT_CSV_HEADER: tuple[str, ...] = (
    _POSITION,
    _SESSION,
    _WORKSTATION,
    _STATE,
    _WEIGHT,
    _POINTS,
    _MAX_POINTS,
    _FAILED_RULES,
    _CRITICAL_ERRORS,
    _NORM_KIND,
    _SERVICE,
    _MEASURED_MS,
    _NORM_MS,
    _DEVIATION_MS,
)

_TOTAL_LABEL = "Итого (с учётом весов)"


def _row(values: Mapping[str, str]) -> list[str]:
    """One CSV row, cells read out in `LESSON_REPORT_CSV_HEADER`'s order; a column this row does
    not set is empty."""
    return [values.get(column, "") for column in LESSON_REPORT_CSV_HEADER]


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
    """`getLessonReportCsv`: the rows of `view` (norms, then reaction times), then the weighted
    total."""
    rows: list[list[str]] = []
    for card in view.cards:
        norms: Sequence[CardNorm | None] = (
            card.report.norms if card.report is not None and card.report.norms else (None,)
        )
        rows.extend(_row(_card_cells(card, norm)) for norm in norms)
        if card.report is not None:
            rows.extend(_row(cells) for cells in _reaction_rows(card, card.report.reaction_times))
    rows.append(
        _row(
            {
                _POSITION: _TOTAL_LABEL,
                _POINTS: csv_number(view.weighted_total),
                _MAX_POINTS: csv_number(view.weighted_max),
            }
        )
    )
    return render_csv(LESSON_REPORT_CSV_HEADER, rows)


def _card_cells(card: LessonReportCard, norm: CardNorm | None) -> dict[str, str]:
    report = card.report
    state = SessionState.COMPLETED if report is not None else _unscored_state(card)
    services = {} if report is None or report.service_names_ru is None else report.service_names_ru
    return {
        _POSITION: str(card.position),
        _SESSION: str(card.session_id),
        _WORKSTATION: "" if report is None else ", ".join(report.workstations),
        _STATE: _STATE_LABELS_RU.get(state, state.value),
        _WEIGHT: csv_number(card.weight),
        _POINTS: "" if report is None else csv_number(report.score_report.total_points),
        _MAX_POINTS: "" if report is None else csv_number(report.score_report.total_max_points),
        _FAILED_RULES: "" if report is None else str(report.failed_rule_count),
        _CRITICAL_ERRORS: "" if report is None else str(report.critical_error_count),
        _NORM_KIND: "" if norm is None else NORM_KIND_LABELS_RU[norm.kind],
        _SERVICE: (
            ""
            if norm is None or norm.service_id is None
            else services.get(norm.service_id, norm.service_id)
        ),
        _MEASURED_MS: "" if norm is None else csv_number(norm.measured_ms),
        _NORM_MS: "" if norm is None else csv_number(norm.norm_ms),
        _DEVIATION_MS: "" if norm is None else csv_number(norm.deviation_ms),
    }


def _reaction_rows(
    card: LessonReportCard, reaction_times: Sequence[LegReactionTime]
) -> Iterable[dict[str, str]]:
    """(I5 E36, Q-E12-1) Two rows per leg — no norm, no deviation — reusing the card's own cells
    for everything but «Норматив» / «Служба» / «Время, мс»."""
    base = _card_cells(card, None)
    services = (
        {}
        if card.report is None or card.report.service_names_ru is None
        else card.report.service_names_ru
    )
    for reaction in reaction_times:
        service = (
            ""
            if reaction.service_id is None
            else services.get(reaction.service_id, reaction.service_id)
        )
        yield {
            **base,
            _NORM_KIND: REACTION_TO_OPEN_LABEL_RU,
            _SERVICE: service,
            _MEASURED_MS: csv_number(reaction.to_open_ms),
        }
        yield {
            **base,
            _NORM_KIND: REACTION_TO_STATUS_LABEL_RU,
            _SERVICE: service,
            _MEASURED_MS: csv_number(reaction.to_first_status_ms),
        }


def _unscored_state(card: LessonReportCard) -> SessionState:
    return SessionState.ABORTED if card.unscored is None else card.unscored.state
