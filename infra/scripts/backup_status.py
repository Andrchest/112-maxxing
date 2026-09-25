"""Parse and verify `backups/last.json` (I4 E26, docs/hld/71-i4-wave4.md §71.3, D33).

Stdlib only (repo facts: "Bash 5.2 + Python 3.10 (stdlib only)") — this is a plain script, not part
of the `backend`/`voice-agent` packages, run on the HOST (`make backup-verify`), never inside the
`backup` compose service itself (that image has no python3, see backup-once.sh's header comment).

`last.json`'s shape (written by infra/scripts/backup-once.sh):
    {
      "ts": "<UTC ISO-8601, e.g. 20260925T120000Z>",
      "status": "ok" | "failed",
      "dump_file": "<filename under the same directory>",
      "dump_size_bytes": <int>,
      "dump_sha256": "<hex>" | null,
      "recordings_file": "<filename under the same directory>",
      "recordings_size_bytes": <int>,
      "recordings_sha256": "<hex>" | null,
      "error": "<short reason>" | null
    }

`purgeRecordings`'s `409 BACKUP_REQUIRED` guard (S5/E29, ¶216) and `listAdminAlerts`'
BACKUP_STALE/BACKUP_FAILED (§71.3 puml note) are a DIFFERENT reader, written in E29's own backend
code — this module is not imported by the backend; it exists only for this epic's own
`make backup-verify` CLI check. The 26h staleness threshold below is chosen to match that puml
note's number, so an operator running `backup-verify` sees the same verdict E29's alert would.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_MAX_AGE_HOURS = 26
REQUIRED_KEYS = (
    "ts",
    "status",
    "dump_file",
    "dump_size_bytes",
    "dump_sha256",
    "recordings_file",
    "recordings_size_bytes",
    "recordings_sha256",
    "error",
)
# The format backup-once.sh's `date -u +%Y%m%dT%H%M%SZ` produces.
TS_FORMAT = "%Y%m%dT%H%M%SZ"


class BackupStatusError(ValueError):
    """`last.json` is missing, malformed, or missing a required key."""


@dataclass(frozen=True)
class BackupStatus:
    ts: datetime
    status: str
    dump_file: str
    dump_size_bytes: int
    dump_sha256: str | None
    recordings_file: str
    recordings_size_bytes: int
    recordings_sha256: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def age_hours(self, now: datetime | None = None) -> float:
        now = now or datetime.now(UTC)
        return (now - self.ts).total_seconds() / 3600.0


def read_status(path: Path) -> BackupStatus:
    """Parse `last.json` at `path`. Raises `BackupStatusError` for anything not shaped as above —
    never a bare `KeyError`/`ValueError`, so a caller can report one clean reason."""
    if not path.is_file():
        raise BackupStatusError(f"{path} does not exist")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BackupStatusError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise BackupStatusError(f"{path} does not contain a JSON object")
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        raise BackupStatusError(f"{path} is missing key(s): {', '.join(missing)}")
    try:
        ts = datetime.strptime(raw["ts"], TS_FORMAT).replace(tzinfo=UTC)
    except (TypeError, ValueError) as exc:
        raise BackupStatusError(f"{path}'s ts {raw['ts']!r} is not {TS_FORMAT}") from exc
    if raw["status"] not in ("ok", "failed"):
        raise BackupStatusError(f"{path}'s status {raw['status']!r} is neither 'ok' nor 'failed'")
    return BackupStatus(
        ts=ts,
        status=raw["status"],
        dump_file=raw["dump_file"],
        dump_size_bytes=int(raw["dump_size_bytes"]),
        dump_sha256=raw["dump_sha256"],
        recordings_file=raw["recordings_file"],
        recordings_size_bytes=int(raw["recordings_size_bytes"]),
        recordings_sha256=raw["recordings_sha256"],
        error=raw["error"],
    )


def verify(path: Path, max_age_hours: float = DEFAULT_MAX_AGE_HOURS) -> tuple[bool, str]:
    """Returns (passed, message). Never raises for an expected failure mode (missing file,
    malformed JSON, failed backup, stale backup) — those are all `passed=False` with a reason."""
    try:
        status = read_status(path)
    except BackupStatusError as exc:
        return False, str(exc)
    if not status.ok:
        return False, f"last backup at {status.ts.isoformat()} FAILED: {status.error}"
    age = status.age_hours()
    if age > max_age_hours:
        return (
            False,
            f"last backup at {status.ts.isoformat()} is {age:.1f}h old (> {max_age_hours}h)",
        )
    return True, (
        f"OK: {status.dump_file} ({status.dump_size_bytes}B) + {status.recordings_file} "
        f"({status.recordings_size_bytes}B), {age:.1f}h ago"
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", type=Path, default=Path("backups/last.json"))
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    args = parser.parse_args(argv)
    passed, message = verify(args.path, args.max_age_hours)
    print(message)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(_main())
