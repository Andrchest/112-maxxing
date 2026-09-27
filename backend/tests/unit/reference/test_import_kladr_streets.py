"""`backend/tools/import_kladr_streets.py` — the КЛАДР half of `reference/streets/` (I5 E41,
HLD 71 §71.12 follow-up, Q-E23-2, CHANGE A).

The real `base.7z` (~61 MB, ФНС open data) is never committed (module doc of the tool under test),
so this test builds a tiny synthetic dBase III / 7z fixture instead of reading it — the parser and
the region-77 filter are exercised exactly as they run against the real archive, just on three
made-up rows.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from tools import import_kladr_streets as kladr

REPO_ROOT = Path(__file__).resolve().parents[4]

_FIELDS: tuple[tuple[str, int], ...] = (("NAME", 20), ("SOCR", 10), ("CODE", 17))


def _field_descriptor(name: str, length: int) -> bytes:
    """One 32-byte dBase field descriptor: name(11) + type(1) + reserved(4) + length + dec + pad."""
    return (
        name.encode("ascii").ljust(11, b"\x00")
        + b"C"
        + b"\x00" * 4
        + bytes([length, 0])
        + b"\x00" * 14
    )


def _dbf_bytes(rows: list[tuple[str, str, str, bool]]) -> bytes:
    """A minimal dBase III file with `_FIELDS` columns. `rows` is `(name, socr, code, deleted)`."""
    header_len = 32 + len(_FIELDS) * 32 + 1
    record_len = 1 + sum(length for _, length in _FIELDS)
    header = struct.pack("<BBBBIHH", 3, 126, 1, 1, len(rows), header_len, record_len)
    header += b"\x00" * 20
    for name, length in _FIELDS:
        header += _field_descriptor(name, length)
    header += b"\r"
    field_index = {"NAME": 0, "SOCR": 1, "CODE": 2}
    body = bytearray()
    for row in rows:
        *_, deleted = row
        body += b"*" if deleted else b" "
        for field_name, length in _FIELDS:
            value = row[field_index[field_name]]
            body += value.encode("cp866").ljust(length)[:length]
    return header + bytes(body)


def test_iter_dbf_records_reads_fields_and_skips_deleted_rows() -> None:
    data = _dbf_bytes(
        [
            ("Тестовая", "ул", "77000000000000100", False),
            ("Удалённая", "ул", "77000000000000200", True),
        ]
    )
    rows = list(kladr._iter_dbf_records(data))
    assert len(rows) == 1
    assert rows[0]["NAME"] == "Тестовая"
    assert rows[0]["SOCR"] == "ул"
    assert rows[0]["CODE"] == "77000000000000100"


def test_moscow_street_names_filters_region_77_and_dedupes(tmp_path: Path) -> None:
    """Region `77` (Moscow) is kept, another region is dropped, and a display duplicate collapses
    to one line — the same filter the tool applies to the real `STREET.DBF`."""
    pytest.importorskip("py7zr", reason="the `tools` dependency group is not installed")
    import py7zr

    data = _dbf_bytes(
        [
            ("Тестовая", "ул", "77000000000000100", False),
            ("Тестовая", "ул", "77000000000000101", False),  # same display value, another code
            ("Другая", "пер", "50000000000000100", False),  # region 50: not Moscow
        ]
    )
    dbf_path = tmp_path / kladr.STREET_DBF_MEMBER
    dbf_path.write_bytes(data)
    archive_path = tmp_path / "base.7z"
    with py7zr.SevenZipFile(archive_path, mode="w") as archive:
        archive.write(dbf_path, arcname=kladr.STREET_DBF_MEMBER)

    assert kladr.moscow_street_names(archive_path) == ["Тестовая ул"]


def test_render_is_sorted_and_newline_terminated(tmp_path: Path) -> None:
    pytest.importorskip("py7zr", reason="the `tools` dependency group is not installed")
    import py7zr

    data = _dbf_bytes(
        [
            ("Юрьевская", "ул", "77000000000000100", False),
            ("Абрикосовая", "ул", "77000000000000200", False),
        ]
    )
    dbf_path = tmp_path / kladr.STREET_DBF_MEMBER
    dbf_path.write_bytes(data)
    archive_path = tmp_path / "base.7z"
    with py7zr.SevenZipFile(archive_path, mode="w") as archive:
        archive.write(dbf_path, arcname=kladr.STREET_DBF_MEMBER)

    text = kladr.render(archive_path)
    assert text == "Абрикосовая ул\nЮрьевская ул\n"


def test_missing_archive_is_a_clean_cli_error() -> None:
    exit_code = kladr.main(["--archive", "/no/such/base.7z"])
    assert exit_code == 2


def test_the_packaged_file_is_pinned_in_the_manifest() -> None:
    """The output this tool writes is one of `reference/manifest.json`'s pinned files (I5 E41)."""
    import json

    manifest = json.loads((REPO_ROOT / "reference" / "manifest.json").read_text(encoding="utf-8"))
    assert "streets/kladr_moscow_street_names.txt" in manifest["files"]
