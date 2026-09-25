"""The CSV format of the reports and the statistics (I4 E33, HLD 71 §71.10; ТЗ ¶360, ¶379).

UTF-8 with BOM, `;`, `\\r\\n`, a decimal comma, an empty cell for "not measured" — and a number
read back is exactly the number written (`repr`), which is what lets the API tests assert that a
file parses back to its JSON.
"""

from __future__ import annotations

import csv
import io

import pytest
from app.application.reports.csv_export import csv_number, render_csv


@pytest.mark.parametrize(
    ("value", "cell"),
    [
        (None, ""),
        (0, "0"),
        (-33_000, "-33000"),
        (2.0, "2"),
        (2.5, "2,5"),
        (-0.1, "-0,1"),
        (0.1 + 0.2, "0,30000000000000004"),
    ],
)
def test_a_number_is_one_cell_with_a_decimal_comma(value: float | int | None, cell: str) -> None:
    assert csv_number(value) == cell


def test_a_fraction_reads_back_exactly() -> None:
    for value in (0.1 + 0.2, 1 / 3, 82.3529411764706, -17.25):
        assert float(csv_number(value).replace(",", ".")) == value


def test_the_file_has_a_bom_semicolons_and_crlf() -> None:
    data = render_csv(["Обучаемый", "Сессий"], [["Иванов; И.", "3"], ["Петров", ""]])
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert text == 'Обучаемый;Сессий\r\n"Иванов; И.";3\r\nПетров;\r\n'
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert rows == [["Обучаемый", "Сессий"], ["Иванов; И.", "3"], ["Петров", ""]]
