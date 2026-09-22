"""`LiveKitCallTransport` — the one module in the workspace that may import the LiveKit SDK.

D9 and SPEC §15 draw the line here: "Domain logic must not import LiveKit objects." Everything
above this file speaks `AudioFrame` / `TransportEvent` / `PlaybackHandle`;
`backend/tools/check_imports.py` enforces that `livekit` appears nowhere else, in `backend/**` or
in any other `workers/**` module, and a sabotage test proves the rule bites.

The mapping is §2.1's table, literally:

| Port element | LiveKit rtc call |
|:--|:--|
| `connect` | `rtc.Room().connect(url, token)` with a backend-minted token |
| `inbound_audio` | `rtc.AudioStream.from_track(track, sample_rate=48000, num_channels=1)` |
| `play` | `rtc.AudioSource(..., queue_size_ms=outbound_queue_ms)` + `capture_frame` |
| `clear_outbound` | `AudioSource.clear_queue()` |
| queued audio | `AudioSource.queued_duration` (seconds, float) |
| natural end | `await AudioSource.wait_for_playout()` |
| `events` | `Room` callbacks pushed into an `asyncio.Queue` |
| `disconnect` | `AudioSource.aclose()` then `Room.disconnect()` |

The SDK is imported **inside** `connect()`, not at module scope, for one reason: `livekit` is an
optional extra (D1 — heavy dependencies are extras and adapters import them lazily), and the whole
E11 gate runs against `FakeCallTransport` with no LiveKit installed. Importing at module scope
would make this file unimportable — and therefore untestable for its *shape* — on a machine that
has never seen the SDK.

The token is minted by the backend (`createVoiceToken`, E11-B): a LiveKit access token is a plain
HS256 JWT, the backend already has `pyjwt`, and that is why `backend/**` never needs `livekit-api`
at all.

**Offsets come from the session, never from this transport (R13, E19-E3 bug #5).** `_now_ms()`
used to be `time.monotonic_ns()` minus this transport's own first reading — "ms since my first
frame". A session starts well before the agent's transport does (create → ring → join → answer),
so `USER_SPEECH_ENDED.at_offset_ms`, which derives from `AudioFrame.capture_offset_ms`, was
stamped against a different zero than `CALLER_TTS_STARTED.first_audio_offset_ms`, which
`VoiceEventAppender` takes from the session. SPEC §27's `speech_end_to_first_audio_ms` is their
difference, so on the real media plane every one of E19-E3's 34 samples came out negative and drew
further apart each turn, and the benchmark had to discard the lot. The transport is now given the
session's `started_at` and the same injected `Clock` the appender holds, and stamps through the
same `session_offset_ms` helper — one origin for the whole call, which is what
`app.application.ports.call_transport` has always specified.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.application.ports.call_transport import (
    AudioFrame,
    PlaybackHandle,
    TransportError,
    TransportEvent,
    TransportEventType,
)
from app.application.ports.clock import Clock
from app.application.timebase import session_offset_ms
from app.application.voice.playback import ChunkedPlayback

if TYPE_CHECKING:  # pragma: no cover - typing only; the SDK is an optional extra
    from livekit import rtc

__all__ = ["LiveKitCallTransport", "LiveKitPlayoutSink"]

logger = logging.getLogger(__name__)

_INBOUND_SAMPLE_RATE = 48_000
_INBOUND_CHANNELS = 1
_MS_PER_S = 1000


class LiveKitPlayoutSink:
    """`PlayoutSink` over one `rtc.AudioSource` (§2.1's `play` / `clear_outbound` rows)."""

    def __init__(self, source: Any, *, capacity_ms: int, sample_rate: int) -> None:
        self._source = source
        self._capacity_ms = capacity_ms
        self._sample_rate = sample_rate

    @property
    def capacity_ms(self) -> int:
        """`outbound_queue_ms`, which is the `AudioSource`'s own `queue_size_ms`."""
        return self._capacity_ms

    async def capture_frame(self, frame: AudioFrame) -> None:
        """`AudioSource.capture_frame` — it back-pressures while the queue is full."""
        from livekit import rtc

        await self._source.capture_frame(
            rtc.AudioFrame(
                data=frame.pcm,
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
                samples_per_channel=frame.samples_per_channel,
            )
        )

    def queued_duration_ms(self) -> int:
        """`AudioSource.queued_duration` in seconds, as whole milliseconds (§6.3)."""
        return round(float(self._source.queued_duration) * _MS_PER_S)

    def clear_queue(self) -> None:
        """`AudioSource.clear_queue()` — the call that actually stops sound (SPEC §18 step 3)."""
        self._source.clear_queue()

    async def wait_for_playout(self) -> None:
        """`AudioSource.wait_for_playout()`."""
        await self._source.wait_for_playout()


class LiveKitCallTransport:
    """A `CallTransport` over a self-hosted LiveKit room (SPEC §15, D9)."""

    def __init__(
        self,
        *,
        url: str,
        token: str,
        outbound_queue_ms: int,
        outbound_sample_rate: int,
        clock: Clock,
        started_at: datetime | None,
        identity: str = "caller",
    ) -> None:
        self._url = url
        self._token = token
        #: The session's own time base (R13): both are required, so a transport can never be
        #: built without the origin its offsets are defined against.
        self._clock = clock
        self._started_at = started_at
        self._outbound_queue_ms = outbound_queue_ms
        self._outbound_sample_rate = outbound_sample_rate
        self._identity = identity
        self._call_id: uuid.UUID | None = None
        self._room: Any = None
        self._source: Any = None
        self._sink: LiveKitPlayoutSink | None = None
        self._audio_queue: asyncio.Queue[AudioFrame | None] = asyncio.Queue()
        self._events: asyncio.Queue[TransportEvent | None] = asyncio.Queue()
        self._pumps: list[asyncio.Task[None]] = []

    # -- the CallTransport port ---------------------------------------------------------------

    async def connect(self, call_id: uuid.UUID) -> None:
        """`rtc.Room().connect(url, token)`, then publish our outbound track. Idempotent."""
        if self._room is not None:
            return
        try:
            from livekit import rtc
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise TransportError(
                "the `livekit` SDK is not installed; install the voice extra or run with "
                "SIM_CALL_TRANSPORT=fake"
            ) from exc
        self._call_id = call_id
        room = rtc.Room()
        self._wire_room_events(room, call_id)
        try:
            await room.connect(self._url, self._token)
        except Exception as exc:
            raise TransportError(f"could not join the LiveKit room for call {call_id}") from exc
        self._room = room
        source = rtc.AudioSource(
            sample_rate=self._outbound_sample_rate,
            num_channels=_INBOUND_CHANNELS,
            queue_size_ms=self._outbound_queue_ms,
        )
        track = rtc.LocalAudioTrack.create_audio_track(self._identity, source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        self._source = source
        self._sink = LiveKitPlayoutSink(
            source,
            capacity_ms=self._outbound_queue_ms,
            sample_rate=self._outbound_sample_rate,
        )
        self._emit(TransportEventType.CONNECTED, detail=self._url)

    async def inbound_audio(self) -> AsyncIterator[AudioFrame]:
        """Frames of the first subscribed remote audio track, in capture order."""
        while True:
            frame = await self._audio_queue.get()
            if frame is None:
                return
            yield frame

    async def play(self, frames: AsyncIterator[AudioFrame]) -> PlaybackHandle:
        """Chunked playback over the published `AudioSource` (§6.1–§6.3)."""
        if self._sink is None:
            raise TransportError("play() before connect()")
        playback = ChunkedPlayback(frames, self._sink, now_ms=self._now_ms)
        playback.start()
        return playback

    async def clear_outbound(self) -> None:
        """`AudioSource.clear_queue()` (SPEC §18 step 3)."""
        if self._sink is not None:
            self._sink.clear_queue()

    async def events(self) -> AsyncIterator[TransportEvent]:
        """Room events, ending when `disconnect()` pushes the sentinel."""
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    async def disconnect(self) -> None:
        """`AudioSource.aclose()` then `Room.disconnect()`. Idempotent."""
        for task in self._pumps:
            if not task.done():
                task.cancel()
        self._pumps = []
        source, self._source, self._sink = self._source, None, None
        room, self._room = self._room, None
        if source is not None:
            await source.aclose()
        if room is not None:
            await room.disconnect()
        self._audio_queue.put_nowait(None)
        self._events.put_nowait(None)

    # -- internals ----------------------------------------------------------------------------

    def _now_ms(self) -> int:
        """The session offset of *now* — the one origin of R13, shared with every appended event.

        `ChunkedPlayback` reads this too, and is unaffected: it only ever takes differences, and
        this counter advances in real milliseconds exactly as the old one did.
        """
        return session_offset_ms(self._clock.now(), self._started_at)

    def _emit(
        self,
        event_type: TransportEventType,
        *,
        participant_identity: str | None = None,
        detail: str | None = None,
    ) -> None:
        call_id = self._call_id
        if call_id is None:  # pragma: no cover - never emitted before connect()
            return
        self._events.put_nowait(
            TransportEvent(
                type=event_type,
                call_id=call_id,
                at_offset_ms=self._now_ms(),
                participant_identity=participant_identity,
                detail=detail,
            )
        )

    def _wire_room_events(self, room: rtc.Room, call_id: uuid.UUID) -> None:
        """Push `Room` callbacks into the event queue (§2.1's `events` row)."""

        @room.on("participant_connected")
        def _on_participant_connected(participant: Any) -> None:
            self._emit(
                TransportEventType.PARTICIPANT_JOINED,
                participant_identity=participant.identity,
            )

        @room.on("participant_disconnected")
        def _on_participant_disconnected(participant: Any) -> None:
            self._emit(
                TransportEventType.PARTICIPANT_LEFT,
                participant_identity=participant.identity,
            )

        @room.on("track_subscribed")
        def _on_track_subscribed(track: Any, publication: Any, participant: Any) -> None:
            self._emit(
                TransportEventType.TRACK_SUBSCRIBED, participant_identity=participant.identity
            )
            self._pumps.append(asyncio.create_task(self._pump_track(track), name="livekit-inbound"))

        @room.on("track_unsubscribed")
        def _on_track_unsubscribed(track: Any, publication: Any, participant: Any) -> None:
            self._emit(
                TransportEventType.TRACK_UNSUBSCRIBED, participant_identity=participant.identity
            )

        @room.on("reconnecting")
        def _on_reconnecting() -> None:
            self._emit(TransportEventType.RECONNECTING)

        @room.on("reconnected")
        def _on_reconnected() -> None:
            self._emit(TransportEventType.RECONNECTED)

        @room.on("disconnected")
        def _on_disconnected(*args: Any) -> None:
            self._emit(TransportEventType.DISCONNECTED, detail=str(args[0]) if args else None)
            self._audio_queue.put_nowait(None)

    async def _pump_track(self, track: Any) -> None:
        """`rtc.AudioStream.from_track(...)` → our `AudioFrame`s (§2.1's `inbound_audio` row)."""
        from livekit import rtc

        stream = rtc.AudioStream.from_track(
            track=track, sample_rate=_INBOUND_SAMPLE_RATE, num_channels=_INBOUND_CHANNELS
        )
        try:
            async for event in stream:
                frame = event.frame
                self._audio_queue.put_nowait(
                    AudioFrame(
                        pcm=bytes(frame.data),
                        sample_rate=frame.sample_rate,
                        num_channels=frame.num_channels,
                        samples_per_channel=frame.samples_per_channel,
                        capture_offset_ms=self._now_ms(),
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LiveKit inbound track pump failed")
            self._emit(TransportEventType.TRANSPORT_ERROR, detail="inbound track pump failed")
