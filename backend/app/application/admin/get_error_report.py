"""`getErrorReport` — errors and failures over a period (ADMIN, ТЗ ¶207).

Merges, newest first:

* the backend's own rotated JSON log (`SIM_LOG_DIR/backend.log[.N]`, `source: BACKEND_LOG`) at
  level `ERROR` or above — read as plain text lines and parsed as JSON one at a time, so one
  unreadable line never hides the rest;
* `MODEL_ERROR` and FATAL `INFERENCE_HEALTH_CHANGED` session events, across every session
  (`AdminMonitoringReader.session_error_events`, `source: MODEL_ERROR` / `INFERENCE_FATAL`).

`from`/`to` default the same `DEFAULT_WINDOW_DAYS`-day window `getUsageStats` does (a technical
choice, for the same reason: the delta leaves both optional and states no default).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.application.admin.get_usage_stats import DEFAULT_WINDOW_DAYS
from app.application.ports.admin_monitoring import AdminMonitoringReader
from app.application.ports.clock import Clock

__all__ = ["ErrorReportItem", "GetErrorReport"]

#: `app.infrastructure.logging.json_formatter.BACKEND_LOG_FILE` /`.LOG_FILE_BACKUP_COUNT`,
#: literally — not imported (D2: `app.application` may not import `app.infrastructure`), so this
#: is the one place besides that module the two values must be kept in step; both are one-line,
#: stable constants (`"backend.log"`, ten rotated backups).
_BACKEND_LOG_FILE = "backend.log"
_LOG_FILE_BACKUP_COUNT = 10

_LOG_LEVELS_AT_OR_ABOVE_ERROR = frozenset({"ERROR", "CRITICAL"})


@dataclass(frozen=True, slots=True)
class ErrorReportItem:
    """`openapi.yaml`'s `ErrorRecordView`, property names literal."""

    ts: datetime
    source: Literal["BACKEND_LOG", "MODEL_ERROR", "INFERENCE_FATAL"]
    message: str
    session_id: UUID | None


class GetErrorReport:
    """ADMIN only. `log_dir` is `Settings.log_dir` — empty means no file, so no `BACKEND_LOG`
    record ever appears (matches `configure_logging`'s own "console only" default)."""

    def __init__(self, reader: AdminMonitoringReader, clock: Clock, *, log_dir: str) -> None:
        self._reader = reader
        self._clock = clock
        self._log_dir = Path(log_dir) if log_dir else None

    async def __call__(
        self,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        limit: int = 100,
    ) -> tuple[ErrorReportItem, ...]:
        resolved_to = to_ts if to_ts is not None else self._clock.now()
        resolved_from = (
            from_ts if from_ts is not None else resolved_to - timedelta(days=DEFAULT_WINDOW_DAYS)
        )
        backend_log = self._read_backend_log(resolved_from, resolved_to)
        session_events = await self._reader.session_error_events(
            from_ts=resolved_from, to_ts=resolved_to, limit=limit
        )
        merged = list(backend_log) + [
            ErrorReportItem(
                ts=event.ts, source=event.source, message=event.message, session_id=event.session_id
            )
            for event in session_events
        ]
        merged.sort(key=lambda item: item.ts, reverse=True)
        return tuple(merged[:limit])

    def _read_backend_log(self, from_ts: datetime, to_ts: datetime) -> list[ErrorReportItem]:
        if self._log_dir is None:
            return []
        items: list[ErrorReportItem] = []
        for path in self._log_files():
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                item = _parse_log_line(line, from_ts=from_ts, to_ts=to_ts)
                if item is not None:
                    items.append(item)
        return items

    def _log_files(self) -> list[Path]:
        if self._log_dir is None:
            return []
        base = self._log_dir / _BACKEND_LOG_FILE
        candidates = [base] + [
            base.with_name(f"{_BACKEND_LOG_FILE}.{n}") for n in range(1, _LOG_FILE_BACKUP_COUNT + 1)
        ]
        return [candidate for candidate in candidates if candidate.is_file()]


def _parse_log_line(line: str, *, from_ts: datetime, to_ts: datetime) -> ErrorReportItem | None:
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    if record.get("level") not in _LOG_LEVELS_AT_OR_ABOVE_ERROR:
        return None
    ts_raw = record.get("ts")
    if not isinstance(ts_raw, str):
        return None
    try:
        ts = datetime.fromisoformat(ts_raw)
    except ValueError:
        return None
    if ts < from_ts or ts >= to_ts:
        return None
    message = record.get("message")
    return ErrorReportItem(
        ts=ts,
        source="BACKEND_LOG",
        message=message if isinstance(message, str) else "",
        session_id=None,
    )
