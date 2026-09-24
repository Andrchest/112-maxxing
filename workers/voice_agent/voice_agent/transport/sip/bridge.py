"""One SIP dialog ↔ one room participant (HLD 80 §80.2.1 `bridge.py`, §80.2.2).

The gateway speaks 8 kHz s16le mono in 20 ms frames (320 bytes) on both sides of a `RoomPort`:

* `push(pcm)` — the softphone's voice (decoded RTP, after the jitter buffer) into the room;
* `on_audio(pcm)` — the callback `open()` is given: the room's audio, back towards the softphone.

`FakeRoomBridge` is the gate's room (it loops audio back, or records it). `LiveKitRoomBridge`
joins a real LiveKit room with the rtc SDK — the softphone's audio is published as its microphone
track, and the first remote audio track is played back as RTP — so a SIP call is one more room
participant exactly like the browser, and the agent's `LiveKitCallTransport` stays unchanged. Its
room identity is `sip-{call_id}` and its token is minted locally by the caller (80 §80.1: no token
travels over Redis or to the gateway).

The SDK is imported **inside** the methods, as in `livekit_transport.py`: the module stays
importable, and the gate green, on a venv without the `transport-livekit` extra (D1, D13).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any, Protocol

from voice_agent.transport.sip.rtp import CLOCK_RATE, FRAME_BYTES, Resampler

__all__ = [
    "FakeRoomBridge",
    "LiveKitRoomBridge",
    "RoomPort",
    "room_factory_for",
    "sip_participant_identity",
]

logger = logging.getLogger(__name__)

ROOM_SAMPLE_RATE = 48_000
AudioSink = Callable[[bytes], None]


def sip_participant_identity(call_id: str) -> str:
    """The gateway's identity in a call's room (§80.2.1: `sip-{call_id}`)."""
    return f"sip-{call_id}"


class RoomPort(Protocol):
    """What the gateway needs from "the room" of one call."""

    async def open(self, on_audio: AudioSink) -> None:
        """Join; from now on the room's audio arrives as 8 kHz 20 ms frames on `on_audio`."""
        ...

    async def push(self, pcm: bytes) -> None:
        """One 20 ms 8 kHz frame of the softphone's voice into the room."""
        ...

    async def close(self) -> None:
        """Leave. Idempotent."""
        ...


class FakeRoomBridge:
    """The gate's room: `loopback` sends every pushed frame straight back; `record` keeps them."""

    def __init__(self, *, mode: str = "loopback") -> None:
        if mode not in ("loopback", "record"):
            raise ValueError(f"unknown FakeRoomBridge mode {mode!r}")
        self.mode = mode
        self.frames: list[bytes] = []
        self.opened = False
        self.closed = False
        self._on_audio: AudioSink | None = None

    async def open(self, on_audio: AudioSink) -> None:
        self._on_audio = on_audio
        self.opened = True

    async def push(self, pcm: bytes) -> None:
        self.frames.append(pcm)
        if self.mode == "loopback" and self._on_audio is not None and not self.closed:
            self._on_audio(pcm)

    def play(self, pcm: bytes) -> None:
        """Test hook: the room "speaks" a frame towards the softphone."""
        if self._on_audio is not None and not self.closed:
            self._on_audio(pcm)

    async def close(self) -> None:
        self.closed = True


class LiveKitRoomBridge:
    """A `RoomPort` over a LiveKit room (rtc SDK; `livekit` 1.x)."""

    def __init__(
        self,
        *,
        url: str,
        token: str,
        identity: str,
        queue_ms: int = 100,
    ) -> None:
        self._url = url
        self._token = token
        self.identity = identity
        self._queue_ms = queue_ms
        self._room: Any = None
        self._source: Any = None
        self._on_audio: AudioSink | None = None
        self._up = Resampler(CLOCK_RATE, ROOM_SAMPLE_RATE)
        self._pumps: list[asyncio.Task[None]] = []
        self._subscribed = False
        #: Set once the first remote audio track is subscribed (a benchmark waits on it).
        self.track_subscribed = asyncio.Event()

    async def open(self, on_audio: AudioSink) -> None:
        from livekit import rtc

        self._on_audio = on_audio
        room = rtc.Room()

        @room.on("track_subscribed")
        def _on_track(track: Any, _publication: Any, participant: Any) -> None:
            if track.kind != rtc.TrackKind.KIND_AUDIO or self._subscribed:
                return
            self._subscribed = True
            logger.info("bridge %s: subscribed to %s", self.identity, participant.identity)
            self._pumps.append(asyncio.create_task(self._pump(track), name="sip-bridge-pump"))
            self.track_subscribed.set()

        await room.connect(self._url, self._token)
        source = rtc.AudioSource(ROOM_SAMPLE_RATE, 1, queue_size_ms=self._queue_ms)
        track = rtc.LocalAudioTrack.create_audio_track(self.identity, source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        self._room = room
        self._source = source

    async def push(self, pcm: bytes) -> None:
        from livekit import rtc

        if self._source is None:
            return
        data = self._up.convert(pcm)
        samples = len(data) // 2
        if samples == 0:
            return
        await self._source.capture_frame(
            rtc.AudioFrame(
                data=data[: samples * 2],
                sample_rate=ROOM_SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=samples,
            )
        )

    async def _pump(self, track: Any) -> None:
        from livekit import rtc

        down = Resampler(ROOM_SAMPLE_RATE, CLOCK_RATE)
        pending = bytearray()
        stream = rtc.AudioStream.from_track(
            track=track, sample_rate=ROOM_SAMPLE_RATE, num_channels=1
        )
        try:
            async for event in stream:
                pending.extend(down.convert(bytes(event.frame.data)))
                while len(pending) >= FRAME_BYTES:
                    frame = bytes(pending[:FRAME_BYTES])
                    del pending[:FRAME_BYTES]
                    if self._on_audio is not None:
                        self._on_audio(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("bridge %s: inbound track pump failed", self.identity)
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()

    async def close(self) -> None:
        for task in self._pumps:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        self._pumps = []
        source, self._source = self._source, None
        room, self._room = self._room, None
        if source is not None:
            with contextlib.suppress(Exception):
                await source.aclose()
        if room is not None:
            with contextlib.suppress(Exception):
                await room.disconnect()


def room_factory_for(url: str, api_key: str, api_secret: str) -> Callable[[Any], RoomPort]:
    """The gateway's `RoomFactory` for real (I3 E6e): a ДДС call's room (`dialed.room_name`),
    joined as `sip-{call_id}` with a token minted locally by the backend's own
    `LiveKitTokenService` — no token travels over Redis or from the backend (80 §80.1)."""
    from app.infrastructure.transport.livekit_token_service import LiveKitTokenService

    tokens = LiveKitTokenService(api_key, api_secret, livekit_url=url, ttl_minutes=10)

    def make(dialed: Any) -> RoomPort:
        identity = sip_participant_identity(dialed.call_id)
        token = tokens.mint(room_name=dialed.room_name, participant_identity=identity).token
        return LiveKitRoomBridge(url=url, token=token, identity=identity)

    return make
