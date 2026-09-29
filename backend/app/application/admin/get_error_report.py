"""`getErrorReport` — errors and failures over a period (ADMIN, ТЗ ¶207).

Merges, newest first:

* the backend's own rotated JSON log (`SIM_LOG_DIR/backend.log[.N]`, `source: BACKEND_LOG`) at
  level `ERROR` or above — read as plain text lines and parsed as JSON one at a time, so one
  unreadable line never hides the rest;
* (I7 E51, G6, ТЗ ¶207) the same rotated log, same directory, for the voice agent
  (`voice-agent.log[.N]`, `source: VOICE_AGENT_LOG`) and the SIP gateway (`sip-gateway.log[.N]`,
  `source: SIP_GATEWAY_LOG`) — additive: absent files (the file handler is off unless that
  process's own `SIM_LOG_DIR` is set) contribute nothing, same as an empty `SIM_LOG_DIR` today;
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

#: `app.infrastructure.logging.json_formatter.log_file_name`/`.LOG_FILE_BACKUP_COUNT`, literally —
#: not imported (D2: `app.application` may not import `app.infrastructure`), so this is the one
#: place besides that module these values must be kept in step. `service -> (file stem, source)`;
#: I7 E51 (G6) added the last two rows, one rotated log per process that shares `SIM_LOG_DIR`.
_LOG_FILE_SOURCES: tuple[tuple[str, str], ...] = (
    ("backend.log", "BACKEND_LOG"),
    ("voice-agent.log", "VOICE_AGENT_LOG"),
    ("sip-gateway.log", "SIP_GATEWAY_LOG"),
)
_LOG_FILE_BACKUP_COUNT = 10

_LOG_LEVELS_AT_OR_ABOVE_ERROR = frozenset({"ERROR", "CRITICAL"})


@dataclass(frozen=True, slots=True)
class ErrorReportItem:
    """`openapi.yaml`'s `ErrorRecordView`, property names literal."""

    ts: datetime
    source: Literal[
        "BACKEND_LOG", "VOICE_AGENT_LOG", "SIP_GATEWAY_LOG", "MODEL_ERROR", "INFERENCE_FATAL"
    ]
    message: str
    session_id: UUID | None


class GetErrorReport:
    """ADMIN only. `log_dir` is `Settings.log_dir` — empty means no file, so no `BACKEND_LOG`
    record ever appears (matches `configure_logging`'s own "console only" default). The voice
    agent and the SIP gateway are separate processes with their own `SIM_LOG_DIR`; in the shipped
    compose (I7 E51, G6) all three point at the same `logs-data` volume, so this one directory is
    where every rotated file lands."""

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
        file_logs = self._read_file_logs(resolved_from, resolved_to)
        session_events = await self._reader.session_error_events(
            from_ts=resolved_from, to_ts=resolved_to, limit=limit
        )
        merged = list(file_logs) + [
            ErrorReportItem(
                ts=event.ts, source=event.source, message=event.message, session_id=event.session_id
            )
            for event in session_events
        ]
        merged.sort(key=lambda item: item.ts, reverse=True)
        return tuple(merged[:limit])

    def _read_file_logs(self, from_ts: datetime, to_ts: datetime) -> list[ErrorReportItem]:
        if self._log_dir is None:
            return []
        items: list[ErrorReportItem] = []
        for file_stem, source in _LOG_FILE_SOURCES:
            for path in self._log_files(file_stem):
                try:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                for line in lines:
                    item = _parse_log_line(line, source=source, from_ts=from_ts, to_ts=to_ts)
                    if item is not None:
                        items.append(item)
        return items

    def _log_files(self, file_stem: str) -> list[Path]:
        if self._log_dir is None:
            return []
        base = self._log_dir / file_stem
        candidates = [base] + [
            base.with_name(f"{file_stem}.{n}") for n in range(1, _LOG_FILE_BACKUP_COUNT + 1)
        ]
        return [candidate for candidate in candidates if candidate.is_file()]


def _parse_log_line(
    line: str, *, source: str, from_ts: datetime, to_ts: datetime
) -> ErrorReportItem | None:
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
        source=source,  # type: ignore[arg-type]  # one of `_LOG_FILE_SOURCES`, all valid members
        message=message if isinstance(message, str) else "",
        session_id=None,
    )
