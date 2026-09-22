"""`LiveKitCallTransport` against a real LiveKit server (§2.1, D9, SPEC §15).

Marked `requires_livekit` and skipped unless **both** are true: the `livekit` SDK is installed
(it is an optional extra, D1) and a server answers on `SIM_LIVEKIT_URL`. `make gate` must stay
green with no LiveKit anywhere, which is this task's ruling 1 — so this file is the *only* place
that would need one, and it declines rather than failing.

What it checks is the port contract, not LiveKit: join a room, publish a generated tone, receive
it on a second participant, cancel mid-playback and get a truthful `DeliveredAudio` back. The
`LiveKitPlayoutSink` in between is the mapping table of §2.1, so if the SDK ever renames
`queued_duration` or `clear_queue` this is what notices.

Run it by hand with a dev-mode server (never on ports 8000/8001, which belong to the owner's
other project):

    docker run --rm -d -p 7880:7880 -p 7881:7881 livekit/livekit-server --dev
    SIM_LIVEKIT_URL=ws://127.0.0.1:7880 uv run pytest -q -m requires_livekit \\
        workers/voice_agent/tests/test_livekit_contract.py
"""

from __future__ import annotations

import asyncio
import importlib
import math
import os
import socket
import time
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import jwt
import pytest
from app.application.ports.call_transport import AudioFrame
from app.application.voice.config import VoiceTurnConfig
from voice_agent.transport.livekit_transport import LiveKitCallTransport

pytestmark = pytest.mark.requires_livekit

# The dev stack's own credentials, so `make dev-infra-up` + this file need no extra environment.
# They are `infra/docker-compose.yml`'s `livekit` service defaults verbatim
# (`LIVEKIT_KEYS: "${SIM_LIVEKIT_API_KEY:-devkey}: ${SIM_LIVEKIT_API_SECRET:-devsecret1234567890}"`)
# and are read from `SIM_LIVEKIT_*` first, so a real deployment's credentials always win.
#
# **Dev-only, and deliberately worthless.** These are the placeholders the local compose file ships
# with; nothing outside a developer's own machine accepts them, no real secret is ever written here
# (SPEC §41), and a deployment that left them in place would be signing tokens with a value printed
# in this repository. Until E19-E3 the secret here was `"secret"`, which matched nothing: this test
# failed against the project's own dev stack with `401 ... token signature is invalid`.
DEFAULT_URL = "ws://127.0.0.1:7880"
DEFAULT_API_KEY = "devkey"
DEFAULT_API_SECRET = "devsecret1234567890"
TOKEN_TTL_S = 600


def _server_url() -> str:
    return os.environ.get("SIM_LIVEKIT_URL", DEFAULT_URL)


def _server_is_up(url: str, timeout_s: float = 1.0) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme in {"wss", "https"} else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _access_token(room: str, identity: str) -> str:
    """A LiveKit access token: a plain HS256 JWT, which is why the backend needs no SDK (D9)."""
    now = int(time.time())
    return jwt.encode(
        {
            "iss": os.environ.get("SIM_LIVEKIT_API_KEY", DEFAULT_API_KEY),
            "sub": identity,
            "jti": identity,
            "nbf": now,
            "exp": now + TOKEN_TTL_S,
            "video": {"room": room, "roomJoin": True, "canPublish": True, "canSubscribe": True},
        },
        os.environ.get("SIM_LIVEKIT_API_SECRET", DEFAULT_API_SECRET),
        algorithm="HS256",
    )


@pytest.fixture
def live_server() -> str:
    """The server URL, or a skip when nothing answers / the SDK is absent."""
    pytest.importorskip("livekit", reason="the `livekit` SDK is an optional extra (D1)")
    url = _server_url()
    if not _server_is_up(url):
        pytest.skip(f"no LiveKit server on {url} (set SIM_LIVEKIT_URL to run this)")
    return url


def tone_frames(config: VoiceTurnConfig, *, duration_ms: int) -> list[AudioFrame]:
    """A generated tone, chunked at `tts_chunk_ms` — the shape E14's TTS will hand over."""
    samples_per_chunk = (config.sample_rate * config.tts_chunk_ms) // 1000
    chunks = duration_ms // config.tts_chunk_ms
    step = 2.0 * math.pi * 440.0 / config.sample_rate
    frames: list[AudioFrame] = []
    for index in range(chunks):
        pcm = bytearray()
        for n in range(samples_per_chunk):
            value = round(0.3 * math.sin(step * (index * samples_per_chunk + n)) * 32767)
            pcm += value.to_bytes(2, "little", signed=True)
        frames.append(
            AudioFrame(
                pcm=bytes(pcm),
                sample_rate=config.sample_rate,
                num_channels=1,
                samples_per_channel=samples_per_chunk,
                capture_offset_ms=index * config.tts_chunk_ms,
            )
        )
    return frames


async def as_stream(frames: list[AudioFrame]) -> AsyncIterator[AudioFrame]:
    for frame in frames:
        yield frame


async def test_connect_publish_receive_and_cancel(live_server: str) -> None:
    """The four port operations that only a real SFU can answer for (§2.1).

    The SDK is reached through `importlib` rather than an `import` statement on purpose: this
    task's ruling 2 restricts the `livekit` import to
    `workers/voice_agent/voice_agent/transport/**`, and `backend/tools/check_imports.py` enforces
    that over `workers/voice_agent/tests/**` too. A test needs a *second* participant, which only
    the SDK can be, so it borrows it dynamically and the static rule stays absolute.
    """
    rtc = importlib.import_module("livekit.rtc")

    config = VoiceTurnConfig()
    room_name = f"e11-contract-{uuid.uuid4().hex[:8]}"
    call_id = uuid.uuid4()

    transport = LiveKitCallTransport(
        url=live_server,
        token=_access_token(room_name, "caller"),
        outbound_queue_ms=config.outbound_queue_ms,
        outbound_sample_rate=config.sample_rate,
    )
    listener = rtc.Room()
    received: list[int] = []

    @listener.on("track_subscribed")
    def _on_track(track: object, publication: object, participant: object) -> None:
        async def pump() -> None:
            stream = rtc.AudioStream.from_track(
                track=track, sample_rate=config.sample_rate, num_channels=1
            )
            async for event in stream:
                received.append(event.frame.samples_per_channel)

        asyncio.create_task(pump())  # noqa: RUF006 - cancelled with the room below

    try:
        await listener.connect(live_server, _access_token(room_name, "trainee"))
        await transport.connect(call_id)

        handle = await transport.play(as_stream(tone_frames(config, duration_ms=4000)))
        # Give the SFU time to subscribe the second participant and forward some audio.
        for _ in range(100):
            await asyncio.sleep(0.05)
            if received:
                break

        assert received, "the second participant received no audio from the published track"

        delivered = await handle.cancel()
        assert delivered.cancelled is True
        assert delivered.total_audio_ms_generated > 0
        assert 0 <= delivered.delivered_audio_ms <= delivered.total_audio_ms_generated
        assert handle.is_active() is False
    finally:
        await transport.disconnect()
        await listener.disconnect()
