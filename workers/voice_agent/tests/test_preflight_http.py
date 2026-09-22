"""`voice_agent.preflight_http` — HLD 60 §5 checks 5 and 6, over loopback (E18-C).

Real sockets, on an ephemeral port (`port=0`), because the thing under test *is* a socket server:
the loopback rule, the two routes and the 503 problem body are all properties of what comes back
over TCP. Nothing here loads a model — both probes are injected callables, which is exactly how the
real ones reach the process's already-warmed providers.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from voice_agent.preflight_http import (
    DEFAULT_PREFLIGHT_HTTP_PORT,
    PREFLIGHT_ASR_PATH,
    PREFLIGHT_TTS_PATH,
    NonLoopbackBindError,
    PreflightHttpServer,
    resolve_preflight_port,
)


async def _get(port: int, path: str, *, method: str = "GET") -> tuple[int, dict[str, Any]]:
    """One request, one response, `Connection: close` — the server's whole contract."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode(
            "latin-1"
        )
    )
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(), timeout=5)
    writer.close()
    await writer.wait_closed()
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n", 1)[0].split()[1])
    return status, json.loads(body) if body else {}


async def _server(asr: Any, tts: Any) -> PreflightHttpServer:
    server = PreflightHttpServer(asr_probe=asr, tts_probe=tts, port=0)
    await server.start()
    return server


async def _ok_asr() -> dict[str, Any]:
    return {"text": "алло, я вас слушаю", "latency_ms": 42}


async def _ok_tts() -> dict[str, Any]:
    return {"output_audio_ms": 640, "latency_ms": 310}


async def _boom() -> dict[str, Any]:
    raise RuntimeError("no ASR provider is loaded in this process")


# -- the loopback rule (SPEC §41) --------------------------------------------------------------


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "192.168.1.10", "::", "localhost.evil.com", "127.0.0.1.nip.io", ""]
)
def test_a_non_loopback_bind_address_is_refused_at_construction(host: str) -> None:
    """It exposes a model. A name that merely *resolves* to loopback is not loopback (no DNS)."""
    with pytest.raises(NonLoopbackBindError, match="loopback"):
        PreflightHttpServer(asr_probe=_ok_asr, tts_probe=_ok_tts, host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5"])
def test_every_loopback_spelling_is_accepted(host: str) -> None:
    server = PreflightHttpServer(asr_probe=_ok_asr, tts_probe=_ok_tts, host=host)
    assert server.started is False


def test_the_default_port_is_ours_and_never_the_owner_s(monkeypatch: pytest.MonkeyPatch) -> None:
    """The E18 brief's machine rules: 8113, never 8000/8001/8011/8012/8016."""
    assert DEFAULT_PREFLIGHT_HTTP_PORT == 8113
    monkeypatch.delenv("SIM_VOICE_AGENT_HTTP_PORT", raising=False)
    assert resolve_preflight_port(object()) == 8113
    monkeypatch.setenv("SIM_VOICE_AGENT_HTTP_PORT", "8199")
    assert resolve_preflight_port(object()) == 8199

    class _WithField:
        voice_agent_http_port = 8123

    assert resolve_preflight_port(_WithField()) == 8123


# -- the two checks ----------------------------------------------------------------------------


async def test_the_asr_check_answers_text_and_latency() -> None:
    """§5 check 5: "HTTP 200 and non-empty text"."""
    server = await _server(_ok_asr, _ok_tts)
    try:
        status, body = await _get(server.port, PREFLIGHT_ASR_PATH)
    finally:
        await server.stop()
    assert status == 200
    assert body["text"] == "алло, я вас слушаю"
    assert body["latency_ms"] == 42


async def test_the_tts_check_answers_output_audio_ms_and_latency() -> None:
    """§5 check 6: "HTTP 200 and `output_audio_ms > 0`"."""
    server = await _server(_ok_asr, _ok_tts)
    try:
        status, body = await _get(server.port, PREFLIGHT_TTS_PATH)
    finally:
        await server.stop()
    assert status == 200
    assert body["output_audio_ms"] == 640
    assert body["latency_ms"] == 310


async def test_a_query_string_does_not_change_the_route() -> None:
    server = await _server(_ok_asr, _ok_tts)
    try:
        status, body = await _get(server.port, f"{PREFLIGHT_TTS_PATH}?verbose=1")
    finally:
        await server.stop()
    assert status == 200 and body["output_audio_ms"] == 640


@pytest.mark.parametrize("path", [PREFLIGHT_ASR_PATH, PREFLIGHT_TTS_PATH])
async def test_a_probe_failure_is_a_503_problem_document(path: str) -> None:
    """A component that was never warmed answers 503 rather than loading a model mid-preflight."""
    server = await _server(_boom, _boom)
    try:
        status, body = await _get(server.port, path)
    finally:
        await server.stop()
    assert status == 503
    assert body["status"] == 503
    assert "no ASR provider is loaded" in body["detail"]


async def test_an_unknown_path_is_404_and_a_post_is_405() -> None:
    server = await _server(_ok_asr, _ok_tts)
    try:
        not_found, _ = await _get(server.port, "/metrics")
        wrong_method, _ = await _get(server.port, PREFLIGHT_ASR_PATH, method="POST")
    finally:
        await server.stop()
    assert (not_found, wrong_method) == (404, 405)


async def test_start_is_idempotent_and_stop_releases_the_socket() -> None:
    server = await _server(_ok_asr, _ok_tts)
    port = server.port
    await server.start()  # idempotent: the port does not move
    assert server.port == port
    await server.stop()
    assert server.started is False
    await server.stop()  # idempotent
    with pytest.raises(OSError):
        await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout=2)
