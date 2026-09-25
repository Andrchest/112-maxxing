"""Unit tests of `last.json` parsing (I4 E26, docs/hld/71-i4-wave4.md §71.3, acceptance: "Unit
side: last.json parsing"). Not part of `make gate` (root `pyproject.toml`'s `testpaths` is fixed to
`backend/tests`, `workers/voice_agent/tests` and `benchmarks/tests`, same as the rest of `infra/`) —
run directly:

    uv run pytest infra/scripts/tests/test_backup_status.py -q
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backup_status import BackupStatusError, read_status, verify

GOOD = {
    "ts": "20260925T120000Z",
    "status": "ok",
    "dump_file": "sim-20260925T120000Z.dump",
    "dump_size_bytes": 12345,
    "dump_sha256": "a" * 64,
    "recordings_file": "recordings-20260925T120000Z.tar.gz",
    "recordings_size_bytes": 6789,
    "recordings_sha256": "b" * 64,
    "error": None,
}


def _write(tmp_path: Path, doc: dict) -> Path:
    path = tmp_path / "last.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_read_status_parses_a_well_formed_file(tmp_path: Path) -> None:
    status = read_status(_write(tmp_path, GOOD))
    assert status.ok is True
    assert status.dump_file == GOOD["dump_file"]
    assert status.dump_size_bytes == 12345
    assert status.dump_sha256 == "a" * 64
    assert status.error is None
    assert status.ts == datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)


def test_read_status_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(BackupStatusError, match="does not exist"):
        read_status(tmp_path / "nope.json")


def test_read_status_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "last.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(BackupStatusError, match="not valid JSON"):
        read_status(path)


def test_read_status_missing_key_raises(tmp_path: Path) -> None:
    doc = dict(GOOD)
    del doc["dump_sha256"]
    with pytest.raises(BackupStatusError, match="missing key"):
        read_status(_write(tmp_path, doc))


def test_read_status_bad_ts_format_raises(tmp_path: Path) -> None:
    doc = dict(GOOD, ts="2026-09-25")
    with pytest.raises(BackupStatusError, match="ts"):
        read_status(_write(tmp_path, doc))


def test_read_status_bad_status_value_raises(tmp_path: Path) -> None:
    doc = dict(GOOD, status="not-a-status")
    with pytest.raises(BackupStatusError, match="status"):
        read_status(_write(tmp_path, doc))


def test_verify_passes_for_a_fresh_ok_backup(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    fresh_ts = now.strftime("%Y%m%dT%H%M%SZ")
    doc = dict(GOOD, ts=fresh_ts)
    passed, message = verify(_write(tmp_path, doc))
    assert passed is True
    assert "OK" in message


def test_verify_fails_for_a_failed_backup(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    doc = dict(GOOD, ts=now.strftime("%Y%m%dT%H%M%SZ"), status="failed", error="pg_dump failed")
    passed, message = verify(_write(tmp_path, doc))
    assert passed is False
    assert "FAILED" in message
    assert "pg_dump failed" in message


def test_verify_fails_for_a_stale_backup(tmp_path: Path) -> None:
    stale = datetime.now(UTC) - timedelta(hours=30)
    doc = dict(GOOD, ts=stale.strftime("%Y%m%dT%H%M%SZ"))
    passed, message = verify(_write(tmp_path, doc), max_age_hours=26)
    assert passed is False
    assert "old" in message


def test_verify_fails_for_a_missing_file(tmp_path: Path) -> None:
    passed, message = verify(tmp_path / "missing.json")
    assert passed is False
    assert "does not exist" in message
