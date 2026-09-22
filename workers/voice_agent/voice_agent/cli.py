"""`python -m voice_agent.cli health` — the voice-agent container's healthcheck (E18-E, HLD 60 §9).

A compose healthcheck has to answer one question with an exit code, from *inside* the container,
without a shell full of tools: is this voice-agent serving? The voice-agent publishes no host port
and runs no API, so the only thing in the container that can be asked is the loopback preflight
endpoint `voice_agent.preflight_http` binds after warm-up (`SIM_VOICE_AGENT_HTTP_PORT`, default
8113). That is exactly the right thing to ask, and it is why the server starts *after* the warm-up
sequence: a socket that answers at all means the process is up, warmed and holding its models.

    healthy   exit 0   `GET /preflight/tts` answered 200 (or, with `--any`, answered at all)
    unhealthy exit 1   nothing is listening, the probe failed, or the model did not respond

`--any` is the looser reading: the endpoint answered, whatever it said. It exists because
`/preflight/tts` runs a real synthesis, and a healthcheck on a 10-second interval must not spend
GPU time on every tick. The compose healthcheck uses the default (a connection check only, via
`--connect`), and `preflight` proper is what actually exercises the models.

Deliberately stdlib-only and import-light: it must start fast and must not pull in `Settings`, the
database engine or any model package to answer a yes/no question.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys

from voice_agent.preflight_http import (
    DEFAULT_PREFLIGHT_HTTP_PORT,
    LOOPBACK_HOST,
    PREFLIGHT_TTS_PATH,
)

__all__ = ["main"]

_CONNECT_TIMEOUT_S = 3.0
_PROBE_TIMEOUT_S = 30.0


def _port() -> int:
    raw = os.environ.get("SIM_VOICE_AGENT_HTTP_PORT", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_PREFLIGHT_HTTP_PORT


async def _connect_only(port: int) -> tuple[bool, str]:
    """Is something listening on the loopback preflight port? No model time spent."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(LOOPBACK_HOST, port), timeout=_CONNECT_TIMEOUT_S
        )
    except Exception as exc:
        return False, f"nothing is listening on {LOOPBACK_HOST}:{port} ({type(exc).__name__})"
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    del reader
    return True, f"the preflight endpoint is listening on {LOOPBACK_HOST}:{port}"


async def _probe(port: int, *, accept_any_status: bool) -> tuple[bool, str]:
    """`GET /preflight/tts` and read the status line (a ~20-line HTTP client, no dependency)."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(LOOPBACK_HOST, port), timeout=_CONNECT_TIMEOUT_S
        )
    except Exception as exc:
        return False, f"nothing is listening on {LOOPBACK_HOST}:{port} ({type(exc).__name__})"
    try:
        writer.write(
            f"GET {PREFLIGHT_TTS_PATH} HTTP/1.1\r\nHost: {LOOPBACK_HOST}\r\n"
            "Connection: close\r\n\r\n".encode("latin-1")
        )
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(), timeout=_PROBE_TIMEOUT_S)
    except Exception as exc:
        return False, f"the preflight probe failed: {type(exc).__name__}: {exc}"
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()

    head, _, body = raw.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
    parts = status_line.split()
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    if accept_any_status and status:
        return True, f"the preflight endpoint answered {status}"
    if status == 200:
        return True, f"tts responded: {body.decode('utf-8', errors='replace')[:200]}"
    return False, f"{PREFLIGHT_TTS_PATH} answered {status or 'nothing parseable'}"


def main(argv: list[str] | None = None) -> int:
    """`health` sub-command: exit 0 when the agent is serving, 1 when it is not."""
    parser = argparse.ArgumentParser(prog="python -m voice_agent.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    health = sub.add_parser("health", help="is this voice-agent up and warmed? (exit 0/1)")
    health.add_argument(
        "--connect",
        action="store_true",
        default=True,
        help="only check that the preflight endpoint is listening (the default: no model time)",
    )
    health.add_argument(
        "--probe",
        action="store_true",
        help=f"actually call {PREFLIGHT_TTS_PATH}; spends GPU time, so never on a short interval",
    )
    health.add_argument(
        "--any",
        action="store_true",
        help="with --probe: any HTTP answer counts as healthy, not only 200",
    )
    health.add_argument("--json", action="store_true", help="print the verdict as JSON")
    args = parser.parse_args(argv)

    port = _port()
    if args.probe:
        healthy, detail = asyncio.run(_probe(port, accept_any_status=args.any))
    else:
        healthy, detail = asyncio.run(_connect_only(port))

    if args.json:
        print(json.dumps({"healthy": healthy, "port": port, "detail": detail}))
    else:
        print(f"{'OK' if healthy else 'FAIL'}  voice-agent  {detail}")
    return 0 if healthy else 1


if __name__ == "__main__":  # pragma: no cover - process entry
    sys.exit(main())
