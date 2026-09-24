"""`LiveKitRoomBridge` against a fake SDK, the import boundary, and the two CLIs (80 §80.2, D2/D9).

The real SDK is never imported here (`check_imports.py` forbids `livekit` in this directory, and
the gate has no LiveKit, D13): a module object named `livekit` is installed in `sys.modules`, as
`test_headless_client.py` does, and the bridge's own behaviour is asserted — 8 kHz ↔ 48 kHz,
20 ms framing, the first remote audio track only, idempotent teardown. That LiveKit itself carries
the audio is `benchmarks/benchmark_voip.py --path sip-livekit`'s job (`requires_livekit`).
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sip_testkit import TEST_REALM, TEST_SIP_PASSWORD
from voice_agent.tools import softphone as softphone_cli
from voice_agent.transport.sip.bridge import LiveKitRoomBridge, sip_participant_identity
from voice_agent.transport.sip.gateway import SipGateway
from voice_agent.transport.sip.rtp import FRAME_BYTES

REPO_ROOT = Path(__file__).resolve().parents[4]
SIP_PACKAGE = REPO_ROOT / "workers/voice_agent/voice_agent/transport/sip"


class _Frame:
    def __init__(self, *, data: bytes, sample_rate: int, num_channels: int, **_: Any) -> None:
        self.data = data
        self.sample_rate = sample_rate
        self.num_channels = num_channels


class _Source:
    def __init__(self, sample_rate: int, channels: int, queue_size_ms: int = 1000) -> None:
        self.sample_rate = sample_rate
        self.queue_size_ms = queue_size_ms
        self.captured: list[_Frame] = []
        self.closed = 0

    async def capture_frame(self, frame: _Frame) -> None:
        self.captured.append(frame)

    async def aclose(self) -> None:
        self.closed += 1


class _Stream:
    queue: asyncio.Queue[Any]

    @classmethod
    def from_track(cls, *, track: Any, sample_rate: int, num_channels: int) -> _Stream:
        assert sample_rate == 48_000 and num_channels == 1
        stream = cls()
        stream.queue = track.queue
        return stream

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> Any:
        return await self.queue.get()

    async def aclose(self) -> None:
        return None


class _Room:
    last: _Room | None = None

    def __init__(self) -> None:
        self.handlers: dict[str, Callable[..., None]] = {}
        self.published: list[Any] = []
        self.connected_to: tuple[str, str] | None = None
        self.disconnected = 0
        self.local_participant = types.SimpleNamespace(publish_track=self._publish)
        _Room.last = self

    def on(self, name: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
        def register(handler: Callable[..., None]) -> Callable[..., None]:
            self.handlers[name] = handler
            return handler

        return register

    async def connect(self, url: str, token: str) -> None:
        self.connected_to = (url, token)

    async def _publish(self, track: Any, options: Any) -> None:
        self.published.append((track, options))

    async def disconnect(self) -> None:
        self.disconnected += 1


@pytest.fixture
def fake_livekit(monkeypatch: pytest.MonkeyPatch) -> Iterator[types.ModuleType]:
    rtc = types.ModuleType("livekit.rtc")
    rtc.Room = _Room  # type: ignore[attr-defined]
    rtc.AudioSource = _Source  # type: ignore[attr-defined]
    rtc.AudioFrame = _Frame  # type: ignore[attr-defined]
    rtc.AudioStream = _Stream  # type: ignore[attr-defined]
    rtc.TrackKind = types.SimpleNamespace(KIND_AUDIO="audio", KIND_VIDEO="video")  # type: ignore[attr-defined]
    rtc.TrackSource = types.SimpleNamespace(SOURCE_MICROPHONE="mic")  # type: ignore[attr-defined]
    rtc.TrackPublishOptions = lambda *, source: types.SimpleNamespace(source=source)  # type: ignore[attr-defined]
    rtc.LocalAudioTrack = types.SimpleNamespace(  # type: ignore[attr-defined]
        create_audio_track=lambda name, source: types.SimpleNamespace(name=name, source=source)
    )
    package = types.ModuleType("livekit")
    package.rtc = rtc  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "livekit", package)
    monkeypatch.setitem(sys.modules, "livekit.rtc", rtc)
    yield package


async def test_the_livekit_bridge_resamples_both_ways_and_keeps_20_ms_frames(
    fake_livekit: types.ModuleType,
) -> None:
    heard: list[bytes] = []
    bridge = LiveKitRoomBridge(url="ws://lk", token="tok", identity=sip_participant_identity("c1"))
    await bridge.open(heard.append)
    room = _Room.last
    assert room is not None and room.connected_to == ("ws://lk", "tok")
    track, _options = room.published[0]
    assert track.name == "sip-c1"

    await bridge.push(b"\x10\x00" * 160)  # 20 ms at 8 kHz
    source = track.source
    assert source.sample_rate == 48_000 and source.queue_size_ms == 100
    assert abs(len(source.captured[0].data) - 6 * FRAME_BYTES) <= 12

    remote = types.SimpleNamespace(kind="audio", queue=asyncio.Queue())
    room.handlers["track_subscribed"](remote, None, types.SimpleNamespace(identity="agent"))
    room.handlers["track_subscribed"](  # a second track is ignored (the first one plays)
        types.SimpleNamespace(kind="audio", queue=asyncio.Queue()),
        None,
        types.SimpleNamespace(identity="other"),
    )
    assert bridge.track_subscribed.is_set()
    for _ in range(4):  # 40 ms of 10 ms frames at 48 kHz
        await remote.queue.put(
            types.SimpleNamespace(
                frame=_Frame(data=b"\x20\x00" * 480, sample_rate=48_000, num_channels=1)
            )
        )
    for _ in range(50):
        if len(heard) >= 1:
            break
        await asyncio.sleep(0.01)
    assert heard and all(len(frame) == FRAME_BYTES for frame in heard)

    await bridge.close()
    await bridge.close()
    assert room.disconnected == 1 and source.closed == 1


def test_check_imports_is_green_and_livekit_stays_under_transport() -> None:
    """80 §80.8.1: `check_imports` green; `livekit` only under `transport/`, no `livekit.agents`."""
    completed = subprocess.run(
        [sys.executable, "backend/tools/check_imports.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    for path in SIP_PACKAGE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "livekit.agents" not in text
        if path.name != "bridge.py":
            assert "from livekit" not in text and "import livekit" not in text, path.name
    for outside in ("voice_agent/sip_gateway.py", "voice_agent/tools/softphone.py"):
        text = (REPO_ROOT / "workers/voice_agent" / outside).read_text(encoding="utf-8")
        assert "livekit" not in text.replace("LiveKit", "")


def test_the_gateway_and_the_softphone_import_without_the_livekit_sdk() -> None:
    code = (
        "import sys; sys.modules['livekit'] = None; "
        "import voice_agent.sip_gateway, voice_agent.tools.softphone, "
        "voice_agent.transport.sip.bridge; print('ok')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, cwd=REPO_ROOT
    )
    assert completed.returncode == 0 and completed.stdout.strip() == "ok", completed.stderr


def test_the_gateway_entry_point_refuses_to_start_without_a_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from voice_agent import sip_gateway

    monkeypatch.setenv("SIM_SIP_PASSWORD", "")
    monkeypatch.setenv("SIM_ENV_FILE", "")
    assert sip_gateway.main([]) == 2
    assert "SIM_SIP_PASSWORD" in capsys.readouterr().err
    monkeypatch.setenv("SIM_SIP_PASSWORD", TEST_SIP_PASSWORD)
    monkeypatch.setenv("SIM_SIP_GATEWAY_HTTP_PORT", "8000")
    assert sip_gateway.main([]) == 2
    assert "owner port" in capsys.readouterr().err


async def test_the_softphone_cli_registers_calls_999_and_reports_audio_both_ways(
    gateway: SipGateway, tmp_path: Path
) -> None:
    capture = tmp_path / "echo.wav"
    args = argparse.Namespace(
        server=f"127.0.0.1:{gateway.udp_port}",
        register="trainee",
        dial="999",
        transport="udp",
        codec="pcma",
        domain=TEST_REALM,
        local_host="127.0.0.1",
        expires=60,
        duration=1.2,
        answer_timeout=5.0,
        wav=None,
        capture=str(capture),
        headset=False,
        unregister=True,
    )
    summary = await softphone_cli.run(args, TEST_SIP_PASSWORD)
    assert summary["register"] == 200
    assert summary["call"] == {"provisional": [100, 180], "final": 200}
    assert summary["codec"] == "PCMA"
    rtp = summary["rtp"]
    assert rtp["packets_sent"] == 60 and rtp["packets_received"] == 60 and rtp["lost"] == 0
    assert rtp["seq_breaks"] == 0 and rtp["ts_breaks"] == 0 and rtp["received_rms"] > 0
    assert summary["echo_round_trip_ms"]["bursts_detected"] == 2
    assert summary["bye"] == 200 and summary["unregister"] == 200
    assert capture.stat().st_size > 44 + 50 * FRAME_BYTES
