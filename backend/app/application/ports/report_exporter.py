"""`ReportExporter` port (I7 E46b, owner item 6) — the Excel and PDF twin of every CSV export.

Every place that already offers a CSV (statistics, the trainee rating, the lesson report) gains
«Excel» and «PDF» next to it, over the same view, same filters, same auth; the session report,
which has no CSV, gains the two straight away. The application layer builds an `ExportDocument` —
one `ExportTable` per XLSX sheet / PDF section — from a view it already has (see
`app.application.statistics.statistics_export`, `.trainee_rating_export`,
`app.application.reports.lesson_report_export`, `.session_report_export`); this port turns that
plain data into bytes. Keeping cells typed (`int` / `float` / `date` / `datetime` / `str` / `None`)
all the way to the adapter is what lets `openpyxl` write a genuine number or date cell instead of a
second, silently different rendering of the same value the CSV already committed to (D11).

The adapter is `app.infrastructure.export.report_exporter.StandardReportExporter` (openpyxl +
reportlab, `backend/app/infrastructure/export/fonts/` for the PDF's Cyrillic).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from app.application.ports.clock import Clock

__all__ = [
    "MOSCOW_TZ",
    "PDF_MEDIA_TYPE",
    "XLSX_MEDIA_TYPE",
    "ExportCell",
    "ExportDocument",
    "ExportTable",
    "ReportExporter",
    "generated_at_moscow",
]

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"

ExportCell = str | int | float | date | datetime | None
"""A typed cell: `None` is an empty cell (never `0` or `""` — the CSV export's own "not measured"
convention, `csv_export`'s module doc)."""


@dataclass(frozen=True, slots=True)
class ExportTable:
    """One XLSX sheet / one PDF section: a title, a header row and its data rows."""

    title: str
    header: Sequence[str]
    rows: Sequence[Sequence[ExportCell]]


@dataclass(frozen=True, slots=True)
class ExportDocument:
    """What `ReportExporter.render_xlsx` / `.render_pdf` turn into a file.

    `filters_line` is the query's own filters rendered as one line of Russian text (an empty
    string for "no filter applied") and `generated_at` is `generated_at_moscow`'s reading — both
    are shown on the PDF page and above the header row of every XLSX sheet, so the file always
    says which filters and which moment produced it.
    """

    title: str
    filters_line: str
    generated_at: datetime
    tables: Sequence[ExportTable]


def generated_at_moscow(clock: Clock) -> datetime:
    """`clock.now()` (UTC, D5) as Europe/Moscow wall time — every export's "Сформировано" stamp."""
    return clock.now().astimezone(MOSCOW_TZ)


@runtime_checkable
class ReportExporter(Protocol):
    """Renders an `ExportDocument` as a complete file, nothing streamed (every export today is
    small enough to hold in memory, like the CSV renderers it sits beside)."""

    def render_xlsx(self, document: ExportDocument) -> bytes: ...

    def render_pdf(self, document: ExportDocument) -> bytes: ...
