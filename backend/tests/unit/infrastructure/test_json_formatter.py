"""`app.infrastructure.logging.json_formatter` (I4 E25, `71-i4-wave4.md` §71.2, D31, ТЗ ¶372).

The formatter is exercised on hand-built `LogRecord`s and the dictConfig dict is inspected, never
applied, so nothing here reconfigures the test process's logging. The real processes are covered by
`test_json_logs_backend_process.py` and the voice agent's `test_json_logs.py`.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest
from app.application.ports.audit_log import AuditAction, AuditOutcome
from app.application.ports.user_repository import UserRole
from app.db.models.events import AUDIT_ACTIONS, AUDIT_OUTCOMES, AUDIT_ROLES
from app.infrastructure.logging.json_formatter import (
    BACKEND_LOG_FILE,
    JsonFormatter,
    TextFormatter,
    build_log_config,
    redact,
)


def _record(
    message: str, *args: object, level: int = logging.INFO, exc_info: object = None
) -> logging.LogRecord:
    return logging.LogRecord("app.test", level, __file__, 1, message, args, exc_info)  # type: ignore[arg-type]


def test_a_record_is_one_json_object_with_the_core_fields() -> None:
    line = JsonFormatter(service="backend").format(_record("hello %s", "мир"))
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["message"] == "hello мир"
    assert payload["service"] == "backend"
    assert payload["ts"].endswith("+00:00")
    assert "\n" not in line


def test_a_traceback_stays_on_one_line() -> None:
    try:
        raise RuntimeError("first\nsecond")
    except RuntimeError:
        exc_info = sys.exc_info()
    line = JsonFormatter().format(_record("failed", level=logging.ERROR, exc_info=exc_info))
    assert "\n" not in line
    payload = json.loads(line)
    assert payload["level"] == "ERROR"
    assert "RuntimeError: first" in payload["exc_info"]


def test_extra_fields_are_carried_and_unserialisable_ones_stringified() -> None:
    record = _record("with extra")
    record.session_id = "abc"
    record.path = Path("/tmp/x")
    payload = json.loads(JsonFormatter().format(record))
    assert payload["session_id"] == "abc"
    assert payload["path"] == "/tmp/x"


@pytest.mark.parametrize("formatter", [JsonFormatter(), TextFormatter()], ids=["json", "text"])
def test_a_token_query_value_is_redacted(formatter: logging.Formatter) -> None:
    line = formatter.format(_record('"WebSocket /api/v1/ws/sessions/1?token=eyJ.secret" accepted'))
    assert "eyJ.secret" not in line
    assert "token=[redacted]" in line


def test_redact_leaves_other_text_alone() -> None:
    assert redact("tokens are fine; token=abc&x=1") == "tokens are fine; token=[redacted]&x=1"


def test_an_unknown_format_is_refused() -> None:
    with pytest.raises(ValueError, match="SIM_LOG_FORMAT"):
        build_log_config("xml", service="backend")


def test_uvicorn_loggers_propagate_to_the_root_handlers() -> None:
    config = build_log_config("json", service="backend")
    assert config["root"]["handlers"] == ["console"]
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert config["loggers"][name] == {"level": "INFO", "handlers": [], "propagate": True}
    assert config["disable_existing_loggers"] is False


def test_the_log_dir_adds_a_rotated_file_that_is_always_json(tmp_path: Path) -> None:
    config = build_log_config("text", service="backend", log_dir=str(tmp_path / "logs"))
    assert config["handlers"]["console"]["formatter"] == "text"
    handler = config["handlers"]["file"]
    assert handler["class"] == "logging.handlers.RotatingFileHandler"
    assert handler["formatter"] == "json"
    assert handler["filename"] == str(tmp_path / "logs" / BACKEND_LOG_FILE)
    assert handler["maxBytes"] > 0 and handler["backupCount"] > 0
    assert (tmp_path / "logs").is_dir()
    assert config["root"]["handlers"] == ["console", "file"]


def test_the_audit_enums_match_the_table_check_lists() -> None:
    """The port's enums and `audit_log`'s CHECK lists are one set each (HLD 20 §20.6)."""
    assert tuple(member.value for member in AuditAction) == AUDIT_ACTIONS
    assert tuple(member.value for member in AuditOutcome) == AUDIT_OUTCOMES
    assert tuple(member.value for member in UserRole) == AUDIT_ROLES
