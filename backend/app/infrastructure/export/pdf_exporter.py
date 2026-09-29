"""`.pdf` rendering (I7 E46b) — A4, Cyrillic via the bundled DejaVu font, `reportlab` only.

The page: the document's title, its filters line, a "Сформировано" (Europe/Moscow) stamp, then one
subtitle + table per `ExportTable`. A table too long for one page splits with its header row
repeated (`Table(..., repeatRows=1)`); every page gets a bottom-right page number. Cells are
formatted with the same convention the CSV export already committed to
(`app.application.reports.csv_export.csv_number`: an integer as-is, a fraction with a decimal
comma) so a number reads the same on the screen, in the CSV and on this page.
"""

from __future__ import annotations

import threading
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.application.ports.report_exporter import ExportCell, ExportDocument, ExportTable

__all__ = ["render_pdf"]

_FONTS_DIR = Path(__file__).parent / "fonts"
_FONT_REGULAR = "DejaVuSans"
_FONT_BOLD = "DejaVuSans-Bold"
_FONTS_REGISTERED = False
_LOCK = threading.Lock()
"""(I7 E57) The routers call `render_pdf` on a worker thread (`asyncio.to_thread`); ReportLab's
registered fonts are process-global and not documented as thread-safe, so one render at a time."""


def _register_fonts() -> None:
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont(_FONT_REGULAR, str(_FONTS_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(_FONTS_DIR / "DejaVuSans-Bold.ttf")))
    _FONTS_REGISTERED = True


def render_pdf(document: ExportDocument) -> bytes:
    """A4, the document's tables one after another, repeating headers, page numbers."""
    with _LOCK:
        return _render_pdf(document)


def _render_pdf(document: ExportDocument) -> bytes:
    _register_fonts()
    buffer = BytesIO()
    margin = 1.5 * cm
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=document.title,
    )
    frame = Frame(margin, margin, A4[0] - 2 * margin, A4[1] - 2 * margin, id="body")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=_draw_page_number)])

    title_style = ParagraphStyle("title", fontName=_FONT_BOLD, fontSize=15, leading=18)
    meta_style = ParagraphStyle("meta", fontName=_FONT_REGULAR, fontSize=9, leading=12)
    heading_style = ParagraphStyle(
        "heading", fontName=_FONT_BOLD, fontSize=11, leading=14, spaceBefore=10, spaceAfter=4
    )

    generated_line = f"Сформировано: {_escape(_format_cell(document.generated_at))} (МСК)"
    story: list[object] = [
        Paragraph(_escape(document.title), title_style),
        Spacer(1, 4),
        Paragraph(_escape(document.filters_line or "Без фильтра"), meta_style),
        Paragraph(generated_line, meta_style),
        Spacer(1, 8),
    ]
    for table in document.tables:
        story.append(Paragraph(_escape(table.title), heading_style))
        story.append(_build_table(table))

    doc.build(story)
    return buffer.getvalue()


def _build_table(table: ExportTable) -> Table:
    cell_style = ParagraphStyle("cell", fontName=_FONT_REGULAR, fontSize=8, leading=10)
    header_style = ParagraphStyle(
        "cellHeader", fontName=_FONT_BOLD, fontSize=8, leading=10, textColor=colors.white
    )
    header = [Paragraph(_escape(column), header_style) for column in table.header]
    body = [
        [Paragraph(_escape(_format_cell(cell)), cell_style) for cell in row] for row in table.rows
    ]
    data = [header, *body]
    grid = Table(data, repeatRows=1, hAlign="LEFT")
    grid.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3b52")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b0b0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
            ]
        )
    )
    return grid


def _draw_page_number(canvas: Canvas, doc: BaseDocTemplate) -> None:
    canvas.saveState()
    canvas.setFont(_FONT_REGULAR, 8)
    canvas.drawRightString(A4[0] - 1.5 * cm, 1 * cm, f"Стр. {canvas.getPageNumber()}")
    canvas.restoreState()


def _format_cell(cell: ExportCell) -> str:
    """The CSV export's own convention (`csv_export.csv_number`), reused here so a number reads
    the same on this page as it does in the CSV: an empty cell for `None`, an integer as-is, a
    fraction with a decimal comma."""
    if cell is None:
        return ""
    if isinstance(cell, bool):  # pragma: no cover - defensive, no boolean column exists
        raise TypeError("a boolean is not an export cell")
    if isinstance(cell, datetime):
        return cell.strftime("%d.%m.%Y %H:%M")
    if isinstance(cell, date):
        return cell.strftime("%d.%m.%Y")
    if isinstance(cell, int):
        return str(cell)
    if isinstance(cell, float):
        return str(int(cell)) if cell.is_integer() else repr(cell).replace(".", ",")
    return cell


def _escape(text: str) -> str:
    """`Paragraph` reads its text as mini-HTML — escape the four characters that matter."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return escaped.replace('"', "&quot;")
