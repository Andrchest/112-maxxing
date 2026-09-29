"""`StandardReportExporter` — the `ReportExporter` port's one adapter (I7 E46b).

Stateless: both formats are pure functions of an `ExportDocument`, split out to their own modules
(`xlsx_exporter`, `pdf_exporter`) because `openpyxl` and `reportlab` share nothing.
"""

from __future__ import annotations

from app.application.ports.report_exporter import ExportDocument
from app.infrastructure.export.pdf_exporter import render_pdf
from app.infrastructure.export.xlsx_exporter import render_xlsx

__all__ = ["StandardReportExporter"]


class StandardReportExporter:
    """`ReportExporter` (`runtime_checkable`, structurally satisfied — no base class needed)."""

    def render_xlsx(self, document: ExportDocument) -> bytes:
        return render_xlsx(document)

    def render_pdf(self, document: ExportDocument) -> bytes:
        return render_pdf(document)
