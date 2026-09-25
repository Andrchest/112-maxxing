"""`getBackupStatus` and the shared parser of E26's `backups/last.json` (ADMIN, ТЗ ¶143, ¶216).

`read_backup_status` is the one place `last.json` (written by `infra/scripts/backup-once.sh`) is
parsed on the backend side; both `GetBackupStatus` (this operation) and
`app.application.recording.purge_recordings.PurgeRecordings` (the `409 BACKUP_REQUIRED` guard) call
it, so the two can never disagree about what "a fresh, successful backup" means.

`infra/scripts/backup_status.py` parses the same file independently, stdlib-only, for the
operator's own `make backup-verify` CLI check outside the backend process (its own docstring says
so); duplicating this one small, stable JSON shape is deliberate rather than importing across that
boundary, which has no package relationship to `backend/` at all.

Never raises: a missing file, unreadable JSON or a missing key all read as `available=False` —
the same "measured, never invented" rule as everywhere else in this epic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

__all__ = ["BackupStatusResult", "GetBackupStatus", "read_backup_status"]

#: The format `infra/scripts/backup-once.sh`'s `date -u +%Y%m%dT%H%M%SZ` produces.
_TS_FORMAT = "%Y%m%dT%H%M%SZ"

_UNAVAILABLE = None  # readability marker for the "nothing to report" branches below


@dataclass(frozen=True, slots=True)
class BackupStatusResult:
    """`openapi.yaml`'s `BackupStatus`, property names literal."""

    available: bool
    finished_at: datetime | None
    status: Literal["OK", "FAILED"] | None
    database_bytes: int | None
    recordings_bytes: int | None
    database_sha256: str | None
    recordings_sha256: str | None


_UNAVAILABLE_RESULT = BackupStatusResult(
    available=False,
    finished_at=_UNAVAILABLE,
    status=_UNAVAILABLE,
    database_bytes=_UNAVAILABLE,
    recordings_bytes=_UNAVAILABLE,
    database_sha256=_UNAVAILABLE,
    recordings_sha256=_UNAVAILABLE,
)


def read_backup_status(path: Path) -> BackupStatusResult:
    """`last.json` at `path`, or the "unavailable" result for anything not shaped as documented."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _UNAVAILABLE_RESULT
    if not isinstance(raw, dict):
        return _UNAVAILABLE_RESULT
    ts_raw = raw.get("ts")
    if not isinstance(ts_raw, str):
        return _UNAVAILABLE_RESULT
    try:
        finished_at = datetime.strptime(ts_raw, _TS_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return _UNAVAILABLE_RESULT
    status: Literal["OK", "FAILED"] = "OK" if raw.get("status") == "ok" else "FAILED"
    return BackupStatusResult(
        available=True,
        finished_at=finished_at,
        status=status,
        database_bytes=_as_int(raw.get("dump_size_bytes")),
        recordings_bytes=_as_int(raw.get("recordings_size_bytes")),
        database_sha256=_as_str(raw.get("dump_sha256")),
        recordings_sha256=_as_str(raw.get("recordings_sha256")),
    )


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


class GetBackupStatus:
    """ADMIN only. `status_path` is `Settings.backup_status_path`."""

    def __init__(self, *, status_path: Path) -> None:
        self._status_path = status_path

    async def __call__(self) -> BackupStatusResult:
        return read_backup_status(self._status_path)
