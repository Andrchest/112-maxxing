"""`.xlsx` rendering (I7 E46b) — one worksheet per `ExportTable`, `openpyxl` only.

Every sheet starts with the document's own title, filters line and "Сформировано" stamp (three
rows), a blank row, then the bold header row `freeze_panes` pins in place, then the data. A cell
keeps its Python type: `int`/`float` write a real number cell (Excel's own thousands separator and
decimal comma follow the workbook's ru-RU-friendly default numeric format, never a pre-formatted
string), `date`/`datetime` write a real date cell with an explicit `DD.MM.YYYY[ HH:MM]` number
format, and `None` is an empty cell.
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.application.ports.report_exporter import ExportCell, ExportDocument, ExportTable

__all__ = ["render_xlsx"]

_DATE_FORMAT = "DD.MM.YYYY"
_DATETIME_FORMAT = "DD.MM.YYYY HH:MM"
_MAX_SHEET_TITLE = 31
"""Excel's own sheet-name length limit."""
_MIN_COLUMN_WIDTH = 8
_MAX_COLUMN_WIDTH = 60


def render_xlsx(document: ExportDocument) -> bytes:
    """One workbook, one sheet per `document.tables` entry, in order."""
    workbook = Workbook()
    first_sheet = workbook.active
    assert first_sheet is not None  # a fresh Workbook always has one
    used_titles: set[str] = set()
    for index, table in enumerate(document.tables):
        sheet = first_sheet if index == 0 else workbook.create_sheet()
        sheet.title = _sheet_title(table.title, used_titles)
        _render_sheet(sheet, document, table)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _sheet_title(title: str, used: set[str]) -> str:
    """A legal, unique Excel sheet name: `:\\/?*[]` are forbidden and 31 characters is the cap."""
    cleaned = "".join(ch for ch in title if ch not in r":\/?*[]") or "Лист"
    base = cleaned[:_MAX_SHEET_TITLE]
    candidate = base
    suffix = 2
    while candidate in used:
        tail = f" {suffix}"
        candidate = base[: _MAX_SHEET_TITLE - len(tail)] + tail
        suffix += 1
    used.add(candidate)
    return candidate


def _render_sheet(sheet: Worksheet, document: ExportDocument, table: ExportTable) -> None:
    # Explicit row numbers throughout — never `sheet.max_row`/`sheet.append` for the layout rows:
    # `append`-ing an all-empty row (the blank separator below) writes no cell, so `max_row` does
    # not advance for it and a row number read back from it would be one short.
    sheet.cell(row=1, column=1, value=document.title).font = Font(bold=True, size=13)
    sheet.cell(row=2, column=1, value=document.filters_line or "Без фильтра")
    sheet.cell(row=3, column=1, value=f"Сформировано: {_format_cell(document.generated_at)} (МСК)")
    header_row = 5
    for column_index, title in enumerate(table.header, start=1):
        cell = sheet.cell(row=header_row, column=column_index, value=title)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="bottom")
    for row_offset, row in enumerate(table.rows):
        row_number = header_row + 1 + row_offset
        for column_index, cell_value in enumerate(row, start=1):
            cell = sheet.cell(row=row_number, column=column_index, value=_xlsx_value(cell_value))
            if isinstance(cell_value, datetime):
                cell.number_format = _DATETIME_FORMAT
            elif isinstance(cell_value, date):
                cell.number_format = _DATE_FORMAT
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1).coordinate
    _size_columns(sheet, table)


def _xlsx_value(cell: ExportCell) -> ExportCell:
    """`bool` is never a cell in this export (`ReportExporter`'s own docstring) — everything else
    is already a type `openpyxl` writes as-is, except a timezone-aware `datetime`: Excel's own
    date cell has no timezone concept at all, and `openpyxl` raises rather than silently drop it
    (a caller means the wall-clock time it already converted to display in, `generated_at_moscow`
    et al. — never UTC re-labelled as naive)."""
    if isinstance(cell, bool):  # pragma: no cover - defensive, no boolean column exists
        raise TypeError("a boolean is not an export cell")
    if isinstance(cell, datetime) and cell.tzinfo is not None:
        return cell.replace(tzinfo=None)
    return cell


def _size_columns(sheet: Worksheet, table: ExportTable) -> None:
    for column_index, header in enumerate(table.header, start=1):
        longest = len(header)
        for row in table.rows:
            if column_index - 1 < len(row):
                longest = max(longest, len(_format_cell(row[column_index - 1])))
        width = max(_MIN_COLUMN_WIDTH, min(_MAX_COLUMN_WIDTH, longest + 2))
        sheet.column_dimensions[get_column_letter(column_index)].width = width


def _format_cell(cell: ExportCell) -> str:
    """Column-width measurement only — the workbook cell itself keeps its real type."""
    if cell is None:
        return ""
    if isinstance(cell, datetime):
        return cell.strftime("%d.%m.%Y %H:%M")
    if isinstance(cell, date):
        return cell.strftime("%d.%m.%Y")
    return str(cell)
