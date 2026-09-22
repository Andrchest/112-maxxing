"""`HeadlessTraineeClient` against a fake SDK (E19-E, HLD 60 §7.4, D9, D13).

`make gate` must stay green with no LiveKit anywhere (D13) and the `livekit` SDK is not even a
declared dependency of this workspace — `voice_agent.transport.livekit_transport` and this client
both import it **inside** their methods for exactly that reason. So these tests install a fake
module named `livekit` in `sys.modules` (a module object built here, never an `import livekit`
statement, which `backend/tools/check_imports.py` forbids in this directory) and assert the
client's own behaviour: what it publishes, at what frame size, when it considers the caller to have
spoken, and that teardown is idempotent.

What is deliberately NOT asserted here is that LiveKit works — that is
`test_livekit_contract.py`'s job, marked `requires_livekit` and skipped without a server.
"""

from __future__ import annotations

import asyncio
import struct
import sys
import types
import wave
from pathlib import Path
from typing import Any

import pytest
from voice_agent.transport.headless_client import HeadlessTraineeClient, PublishedTurn

pytestmark = pytest.mark.asyncio

SAMPLE_RATE = 16_000
FRAME_MS = 20


# ---------------------------------------------------------------------------------------------
# The fake SDK: only the handful of names the client actually touches.
# ---------------------------------------------------------------------------------------------


class _TrackKind:
    KIND_AUDIO = "audio"
    KIND_VIDEO = "video"


class _TrackSource:
    SOURCE_MICROPHONE = "microphone"


class _AudioFrame:
    def __init__(
        self, *, data: bytes, sample_rate: int, num_channels: int, samples_per_channel: int
    ) -> None:
        self.data = data
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.samples_per_channel = samples_per_channel


class _AudioSource:
    def __init__(self, sample_rate: int, channels: int) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.captured: list[_AudioFrame] = []
        self.closed = 0

    async def capture_frame(self, frame: _AudioFrame) -> None:
        self.captured.append(frame)

    async def aclose(self) -> None:
        self.closed += 1


class _LocalAudioTrack:
    def __init__(self, name: str, source: _AudioSource) -> None:
        self.name = name
        self.source = source

    @classmethod
    def create_audio_track(cls, name: str, source: _AudioSource) -> _LocalAudioTrack:
        return cls(name, source)


class _TrackPublishOptions:
    def __init__(self, *, source: str) -> None:
        self.source = source


class _LocalParticipant:
    def __init__(self) -> None:
        self.published: list[tuple[Any, Any]] = []

    async def publish_track(self, track: Any, options: Any) -> None:
        self.published.append((track, options))


class _FakeTrack:
    def __init__(self, kind: str = _TrackKind.KIND_AUDIO) -> None:
        self.kind = kind


class _AudioStream:
    """An async iterator over `queue`, so a test decides when the caller "speaks"."""

    #: The queue the next `from_track` hands out — set by the test before it fires a track event.
    next_queue: asyncio.Queue[object] | None = None

    def __init__(self, queue: asyncio.Queue[object]) -> None:
        self._queue = queue
        self.closed = 0

    @classmethod
    def from_track(cls, *, track: Any, sample_rate: int, num_channels: int) -> _AudioStream:
        queue = cls.next_queue if cls.next_queue is not None else asyncio.Queue()
        return cls(queue)

    def __aiter__(self) -> _AudioStream:
        return self

    async def __anext__(self) -> object:
        return await self._queue.get()

    async def aclose(self) -> None:
        self.closed += 1


class _Room:
    def __init__(self) -> None:
        self.handlers: dict[str, list[Any]] = {}
        self.connected_to: tuple[str, str] | None = None
        self.disconnects = 0
        self.local_participant = _LocalParticipant()

    def on(self, event: str) -> Any:
        def register(handler: Any) -> Any:
            self.handlers.setdefault(event, []).append(handler)
            return handler

        return register

    async def connect(self, url: str, token: str) -> None:
        self.connected_to = (url, token)

    async def disconnect(self) -> None:
        self.disconnects += 1

    def fire_track_subscribed(self, track: Any) -> None:
        for handler in self.handlers.get("track_subscribed", []):
            handler(track, None, None)


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Install a module named `livekit` whose `rtc` is the doubles above, and hand back the room.

    Built with `types.ModuleType` rather than imported: there is no `livekit` wheel in this venv
    (it is not a declared dependency) and an `import livekit` statement in this directory is a
    boundary violation `check_imports.py` would fail (`test_transport_boundary.py`).
    """
    rooms: list[_Room] = []

    def room_factory() -> _Room:
        room = _Room()
        rooms.append(room)
        return room

    rtc = types.SimpleNamespace(
        Room=room_factory,
        AudioSource=_AudioSource,
        LocalAudioTrack=_LocalAudioTrack,
        TrackPublishOptions=_TrackPublishOptions,
        TrackSource=_TrackSource,
        TrackKind=_TrackKind,
        AudioFrame=_AudioFrame,
        AudioStream=_AudioStream,
    )
    package = types.ModuleType("livekit")
    package.rtc = rtc  # type: ignore[attr-defined]
    rtc_module = types.ModuleType("livekit.rtc")
    monkeypatch.setitem(sys.modules, "livekit", package)
    monkeypatch.setitem(sys.modules, "livekit.rtc", rtc_module)
    _AudioStream.next_queue = None
    return types.SimpleNamespace(rooms=rooms, rtc=rtc)


def write_wav(path: Path, *, duration_ms: int) -> Path:
    """A 16 kHz mono 16-bit WAV of `duration_ms`, exactly the corpus format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = (SAMPLE_RATE * duration_ms) // 1000
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(b"".join(struct.pack("<h", (n % 1000) * 8) for n in range(frames)))
    return path


def client() -> HeadlessTraineeClient:
    return HeadlessTraineeClient(url="ws://127.0.0.1:7880", token="t0ken", room="room-1")


# ---------------------------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------------------------


async def test_connect_joins_the_room_and_publishes_a_microphone_track(
    fake_sdk: types.SimpleNamespace,
) -> None:
    """The trainee's browser does exactly this: join with the backend's token, publish a mic."""
    subject = client()
    await subject.connect()
    room = fake_sdk.rooms[0]

    assert room.connected_to == ("ws://127.0.0.1:7880", "t0ken")
    assert len(room.local_participant.published) == 1
    track, options = room.local_participant.published[0]
    assert track.name == "trainee-microphone"
    assert options.source == _TrackSource.SOURCE_MICROPHONE
    assert track.source.sample_rate == SAMPLE_RATE
    assert track.source.channels == 1
    assert subject.room_name == "room-1"
    await subject.close()


async def test_publishing_before_connect_is_refused(fake_sdk: types.SimpleNamespace) -> None:
    """A wrong call order fails loudly instead of silently measuring nothing."""
    with pytest.raises(RuntimeError, match="connect"):
        await client().publish_wav(Path("nowhere.wav"), turn_id="t")


# ---------------------------------------------------------------------------------------------
# publish_wav
# ---------------------------------------------------------------------------------------------


async def test_publish_wav_sends_20ms_frames(
    fake_sdk: types.SimpleNamespace, tmp_path: Path
) -> None:
    """200 ms of audio is ten 20 ms frames of 320 samples each — the room's own frame size."""
    path = write_wav(tmp_path / "turn.wav", duration_ms=200)
    subject = client()
    await subject.connect()
    turn = await subject.publish_wav(path, turn_id="greeting", realtime=False)

    source = fake_sdk.rooms[0].local_participant.published[0][0].source
    assert len(source.captured) == 10
    assert {frame.samples_per_channel for frame in source.captured} == {320}
    assert {len(frame.data) for frame in source.captured} == {640}
    assert {frame.sample_rate for frame in source.captured} == {SAMPLE_RATE}
    assert isinstance(turn, PublishedTurn)
    assert turn.turn_id == "greeting"
    assert turn.first_audio_wall_ms is None
    await subject.close()


async def test_publish_wav_paces_frames_in_realtime(
    fake_sdk: types.SimpleNamespace, tmp_path: Path
) -> None:
    """`realtime=True` is what makes the room timeline the wall timeline (docstring)."""
    path = write_wav(tmp_path / "turn.wav", duration_ms=200)
    subject = client()
    await subject.connect()
    loop = asyncio.get_running_loop()
    started = loop.time()
    await subject.publish_wav(path, turn_id="t", realtime=True)
    elapsed_ms = (loop.time() - started) * 1000

    assert elapsed_ms >= 150, elapsed_ms  # ten 20 ms sleeps, minus scheduler slack
    await subject.close()


@pytest.mark.parametrize(
    ("channels", "width", "rate", "message"),
    [
        (2, 2, SAMPLE_RATE, "16-bit mono"),
        (1, 1, SAMPLE_RATE, "16-bit mono"),
        (1, 2, 22_050, "16000 Hz"),
    ],
)
async def test_publish_wav_refuses_the_wrong_format(
    fake_sdk: types.SimpleNamespace,
    tmp_path: Path,
    channels: int,
    width: int,
    rate: int,
    message: str,
) -> None:
    """A 22 kHz or stereo WAV would be resampled by the room, silently changing the measurement."""
    path = tmp_path / "bad.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(b"\x00" * 3200)
    subject = client()
    await subject.connect()
    with pytest.raises(ValueError, match=message):
        await subject.publish_wav(path, turn_id="t", realtime=False)
    await subject.close()


# ---------------------------------------------------------------------------------------------
# the caller's first audio (cross-check only)
# ---------------------------------------------------------------------------------------------


async def test_the_callers_first_audio_is_timed_per_turn(
    fake_sdk: types.SimpleNamespace, tmp_path: Path
) -> None:
    """Two turns, two cross-checks: the subscriber must re-arm, not stop after the first frame.

    This is the bug the E19-A draft had — `break` after one frame left every later turn with no
    cross-check and an undrained stream.
    """
    path = write_wav(tmp_path / "turn.wav", duration_ms=60)
    queue: asyncio.Queue[object] = asyncio.Queue()
    _AudioStream.next_queue = queue
    subject = client()
    await subject.connect()
    fake_sdk.rooms[0].fire_track_subscribed(_FakeTrack())

    for turn_id in ("turn-1", "turn-2"):
        await subject.publish_wav(path, turn_id=turn_id, realtime=False)
        queue.put_nowait(object())
        crosscheck = await subject.wait_for_caller_audio(timeout_s=2.0)
        assert crosscheck is not None, turn_id
        assert crosscheck >= 0.0

    assert [turn.turn_id for turn in subject.turns] == ["turn-1", "turn-2"]
    assert all(turn.first_audio_wall_ms is not None for turn in subject.turns)
    await subject.close()


async def test_a_silent_caller_is_a_missing_crosscheck_not_a_failure(
    fake_sdk: types.SimpleNamespace, tmp_path: Path
) -> None:
    """The event log is the authority; a missing cross-check must not abort the benchmark."""
    path = write_wav(tmp_path / "turn.wav", duration_ms=60)
    subject = client()
    await subject.connect()
    await subject.publish_wav(path, turn_id="t", realtime=False)

    assert await subject.wait_for_caller_audio(timeout_s=0.05) is None
    await subject.close()


async def test_a_video_track_is_ignored(fake_sdk: types.SimpleNamespace) -> None:
    """Only the caller's audio track is watched — a video track starts no subscriber task."""
    subject = client()
    await subject.connect()
    fake_sdk.rooms[0].fire_track_subscribed(_FakeTrack(kind=_TrackKind.KIND_VIDEO))
    await asyncio.sleep(0)

    assert await subject.wait_for_caller_audio(timeout_s=0.05) is None
    await subject.close()


# ---------------------------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------------------------


async def test_close_is_idempotent_and_leaves_the_room(
    fake_sdk: types.SimpleNamespace, tmp_path: Path
) -> None:
    """A benchmark run that fails half-way must not leave a participant in the room."""
    _AudioStream.next_queue = asyncio.Queue()
    subject = client()
    await subject.connect()
    fake_sdk.rooms[0].fire_track_subscribed(_FakeTrack())
    await asyncio.sleep(0)

    await subject.close()
    await subject.close()

    room = fake_sdk.rooms[0]
    assert room.disconnects == 1
    assert room.local_participant.published[0][0].source.closed == 1


# ---------------------------------------------------------------------------------------------
# The real SDK (E19-E2): skipped when the `transport-livekit` extra is not installed, so the gate
# stays green with no LiveKit anywhere (D13). These need no server — they prove that the extra
# exists, that it provides every name this package uses, and that the import inside the methods
# really resolves to the SDK rather than to a test double.
# ---------------------------------------------------------------------------------------------

#: Every `rtc.*` name `livekit_transport.py` and `headless_client.py` touch between them.
SDK_NAMES = (
    "Room",
    "AudioSource",
    "AudioFrame",
    "AudioStream",
    "LocalAudioTrack",
    "TrackPublishOptions",
    "TrackSource",
    "TrackKind",
)


@pytest.fixture
def real_sdk() -> Any:
    """`livekit.rtc`, or a skip. Imported by name so nothing here is a static `livekit` import."""
    import importlib

    pytest.importorskip(
        "livekit",
        reason="the `livekit` SDK is the `transport-livekit` extra (`make deps-livekit`)",
    )
    return importlib.import_module("livekit.rtc")


@pytest.mark.requires_livekit
async def test_the_installed_sdk_provides_every_name_this_package_uses(real_sdk: Any) -> None:
    """`make deps-livekit` gives the API the transport package was written against (>=1.0,<2)."""
    missing = [name for name in SDK_NAMES if not hasattr(real_sdk, name)]
    assert not missing, missing
    assert hasattr(real_sdk.AudioStream, "from_track")
    assert hasattr(real_sdk.LocalAudioTrack, "create_audio_track")


@pytest.mark.requires_livekit
async def test_connect_reaches_the_real_sdk_and_fails_on_the_network_not_the_import(
    real_sdk: Any,
) -> None:
    """The lazy `from livekit import rtc` inside `connect()` resolves for real.

    Port 1 answers nothing, so a successful import shows up as a *connection* error from the SDK's
    own engine — never `ModuleNotFoundError`, which is exactly what this asserts. `close()` after a
    failed connect must still be safe: a benchmark run that cannot join must not leak a client.
    """
    subject = HeadlessTraineeClient(url="ws://127.0.0.1:1", token="not-a-token", room="r")
    # The SDK raises its own `ConnectError`; catching it by name would need a static import here.
    with pytest.raises(Exception) as caught:
        await subject.connect()
    assert not isinstance(caught.value, ModuleNotFoundError)
    assert (
        "refused" in str(caught.value).lower() or "connect" in type(caught.value).__name__.lower()
    )
    await subject.close()
