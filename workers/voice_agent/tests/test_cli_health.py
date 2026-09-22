"""`python -m voice_agent.cli health` — the compose healthcheck's exit code (E18-C for E18-E).

The voice-agent publishes no host port and runs no API, so the only thing inside its container that
can be asked "are you serving?" is the loopback preflight endpoint it binds after warm-up. This CLI
asks it and answers with an exit code, which is the whole interface a `healthcheck:` has.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from voice_agent.cli import main
from voice_agent.preflight_http import PreflightHttpServer


async def _ok_asr() -> dict[str, Any]:
    return {"text": "алло", "latency_ms": 12}


async def _ok_tts() -> dict[str, Any]:
    return {"output_audio_ms": 320, "latency_ms": 90}


async def _boom() -> dict[str, Any]:
    raise RuntimeError("no TTS provider is loaded in this process")


@pytest.fixture
async def serving(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A live preflight endpoint on an ephemeral loopback port, pointed at by the env var."""

    async def _start(tts: Any = _ok_tts) -> PreflightHttpServer:
        server = PreflightHttpServer(asr_probe=_ok_asr, tts_probe=tts, port=0)
        await server.start()
        monkeypatch.setenv("SIM_VOICE_AGENT_HTTP_PORT", str(server.port))
        return server

    return _start


def _run(argv: list[str]) -> int:
    """`main` runs its own event loop, so it is called from a thread-free sync context."""
    return main(argv)


async def test_nothing_listening_is_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The healthcheck's whole job: a process that is not serving must not be called healthy."""
    # An ephemeral port nobody bound. Grab one and release it immediately.
    server = PreflightHttpServer(asr_probe=_ok_asr, tts_probe=_ok_tts, port=0)
    await server.start()
    port = server.port
    await server.stop()
    monkeypatch.setenv("SIM_VOICE_AGENT_HTTP_PORT", str(port))

    assert await asyncio.to_thread(_run, ["health"]) == 1


async def test_a_listening_endpoint_is_healthy(serving, capsys: pytest.CaptureFixture[str]) -> None:
    """The default is a connection check: a healthcheck on a short interval spends no GPU time."""
    server = await serving()
    try:
        assert await asyncio.to_thread(_run, ["health"]) == 0
    finally:
        await server.stop()
    assert "OK" in capsys.readouterr().out


async def test_the_probe_mode_calls_the_tts_endpoint(serving) -> None:  # type: ignore[no-untyped-def]
    server = await serving()
    try:
        assert await asyncio.to_thread(_run, ["health", "--probe"]) == 0
    finally:
        await server.stop()


async def test_the_probe_mode_is_unhealthy_when_the_model_does_not_respond(
    serving,
) -> None:  # type: ignore[no-untyped-def]
    """A warm socket in front of a dead model is not health — 503 must fail the check."""
    server = await serving(_boom)
    try:
        assert await asyncio.to_thread(_run, ["health", "--probe"]) == 1
        # `--any` is the looser reading: the endpoint answered at all.
        assert await asyncio.to_thread(_run, ["health", "--probe", "--any"]) == 0
    finally:
        await server.stop()


async def test_the_json_output_is_machine_readable(
    serving, capsys: pytest.CaptureFixture[str]
) -> None:  # type: ignore[no-untyped-def]
    import json

    server = await serving()
    port = server.port
    try:
        assert await asyncio.to_thread(_run, ["health", "--json"]) == 0
    finally:
        await server.stop()
    body = json.loads(capsys.readouterr().out.strip())
    assert body["healthy"] is True
    assert body["port"] == port


def test_an_unknown_subcommand_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["nonsense"])
