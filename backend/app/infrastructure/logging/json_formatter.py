"""One JSON object per log line, for every process (I4 E25, `71-i4-wave4.md` §71.2, D31, ТЗ ¶372
«JSON для логов и журналов»).

Stdlib only — no dependency — because three processes use it: the backend (wired into uvicorn's
loggers and the app's own by `configure_logging`, called from `app.api.main.create_app`), the
voice agent and the SIP gateway (both replace their `logging.basicConfig` with it).

* `JsonFormatter` renders a record as one line: `ts` (UTC, ISO 8601, milliseconds), `level`,
  `logger`, `message`, `service`, plus `exc_info`/`stack_info` when present and any `extra=`
  field. `json.dumps` escapes every newline, so a multi-line traceback is still one line.
* `SIM_LOG_FORMAT=json|text` chooses the console format (`json` is the default); `text` keeps the
  old human `%(asctime)s %(levelname)s %(name)s: %(message)s` line.
* `SIM_LOG_DIR` (backend only) adds a rotated file, `backend.log`, that is **always** JSON
  whatever the console format — it is what E29's error report parses.

Both formatters redact a `token=` query value (a WebSocket URL carries the bearer token there,
HLD 40 §40.1) before the line is written anywhere (SPEC §41: a token is never logged).
"""

from __future__ import annotations

import json
import logging
import logging.config
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "BACKEND_LOG_FILE",
    "LOG_FORMATS",
    "JsonFormatter",
    "LogFormat",
    "TextFormatter",
    "build_log_config",
    "configure_logging",
    "log_file_name",
    "redact",
]

LogFormat = Literal["json", "text"]
LOG_FORMATS: tuple[str, ...] = ("json", "text")

#: The backend's rotated JSON log under `SIM_LOG_DIR`.
BACKEND_LOG_FILE = "backend.log"


def log_file_name(service: str) -> str:
    """`{service}.log` — `"backend"` gives `BACKEND_LOG_FILE` itself; I7 E51 (G6, ТЗ ¶207) extends
    the same rotated-file handler to the voice agent and the SIP gateway (`voice-agent.log`,
    `sip-gateway.log`), which `GetErrorReport` also reads once `SIM_LOG_DIR` is set for them."""
    return f"{service}.log"


#: Rotation: ten files of 10 MiB each — bounded, and days of a classroom's volume.
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 10

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

#: The uvicorn loggers, re-pointed at the root handlers so their lines share one format.
_UVICORN_LOGGERS: tuple[str, ...] = ("uvicorn", "uvicorn.error", "uvicorn.access")

_TOKEN_QUERY = re.compile(r"(\btoken=)[^&\s\"']+")

#: Every attribute a plain `LogRecord` has; anything else on a record came from `extra=`.
_STANDARD_ATTRS: frozenset[str] = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
) | {"message", "asctime", "taskName", "color_message"}


def redact(text: str) -> str:
    """`text` with every `token=<value>` query value replaced (SPEC §41)."""
    return _TOKEN_QUERY.sub(r"\1[redacted]", text)


class JsonFormatter(logging.Formatter):
    """One JSON object per record, on one line."""

    def __init__(self, service: str | None = None) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if self._service is not None:
            payload["service"] = self._service
        if record.exc_info:
            payload["exc_info"] = redact(self.formatException(record.exc_info))
        elif record.exc_text:
            payload["exc_info"] = redact(record.exc_text)
        if record.stack_info:
            payload["stack_info"] = redact(self.formatStack(record.stack_info))
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and key not in payload:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """The human line `SIM_LOG_FORMAT=text` keeps, with the same redaction as the JSON one."""

    def __init__(self) -> None:
        super().__init__(TEXT_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def build_log_config(
    log_format: str,
    *,
    service: str,
    level: str = "INFO",
    log_dir: str | None = None,
) -> dict[str, Any]:
    """A `logging.config.dictConfig` dict: console in `log_format`, plus the JSON file when
    `log_dir` is set. Uvicorn's own loggers lose their handlers and propagate to the root one."""
    if log_format not in LOG_FORMATS:
        raise ValueError(f"SIM_LOG_FORMAT={log_format!r} is not one of {', '.join(LOG_FORMATS)}")
    formatters: dict[str, Any] = {
        "json": {"()": JsonFormatter, "service": service},
        "text": {"()": TextFormatter},
    }
    handlers: dict[str, Any] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": log_format,
            "stream": "ext://sys.stderr",
        }
    }
    if log_dir:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": str(directory / log_file_name(service)),
            "maxBytes": LOG_FILE_MAX_BYTES,
            "backupCount": LOG_FILE_BACKUP_COUNT,
            "encoding": "utf-8",
        }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "handlers": handlers,
        "root": {"level": level.upper(), "handlers": list(handlers)},
        "loggers": {
            name: {"level": level.upper(), "handlers": [], "propagate": True}
            for name in _UVICORN_LOGGERS
        },
    }


def configure_logging(
    log_format: str,
    *,
    service: str,
    level: str = "INFO",
    log_dir: str | None = None,
) -> None:
    """Apply `build_log_config` to this process."""
    logging.config.dictConfig(
        build_log_config(log_format, service=service, level=level, log_dir=log_dir)
    )
