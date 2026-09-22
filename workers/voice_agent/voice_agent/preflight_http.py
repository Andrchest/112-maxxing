"""The voice-agent's loopback preflight endpoints — HLD 60 §5 checks 5 and 6 (SPEC §38).

Preflight (`uv run python -m app.cli preflight`) runs in the **backend** process and loads no ML
model (§5: "it probes services and files, so it is fast and can run in CI against fakes"). Two of
its eleven checks are nevertheless about models — "ASR responds" and "TTS responds" — and the only
process that has an ASR and a TTS model loaded is this one. §5 resolves that by making checks 5/6
out-of-process HTTP probes:

* `GET /preflight/asr` — transcribe the warm-up sample with the **already loaded** provider and
  answer `{"text": ..., "latency_ms": ...}`. PASS is HTTP 200 with non-empty `text`.
* `GET /preflight/tts` — synthesise `warmup.tts_text` and answer
  `{"output_audio_ms": ..., "latency_ms": ...}`. PASS is HTTP 200 with `output_audio_ms > 0`.

Neither probe loads anything: a component that has not been warmed answers 503, which is the
truthful answer ("ASR does not respond") rather than a lazy load that would make a preflight the
slowest thing in the stack and could OOM the card the preflight exists to protect.

**Loopback only.** `bind_host` must be a loopback address; anything else raises
`NonLoopbackBindError` at construction, so a misconfigured deployment fails to start rather than
exposing a model endpoint on the network (SPEC §41). The compose service publishes no host port for
this either (R10).

**Stdlib only.** `asyncio.start_server` plus ~40 lines of request-line parsing, not a second web
framework: the voice-agent process has no HTTP server dependency of its own today and two tiny GET
endpoints are not a reason to acquire one. Anything but a `GET` of one of the two known paths is a
404/405 problem document; the parser reads the request line and headers, discards any body, and
answers one response per connection (`Connection: close`).

Every failure body is an RFC 7807-shaped problem document, the same shape the API uses, so the
preflight CLI can report `detail` verbatim in its FAIL row.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

__all__ = [
    "DEFAULT_PREFLIGHT_HTTP_PORT",
    "LOOPBACK_HOST",
    "PREFLIGHT_ASR_PATH",
    "PREFLIGHT_TTS_PATH",
    "NonLoopbackBindError",
    "PreflightHttpServer",
    "resolve_preflight_port",
]

logger = logging.getLogger(__name__)

#: `SIM_VOICE_AGENT_HTTP_PORT`'s default (the E18 brief's machine rules: ours, never the owner's
#: 8000/8001/8011/8012/8016).
DEFAULT_PREFLIGHT_HTTP_PORT = 8113
LOOPBACK_HOST = "127.0.0.1"

PREFLIGHT_ASR_PATH = "/preflight/asr"
PREFLIGHT_TTS_PATH = "/preflight/tts"

#: `Probe` answers the JSON body of a successful check, or raises. Injected so both endpoints are
#: unit-testable without a model: the real ones close over the process's warmed providers.
Probe = Callable[[], Awaitable[dict[str, Any]]]

_PROBLEM_CONTENT_TYPE = "application/problem+json"
_JSON_CONTENT_TYPE = "application/json"
_MAX_REQUEST_BYTES = 16 * 1024
_READ_TIMEOUT_S = 10.0


class NonLoopbackBindError(ValueError):
    """`bind_host` is not a loopback address (SPEC §41).

    Raised at construction, not at `start()`, so the mistake is found before a socket exists.
    """


def _is_loopback(host: str) -> bool:
    """True only for a literal loopback address or the name `localhost`.

    No DNS resolution, exactly as `app.inference.loopback` decided for the provider base URLs: a
    name that merely *resolves* to loopback today is not a loopback bind address, and a name that
    merely *contains* `localhost` is not `localhost`.
    """
    candidate = host.strip().strip("[]").lower()
    if candidate == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def resolve_preflight_port(settings: Any) -> int:
    """`SIM_VOICE_AGENT_HTTP_PORT` → the port to bind (default 8113).

    Read off `Settings` when the field exists and from the environment otherwise: the field is
    E18-A's to add to `app.config.settings.Settings` and this resolver picks it up the moment it
    does, without this module — or `main.py` — changing again. Until then `.env.example`'s
    documented variable still works, which is what matters for a compose deployment.
    """
    from_settings = getattr(settings, "voice_agent_http_port", None)
    if isinstance(from_settings, int) and from_settings > 0:
        return from_settings
    import os

    raw = os.environ.get("SIM_VOICE_AGENT_HTTP_PORT", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_PREFLIGHT_HTTP_PORT


class PreflightHttpServer:
    """`GET /preflight/asr` and `GET /preflight/tts` on loopback (§5 checks 5-6)."""

    def __init__(
        self,
        *,
        asr_probe: Probe,
        tts_probe: Probe,
        host: str = LOOPBACK_HOST,
        port: int = DEFAULT_PREFLIGHT_HTTP_PORT,
    ) -> None:
        if not _is_loopback(host):
            raise NonLoopbackBindError(
                f"the voice-agent preflight endpoint may only bind loopback, not {host!r} "
                "(SPEC §41: local operation; it exposes a model, and no host port is published)"
            )
        self._asr_probe = asr_probe
        self._tts_probe = tts_probe
        self._host = host
        self._port = port
        self._server: asyncio.AbstractServer | None = None

    @property
    def port(self) -> int:
        """The bound port — the real one after `start()` when 0 was requested."""
        server = self._server
        if server is not None and server.sockets:
            bound: int = server.sockets[0].getsockname()[1]
            return bound
        return self._port

    @property
    def started(self) -> bool:
        """Whether a socket is listening."""
        return self._server is not None

    async def start(self) -> None:
        """Bind and serve in the background. Idempotent."""
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        logger.info("voice-agent preflight HTTP listening on %s:%d", self._host, self.port)

    async def stop(self) -> None:
        """Close the listening socket and wait for it. Idempotent."""
        server = self._server
        if server is None:
            return
        self._server = None
        server.close()
        try:
            await server.wait_closed()
        except Exception:  # pragma: no cover - a close race is not worth failing shutdown over
            logger.debug("closing the preflight HTTP server raised", exc_info=True)

    # -- the (very small) HTTP layer -----------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            method, path = await self._read_request(reader)
            status, content_type, body = await self._route(method, path)
            await self._write(writer, status, content_type, body)
        except (TimeoutError, ConnectionError, asyncio.IncompleteReadError):
            logger.debug("a preflight HTTP connection went away before it was answered")
        except Exception:
            logger.exception("the preflight HTTP handler failed")
        finally:
            writer.close()
            # A peer that has already gone away is not a failure worth logging.
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _read_request(self, reader: asyncio.StreamReader) -> tuple[str, str]:
        """Read the request line and drain the headers; the body is ignored (both are GETs)."""
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=_READ_TIMEOUT_S)
        if len(header) > _MAX_REQUEST_BYTES:
            raise ValueError("preflight request header too large")
        request_line = header.split(b"\r\n", 1)[0].decode("latin-1")
        parts = request_line.split()
        if len(parts) < 2:
            raise ValueError(f"malformed HTTP request line {request_line!r}")
        return parts[0].upper(), parts[1].split("?", 1)[0]

    async def _route(self, method: str, path: str) -> tuple[int, str, bytes]:
        if path not in (PREFLIGHT_ASR_PATH, PREFLIGHT_TTS_PATH):
            return self._problem(404, "Not Found", f"no preflight endpoint at {path}")
        if method != "GET":
            return self._problem(
                405, "Method Not Allowed", f"{path} is a GET; {method} is not allowed"
            )
        probe = self._asr_probe if path == PREFLIGHT_ASR_PATH else self._tts_probe
        component = "asr" if path == PREFLIGHT_ASR_PATH else "tts"
        try:
            payload = await probe()
        except Exception as exc:
            logger.warning("preflight %s probe failed: %s", component, exc)
            return self._problem(
                503,
                "Service Unavailable",
                f"the {component} provider did not respond: {type(exc).__name__}: {exc}",
            )
        return 200, _JSON_CONTENT_TYPE, _dump(payload)

    def _problem(self, status: int, title: str, detail: str) -> tuple[int, str, bytes]:
        return (
            status,
            _PROBLEM_CONTENT_TYPE,
            _dump({"type": "about:blank", "title": title, "status": status, "detail": detail}),
        )

    async def _write(
        self, writer: asyncio.StreamWriter, status: int, content_type: str, body: bytes
    ) -> None:
        reason = _REASONS.get(status, "OK")
        head = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("latin-1")
        writer.write(head + body)
        await writer.drain()


_REASONS = {
    200: "OK",
    404: "Not Found",
    405: "Method Not Allowed",
    503: "Service Unavailable",
}


def _dump(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")
