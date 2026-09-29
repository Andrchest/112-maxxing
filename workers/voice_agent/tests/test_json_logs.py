"""The voice agent and the SIP gateway log one JSON object per line (I4 E25, `71-i4-wave4.md`
§71.2, D31): both entry points replaced `logging.basicConfig` with `configure_logging`.

Each process runs in a subprocess (it reconfigures logging for the whole interpreter) with its
serving coroutine replaced by a stub that logs, so the real `main()` is what configures logging
and nothing binds a port, dials Redis or loads a model.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

_VOICE_AGENT = """
import logging
import voice_agent.main as entry

async def stub_run():
    logging.getLogger("voice_agent.main").info("probe voice agent")
    try:
        raise RuntimeError("boom\\nsecond line")
    except RuntimeError:
        logging.getLogger("voice_agent.main").exception("probe failure")

entry.run = stub_run
entry.main()
"""

_SIP_GATEWAY = """
import logging
import voice_agent.sip_gateway as entry

async def stub_serve(config):
    logging.getLogger("voice_agent.sip_gateway").info("probe gateway on %s", config.sip_port)

entry.serve = stub_serve
raise SystemExit(entry.main([]))
"""


def _run(script: str, log_format: str | None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "SIM_ENV_FILE": "",
        "SIM_SIP_PASSWORD": "e25-probe",
        "SIM_SIP_PORT": "5099",
        # I7 E44: plain transports only — with the default `tls,udp,tcp` and no certificate the
        # gateway logs one more (JSON) line, the "TLS is OFF" warning.
        "SIM_SIP_TRANSPORTS": "udp,tcp",
    }
    env.pop("SIM_SIP_BACKEND_URL", None)
    env.pop("SIM_LOG_FORMAT", None)
    if log_format is not None:
        env["SIM_LOG_FORMAT"] = log_format
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _records(stderr: str) -> list[dict[str, object]]:
    lines = [line for line in stderr.splitlines() if line.strip()]
    assert lines, "no log line was written"
    return [json.loads(line) for line in lines]  # raises on any line that is not one object


@pytest.mark.parametrize("log_format", [None, "json"], ids=["default", "explicit"])
def test_the_voice_agent_logs_json(log_format: str | None) -> None:
    result = _run(_VOICE_AGENT, log_format)
    assert result.returncode == 0, result.stderr
    records = _records(result.stderr)
    assert [record["message"] for record in records] == ["probe voice agent", "probe failure"]
    assert all(record["service"] == "voice-agent" for record in records)
    assert "RuntimeError: boom" in str(records[1]["exc_info"])


@pytest.mark.parametrize("log_format", [None, "json"], ids=["default", "explicit"])
def test_the_sip_gateway_logs_json(log_format: str | None) -> None:
    result = _run(_SIP_GATEWAY, log_format)
    assert result.returncode == 0, result.stderr
    (record,) = _records(result.stderr)
    assert record["message"] == "probe gateway on 5099"
    assert record["service"] == "sip-gateway"
    assert record["logger"] == "voice_agent.sip_gateway"


def test_text_keeps_the_old_human_line() -> None:
    result = _run(_SIP_GATEWAY, "text")
    assert result.returncode == 0, result.stderr
    assert "INFO voice_agent.sip_gateway: probe gateway on 5099" in result.stderr
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stderr.splitlines()[0])
