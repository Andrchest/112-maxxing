"""The backend process logs one JSON object per line (I4 E25, `71-i4-wave4.md` §71.2, D31).

Run in a subprocess, because it reconfigures the process's logging exactly as production does: a
real `uvicorn.Config("app.api.main:create_app", factory=True).load()` — uvicorn applies its own
default `log_config`, then calls the factory, which re-points uvicorn's loggers and the app's own
at the JSON formatter. No socket is bound (`load()` only imports and builds the app), and nothing
connects to PostgreSQL or Redis (the container creates its clients lazily).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

_SCRIPT = """
import logging
import uvicorn

config = uvicorn.Config("app.api.main:create_app", factory=True, log_level="info")
config.load()
logging.getLogger("uvicorn.error").info("probe uvicorn.error")
logging.getLogger("uvicorn.access").info(
    '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET",
    "/api/v1/ws/sessions/1?token=e25-secret-token", "1.1", 200,
)
logging.getLogger("app.api.main").warning("probe app")
try:
    raise RuntimeError("boom\\nsecond line")
except RuntimeError:
    logging.getLogger("app.infrastructure").exception("probe error")
"""


def _run(tmp_path: Path, log_format: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "SIM_ENV_FILE": "",
        "SIM_LOG_FORMAT": log_format,
        "SIM_LOG_DIR": str(tmp_path / "logs"),
        "SIM_DATABASE_URL": "postgresql+asyncpg://sim:sim@127.0.0.1:1/none",
        "SIM_REDIS_URL": "redis://127.0.0.1:1/0",
        "SIM_JWT_SECRET": "test-only-secret-padded-32-bytes!",
        "SIM_LIVEKIT_URL": "ws://127.0.0.1:7880",
        "SIM_LIVEKIT_API_KEY": "devkey",
        "SIM_LIVEKIT_API_SECRET": "devsecret1234567890",
        "SIM_LLM_BASE_URL": "http://127.0.0.1:8080/v1",
        "SIM_MODEL_PROFILE": "DEV_3060TI",
    }
    return subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _json_lines(text: str) -> list[dict[str, object]]:
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines, "no log line was written"
    return [json.loads(line) for line in lines]  # raises on any line that is not one object


def test_uvicorn_and_the_app_log_one_json_object_per_line(tmp_path: Path) -> None:
    result = _run(tmp_path, "json")
    assert result.returncode == 0, result.stderr
    records = _json_lines(result.stderr)
    by_logger = {str(record["logger"]): record for record in records}
    assert {"uvicorn.error", "uvicorn.access", "app.api.main", "app.infrastructure"} <= set(
        by_logger
    )
    assert all(record["service"] == "backend" for record in records)
    assert "RuntimeError: boom" in str(by_logger["app.infrastructure"]["exc_info"])
    assert "e25-secret-token" not in result.stderr


def test_the_log_dir_file_is_json_even_when_the_console_is_text(tmp_path: Path) -> None:
    result = _run(tmp_path, "text")
    assert result.returncode == 0, result.stderr
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stderr.splitlines()[0])
    records = _json_lines((tmp_path / "logs" / "backend.log").read_text(encoding="utf-8"))
    assert {"ERROR", "WARNING", "INFO"} <= {str(record["level"]) for record in records}
    assert "e25-secret-token" not in (tmp_path / "logs" / "backend.log").read_text("utf-8")
