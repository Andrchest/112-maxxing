"""`voice_agent.tools.inject` — the mic-less demo CLI (E20-B, ruling R8).

Every network boundary the CLI touches is dependency-injected (`run_injection`'s
`http_client_factory` / `voice_client_factory` / `event_stream_factory`), so this suite drives the
real turn-loop logic against a fake `TraineeVoiceClient` and a canned WebSocket event feed, and the
real REST calls (`login`, `fetch_voice_token`) against `httpx.MockTransport` — no LiveKit SDK, no
`websockets` network connection, and no backend process anywhere (D13: the gate stays GPU/network
free). `test_transport_boundary.py` separately proves this module contains no `import livekit`.
"""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from voice_agent.tools import inject

# `asyncio_mode = "auto"` (root pyproject.toml) picks up every `async def test_*` below with no
# marker needed; a module-level `pytestmark = pytest.mark.asyncio` would also apply (and warn on)
# the plain synchronous tests in this file.


# -------------------------------------------------------------------------------------------
# Fakes
# -------------------------------------------------------------------------------------------


class _FakeVoiceClient:
    """Stands in for `HeadlessTraineeClient` — records what was published, nothing more."""

    def __init__(self, *, url: str, token: str, room: str) -> None:
        self.url = url
        self.token = token
        self.room = room
        self.connected = False
        self.closed = False
        self.published: list[tuple[Path, str]] = []

    async def connect(self) -> None:
        self.connected = True

    async def publish_wav(self, path: Path, *, turn_id: str, realtime: bool = True) -> Any:
        self.published.append((path, turn_id))
        return None

    async def close(self) -> None:
        self.closed = True


def _fake_voice_client_factory(
    clients: list[_FakeVoiceClient],
) -> Any:
    def _build(*, url: str, token: str, room: str) -> _FakeVoiceClient:
        client = _FakeVoiceClient(url=url, token=token, room=room)
        clients.append(client)
        return client

    return _build


def _fake_event_stream_factory(frames: Sequence[dict[str, Any]]) -> Any:
    """A canned `event_stream_factory`: yields `frames` in order, one `asyncio.sleep(0)` apart so
    the consumer task genuinely interleaves with the turn loop, the way a real socket would."""

    @contextlib.asynccontextmanager
    async def _open(ws_url: str) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        import asyncio

        async def _frames() -> AsyncIterator[dict[str, Any]]:
            for frame in frames:
                await asyncio.sleep(0)
                yield frame

        yield _frames()

    return _open


def _event(event_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": "event", "seq_no": 1, "event_type": event_type, "payload": payload}


TWO_TURN_FRAMES = [
    _event("USER_SPEECH_ENDED", at_offset_ms=1000),
    _event("ASR_FINAL", text="служба сто двенадцать"),
    _event("CALLER_TTS_STARTED", turn_index=0, at_offset_ms=1500),
    _event("CALLER_TTS_ENDED", turn_index=0, at_offset_ms=3500, completed=True),
    _event("USER_SPEECH_ENDED", at_offset_ms=5000),
    _event("ASR_FINAL", text="пожар на кухне"),
    _event("CALLER_TTS_STARTED", turn_index=1, at_offset_ms=5400),
    _event("CALLER_TTS_ENDED", turn_index=1, at_offset_ms=7000, completed=True),
]


def _mock_transport(
    *, login_status: int = 200, voice_token_status: int = 200
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/login":
            if login_status != 200:
                return httpx.Response(login_status, text="nope")
            body = json.loads(request.content)
            assert body == {"username": "trainee", "password": "s3cret"}
            return httpx.Response(200, json={"access_token": "jwt-token-abc"})
        if request.url.path.endswith("/voice-token"):
            assert request.headers["authorization"] == "Bearer jwt-token-abc"
            if voice_token_status != 200:
                return httpx.Response(voice_token_status, text="not ready")
            return httpx.Response(
                200,
                json={
                    "token": "livekit-jwt",
                    "livekit_url": "ws://127.0.0.1:7880",
                    "room_name": "session-room",
                    "participant_identity": "trainee:abc",
                    "expires_at": "2026-09-22T12:00:00Z",
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.MockTransport(handler)


# -------------------------------------------------------------------------------------------
# Turn corpus loaders
# -------------------------------------------------------------------------------------------


def test_turns_from_wavs_assigns_ordinal_ids(tmp_path: Path) -> None:
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    turns = inject.turns_from_wavs([a, b])
    assert [t.id for t in turns] == ["turn-1", "turn-2"]
    assert [t.path for t in turns] == [a, b]


def test_turns_from_jsonl_resolves_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "wav").mkdir()
    (tmp_path / "wav" / "greeting.wav").write_bytes(b"")
    turns_file = tmp_path / "turns.jsonl"
    turns_file.write_text(
        '{"id": "greeting", "path": "wav/greeting.wav", "text": "..."}\n'
        "\n"  # a blank line must be skipped
        '{"path": "wav/greeting.wav"}\n',
        encoding="utf-8",
    )
    turns = inject.turns_from_jsonl(turns_file)
    assert [t.id for t in turns] == ["greeting", "turn-2"]
    assert all(t.path == tmp_path / "wav" / "greeting.wav" for t in turns)


# -------------------------------------------------------------------------------------------
# REST: login, voice-token
# -------------------------------------------------------------------------------------------


async def test_login_returns_the_bearer_token() -> None:
    async with httpx.AsyncClient(transport=_mock_transport()) as client:
        token = await inject.login(
            client, base_url="http://127.0.0.1:8100", username="trainee", password="s3cret"
        )
    assert token == "jwt-token-abc"


async def test_login_failure_raises_api_error() -> None:
    async with httpx.AsyncClient(transport=_mock_transport(login_status=401)) as client:
        with pytest.raises(inject.ApiError, match="login"):
            await inject.login(
                client, base_url="http://127.0.0.1:8100", username="trainee", password="wrong"
            )


async def test_fetch_voice_token_maps_every_field() -> None:
    async with httpx.AsyncClient(transport=_mock_transport()) as client:
        token = await inject.fetch_voice_token(
            client,
            base_url="http://127.0.0.1:8100",
            session_id="11111111-1111-1111-1111-111111111111",
            access_token="jwt-token-abc",
        )
    assert token == inject.VoiceToken(
        token="livekit-jwt",
        livekit_url="ws://127.0.0.1:7880",
        room_name="session-room",
        participant_identity="trainee:abc",
        expires_at="2026-09-22T12:00:00Z",
    )


async def test_fetch_voice_token_failure_raises_api_error() -> None:
    async with httpx.AsyncClient(transport=_mock_transport(voice_token_status=409)) as client:
        with pytest.raises(inject.ApiError, match="voice-token"):
            await inject.fetch_voice_token(
                client,
                base_url="http://127.0.0.1:8100",
                session_id="11111111-1111-1111-1111-111111111111",
                access_token="jwt-token-abc",
            )


def test_ws_url_carries_the_token_and_switches_scheme() -> None:
    url = inject._ws_url("https://demo.local:8100", "abc-123", "jwt-token-abc")
    assert url == "wss://demo.local:8100/api/v1/ws/sessions/abc-123?token=jwt-token-abc"

    url = inject._ws_url("http://127.0.0.1:8100/", "abc-123", "jwt-token-abc")
    assert url == "ws://127.0.0.1:8100/api/v1/ws/sessions/abc-123?token=jwt-token-abc"


# -------------------------------------------------------------------------------------------
# The turn loop (the gate test the brief asks for): fake voice client + fake event stream
# -------------------------------------------------------------------------------------------


async def test_run_injection_sends_every_wav_and_prints_the_redacted_events(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    turns = inject.turns_from_wavs([tmp_path / "a.wav", tmp_path / "b.wav"])
    clients: list[_FakeVoiceClient] = []

    exit_code = await inject.run_injection(
        api_base_url="http://127.0.0.1:8100",
        session_id="session-1",
        turns=turns,
        wait_caller=True,
        password="s3cret",
        http_client_factory=lambda: httpx.AsyncClient(transport=_mock_transport()),
        voice_client_factory=_fake_voice_client_factory(clients),
        event_stream_factory=_fake_event_stream_factory(TWO_TURN_FRAMES),
    )

    assert exit_code == 0
    assert len(clients) == 1
    client = clients[0]
    assert client.connected is True
    assert client.closed is True
    assert client.published == [(turns[0].path, "turn-1"), (turns[1].path, "turn-2")]
    # the token/room/url reached the voice client exactly as `fetch_voice_token` mapped them
    assert client.token == "livekit-jwt"
    assert client.room == "session-room"
    assert client.url == "ws://127.0.0.1:7880"

    out = capsys.readouterr().out
    assert "sending a.wav (turn 1/2, id=turn-1)" in out
    assert "sending b.wav (turn 2/2, id=turn-2)" in out
    assert 'heard (trainee speech): "служба сто двенадцать"' in out
    assert 'heard (trainee speech): "пожар на кухне"' in out
    # the caller's own words are never printed - only the redacted timing (this module's docstring)
    assert "служба сто двенадцать" not in out.split("heard")[0]
    assert "text withheld from OPERATOR_112 by design" in out
    assert "speech_end_to_first_audio_ms: 500" in out  # turn 1: 1500 - 1000
    assert "speech_end_to_first_audio_ms: 400" in out  # turn 2: 5400 - 5000
    assert "caller done (completed=True)" in out
    assert "timed out" not in out


async def test_run_injection_without_wait_caller_does_not_block_on_the_reply(
    tmp_path: Path,
) -> None:
    """The default: fire every WAV without waiting for `CALLER_TTS_ENDED` (barge-in demos)."""
    turns = inject.turns_from_wavs([tmp_path / "a.wav", tmp_path / "b.wav"])
    clients: list[_FakeVoiceClient] = []

    exit_code = await inject.run_injection(
        api_base_url="http://127.0.0.1:8100",
        session_id="session-1",
        turns=turns,
        wait_caller=False,
        password="s3cret",
        http_client_factory=lambda: httpx.AsyncClient(transport=_mock_transport()),
        voice_client_factory=_fake_voice_client_factory(clients),
        event_stream_factory=_fake_event_stream_factory([]),  # no events at all - still finishes
    )

    assert exit_code == 0
    assert clients[0].published == [(turns[0].path, "turn-1"), (turns[1].path, "turn-2")]


async def test_run_injection_reports_a_timeout_without_crashing(tmp_path: Path) -> None:
    """A caller that never replies (the events end early) times out the wait, not the CLI."""
    turns = inject.turns_from_wavs([tmp_path / "a.wav"])
    clients: list[_FakeVoiceClient] = []

    exit_code = await inject.run_injection(
        api_base_url="http://127.0.0.1:8100",
        session_id="session-1",
        turns=turns,
        wait_caller=True,
        password="s3cret",
        http_client_factory=lambda: httpx.AsyncClient(transport=_mock_transport()),
        voice_client_factory=_fake_voice_client_factory(clients),
        event_stream_factory=_fake_event_stream_factory([]),
        caller_reply_timeout_s=0.05,
    )

    assert exit_code == 0
    assert clients[0].closed is True


async def test_run_injection_prints_not_derivable_for_a_negative_gap(tmp_path: Path) -> None:
    """Over a not-yet-R13-fixed transport the two offsets can share no origin (E20 R13, open)."""
    turns = inject.turns_from_wavs([tmp_path / "a.wav"])
    frames = [
        _event("USER_SPEECH_ENDED", at_offset_ms=40000),
        _event("CALLER_TTS_STARTED", turn_index=0, at_offset_ms=1500),
        _event("CALLER_TTS_ENDED", turn_index=0, at_offset_ms=1800, completed=True),
    ]

    out = io.StringIO()
    exit_code = await inject.run_injection(
        api_base_url="http://127.0.0.1:8100",
        session_id="session-1",
        turns=turns,
        wait_caller=True,
        password="s3cret",
        out=out,
        http_client_factory=lambda: httpx.AsyncClient(transport=_mock_transport()),
        voice_client_factory=_fake_voice_client_factory([]),
        event_stream_factory=_fake_event_stream_factory(frames),
    )
    assert exit_code == 0
    assert "speech_end_to_first_audio_ms: not derivable" in out.getvalue()
    assert "E20 R13" in out.getvalue()


async def test_run_injection_propagates_a_failed_login(tmp_path: Path) -> None:
    turns = inject.turns_from_wavs([tmp_path / "a.wav"])
    with pytest.raises(inject.ApiError):
        await inject.run_injection(
            api_base_url="http://127.0.0.1:8100",
            session_id="session-1",
            turns=turns,
            wait_caller=False,
            password="wrong",
            http_client_factory=lambda: httpx.AsyncClient(
                transport=_mock_transport(login_status=401)
            ),
            voice_client_factory=_fake_voice_client_factory([]),
            event_stream_factory=_fake_event_stream_factory([]),
        )


# -------------------------------------------------------------------------------------------
# CLI argument parsing (no network reached in any of these)
# -------------------------------------------------------------------------------------------


def test_main_refuses_both_wav_and_turns(tmp_path: Path) -> None:
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"")
    turns_file = tmp_path / "turns.jsonl"
    turns_file.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        inject.main(["--session", "s1", "--wav", str(wav), "--turns", str(turns_file)])
    assert excinfo.value.code == 2


def test_main_refuses_neither_wav_nor_turns() -> None:
    with pytest.raises(SystemExit) as excinfo:
        inject.main(["--session", "s1"])
    assert excinfo.value.code == 2


def test_main_requires_the_session_flag() -> None:
    with pytest.raises(SystemExit):
        inject.main(["--wav", "a.wav"])


def test_main_refuses_a_missing_trainee_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(inject.TRAINEE_PASSWORD_ENV, raising=False)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"")
    exit_code = inject.main(["--session", "s1", "--wav", str(wav)])
    assert exit_code == 2
