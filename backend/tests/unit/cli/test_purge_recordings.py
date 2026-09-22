"""`app.cli.purge_recordings` — argument parsing and exit codes, with the actual purge and
`Settings` load faked out (R8). `backend/tests/integration/recording/test_purge_recordings.py`
covers the real `PurgeRecordings` use case against PostgreSQL and real files; this file covers only
the thin CLI wrapper around it: `--dry-run` is the default, `--no-dry-run`/`--older-than-days`/
`--session-id` are threaded through unchanged, and a settings/run failure is exit code 2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.application.recording import PurgeRecordingsRequest, PurgeRecordingsResult
from app.cli import purge_recordings as cli


class _FakeSettings:
    """Just enough of `Settings` for `main()` to build a request and print a result."""

    data_dir = "/tmp/unused"
    recording_retention_days = 30


def _result(**overrides: object) -> PurgeRecordingsResult:
    base = {
        "dry_run": True,
        "retention_days": 30,
        "session_count": 0,
        "segment_count": 0,
        "bytes_freed": 0,
        "purged_at": datetime(2026, 1, 1, tzinfo=UTC),
        "reason": "RETENTION_WINDOW",
    }
    base.update(overrides)
    return PurgeRecordingsResult(**base)  # type: ignore[arg-type]


def test_dry_run_is_the_default_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_purge_recordings(
        settings: object, request: PurgeRecordingsRequest
    ) -> PurgeRecordingsResult:
        captured["request"] = request
        return _result()

    monkeypatch.setattr(cli, "Settings", lambda: _FakeSettings())
    monkeypatch.setattr(cli, "purge_recordings", fake_purge_recordings)

    exit_code = cli.main([])

    assert exit_code == 0
    request = captured["request"]
    assert isinstance(request, PurgeRecordingsRequest)
    assert request.dry_run is True
    assert request.older_than_days is None
    assert request.session_id is None


def test_no_dry_run_older_than_days_and_session_id_are_threaded_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_purge_recordings(
        settings: object, request: PurgeRecordingsRequest
    ) -> PurgeRecordingsResult:
        captured["request"] = request
        return _result(dry_run=False, segment_count=2, bytes_freed=4096)

    monkeypatch.setattr(cli, "Settings", lambda: _FakeSettings())
    monkeypatch.setattr(cli, "purge_recordings", fake_purge_recordings)
    session_id = "11111111-1111-4111-8111-111111111111"

    exit_code = cli.main(["--no-dry-run", "--older-than-days", "7", "--session-id", session_id])

    assert exit_code == 0
    request = captured["request"]
    assert isinstance(request, PurgeRecordingsRequest)
    assert request.dry_run is False
    assert request.older_than_days == 7
    assert request.session_id == UUID(session_id)


def test_an_invalid_settings_load_is_exit_code_two(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_settings() -> _FakeSettings:
        raise RuntimeError("SIM_DATABASE_URL is not set")

    monkeypatch.setattr(cli, "Settings", broken_settings)

    assert cli.main([]) == 2


def test_a_failing_run_is_exit_code_two(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_purge_recordings(
        settings: object, request: PurgeRecordingsRequest
    ) -> PurgeRecordingsResult:
        raise ConnectionRefusedError("no postgres")

    monkeypatch.setattr(cli, "Settings", lambda: _FakeSettings())
    monkeypatch.setattr(cli, "purge_recordings", failing_purge_recordings)

    assert cli.main([]) == 2
