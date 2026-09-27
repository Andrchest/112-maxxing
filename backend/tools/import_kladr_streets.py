#!/usr/bin/env python3
"""ФНС КЛАДР `base.7z` → `reference/streets/kladr_moscow_street_names.txt` (I5 E41, HLD 71 §71.12
follow-up, Q-E23-2).

CHANGE A pins down what Q-E23-2 (E23's own recon, `reference/streets/SOURCES.txt`) left open:
КЛАДР is a second, official-form street-name source, alongside the OSM extract E35 already
packages. `StreetDirectory` (`app.infrastructure.reference.street_directory`) now unions both
files — a street KNOWN to either one is `KNOWN`, and `NEAR` suggestions are drawn from the union.

The archive (`base.7z`, ~61 MB, ФНС open data) is **not committed** (I5 E41 CHANGE A): download it
yourself and pass `--archive`. Its URL changes per release — read it from
`Kladr47ZUrl` at `https://fias.nalog.ru/WebServices/Public/GetLastDownloadFileInfo` (it was
`https://fias-file.nalog.ru/downloads/2026.07.07/base.7z` on 2026-09-27). `py7zr` is a
`tools`-group dependency only (`pyproject.toml`), never imported by `backend/app`
(`backend/tests/unit/reference/test_reference_pack.py`-style boundary: see
`backend/tests/unit/tools/test_import_kladr_streets.py`).

КЛАДР's `STREET.DBF` is dBase III, codepage 866 (Russian MS-DOS) — read here with a minimal
stdlib parser (`_iter_dbf_records`) rather than a general-purpose dbf library, since `py7zr` is the
one new dependency this epic allows. `CODE`'s first two digits are the КЛАДР region code; `77` is
Moscow (ТиНАО included — unified into the city's own code since the 2012 annexation), the same
scope `osm_moscow_street_names.txt` covers.

    uv run python backend/tools/import_kladr_streets.py --archive /path/to/base.7z
    uv run python backend/tools/import_kladr_streets.py --archive /path/to/base.7z --check
"""

from __future__ import annotations

import argparse
import struct
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make `tools.*` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.import_manifest import write_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "reference" / "streets" / "kladr_moscow_street_names.txt"

#: КЛАДР's own region code for Moscow (`STREET.DBF`'s `CODE`, first two digits).
MOSCOW_REGION_CODE = "77"
STREET_DBF_MEMBER = "STREET.DBF"
_ENCODING = "cp866"


def _iter_dbf_records(data: bytes) -> Iterator[dict[str, str]]:
    """Every non-deleted record of a dBase III `.dbf` file, field name -> stripped cp866 text.

    Enough of the format to read КЛАДР's own files: a fixed 32-byte file header (record count,
    header length, record length), one 32-byte field descriptor per column up to the `\\r`
    terminator, then fixed-width records (byte 0 is the deletion flag, `*` marks a deleted one).
    """
    _version, _y, _m, _d, record_count, header_len, record_len = struct.unpack_from(
        "<BBBBIHH", data, 0
    )
    fields: list[tuple[str, int]] = []
    offset = 32
    while data[offset : offset + 1] != b"\r":
        name = data[offset : offset + 11].split(b"\x00")[0].decode(_ENCODING)
        length = data[offset + 16]
        fields.append((name, length))
        offset += 32
    for index in range(record_count):
        start = header_len + index * record_len
        record = data[start : start + record_len]
        if len(record) < record_len or record[0:1] == b"*":
            continue
        values: dict[str, str] = {}
        cursor = 1  # byte 0 is the deletion flag, already checked above
        for name, length in fields:
            values[name] = record[cursor : cursor + length].decode(_ENCODING).strip()
            cursor += length
        yield values


def moscow_street_names(archive_path: Path) -> list[str]:
    """Every unique `"<name> <socr>"` from `STREET.DBF` whose КЛАДР code is region `77`."""
    import py7zr  # `tools` dependency group only (module docstring)

    with tempfile.TemporaryDirectory() as scratch:
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            archive.extract(path=scratch, targets=[STREET_DBF_MEMBER])
        data = (Path(scratch) / STREET_DBF_MEMBER).read_bytes()

    names: set[str] = set()
    for row in _iter_dbf_records(data):
        if not row["CODE"].startswith(MOSCOW_REGION_CODE):
            continue
        name, socr = row["NAME"], row["SOCR"]
        if not name:
            continue
        names.add(f"{name} {socr}" if socr else name)
    return sorted(names)


def render(archive_path: Path) -> str:
    """The byte-stable output text: one name per line, sorted, one trailing newline."""
    return "\n".join(moscow_street_names(archive_path)) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Extract Moscow (КЛАДР region 77) street names from base.7z"
    )
    parser.add_argument(
        "--archive", type=Path, required=True, help="local path to the downloaded base.7z"
    )
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when the packaged file is stale"
    )
    args = parser.parse_args(argv)

    if not args.archive.is_file():
        print(f"error: {args.archive} not found", file=sys.stderr)
        return 2

    text = render(args.archive)
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.is_file() else ""
        if current != text:
            print(f"{OUTPUT_PATH} is stale; re-run without --check", file=sys.stderr)
            return 1
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    write_manifest()
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
