"""`CallTransport` port and its value types (HLD `50-voice-pipeline.md` §2.1, D9, SPEC §15).

The media plane is behind a port so that a future SIP/PSTN transport is a file and not a
refactor, and so that no LiveKit object ever crosses into `app.domain` / `app.application`
(SPEC §15: "Domain logic must not import LiveKit objects"). `LiveKitCallTransport`
(`workers/voice_agent/voice_agent/transport/livekit_transport.py`) is the only module in the
workspace allowed to import the `livekit` SDK; `backend/tools/check_imports.py` enforces it.

Every type here is our own: `AudioFrame` is PCM s16le bytes plus the four numbers a consumer
needs, and `capture_offset_ms` is a **session** offset taken from the injected `Clock`
(`app.application.timebase.session_offset_ms`), never a wall clock and never the transport's own
timeline (D5, D7).

**One clock origin, and it is the port's contract, not a transport's private choice (R13).**
`AudioFrame.capture_offset_ms` and `TransportEvent.at_offset_ms` are defined as
`session_offset_ms(clock.now(), session.started_at)` — milliseconds since `SESSION_STARTED` — which
is the same helper, the same `Clock` and the same origin that `VoiceEventAppender.offset_ms()` uses
for every event the pipeline writes. A transport is therefore constructed with the session's
`started_at`, not left to invent a zero. `LiveKitCallTransport` used to measure from its **own**
first frame; because a session starts well before the agent's transport does (create → ring → join
→ answer), `USER_SPEECH_ENDED.at_offset_ms` and `CALLER_TTS_STARTED.first_audio_offset_ms` were
then stamped against two different zeros, and SPEC §27's `speech_end_to_first_audio_ms` — their
difference — came out **negative and drifting further every turn** on the real media plane. E19-E3
measured 34 such samples and the benchmark discarded all of them rather than publish a percentile
over impossible numbers. In process the two happened to share a clock, which is the only reason the
in-process figures were ever sound.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "AudioFrame",
    "CallTransport",
    "DeliveredAudio",
    "PlaybackHandle",
    "TransportError",
    "TransportEvent",
    "TransportEventType",
]


class TransportError(RuntimeError):
    """A transport-level failure: the room could not be joined, or the media plane went away."""


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """One block of PCM audio. Our own type: no LiveKit object crosses this boundary (SPEC §15)."""

    pcm: bytes
    """PCM s16le, little-endian, interleaved."""

    sample_rate: int
    """Hz, e.g. 48000 inbound from LiveKit, 16000 after the `Resampler`."""

    num_channels: int
    """1 after the `Resampler`; transports may deliver 1 or 2."""

    samples_per_channel: int
    """`len(pcm) == samples_per_channel * num_channels * 2`."""

    capture_offset_ms: int
    """Milliseconds since `SESSION_STARTED`, from the `Clock`; never a wall clock.

    Exactly `app.application.timebase.session_offset_ms(clock.now(), session.started_at)` — the
    same origin every event in the log is stamped against, so a subtraction across the two
    (SPEC §27's `speech_end_to_first_audio_ms`) is meaningful. **Never** a transport-local
    timeline such as "ms since this transport's first frame" (R13).
    """

    @property
    def duration_ms(self) -> int:
        """The frame's length in whole milliseconds at its own sample rate."""
        return (self.samples_per_channel * 1000) // self.sample_rate


class TransportEventType(enum.StrEnum):
    """What the media plane reports about itself (§2.1)."""

    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    RECONNECTED = "RECONNECTED"
    PARTICIPANT_JOINED = "PARTICIPANT_JOINED"
    PARTICIPANT_LEFT = "PARTICIPANT_LEFT"
    TRACK_SUBSCRIBED = "TRACK_SUBSCRIBED"
    TRACK_UNSUBSCRIBED = "TRACK_UNSUBSCRIBED"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"


@dataclass(frozen=True, slots=True)
class TransportEvent:
    """One media-plane notification, stamped with the same session offset as an `AudioFrame`.

    `at_offset_ms` is `session_offset_ms(clock.now(), session.started_at)`, the same origin (R13).
    """

    type: TransportEventType
    call_id: uuid.UUID
    at_offset_ms: int
    participant_identity: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveredAudio:
    """What a cancelled or finished playback actually put on the wire (§6.3, SPEC §18 step 6)."""

    delivered_audio_ms: int
    """Audio actually emitted to the transport, playout-adjusted."""

    total_audio_ms_generated: int
    """Audio the TTS produced, delivered or not."""

    frames_delivered: int
    frames_discarded: int

    cancelled: bool
    """True when `cancel()` ended the playback, False on a natural end."""


@runtime_checkable
class PlaybackHandle(Protocol):
    """Handle over one outbound utterance. Returned by `CallTransport.play()`."""

    @property
    def playback_id(self) -> uuid.UUID:
        """Identity of this playback, so a late `cancel()` cannot hit the next utterance."""
        ...

    @property
    def started_offset_ms(self) -> int | None:
        """Offset of the first frame actually handed to the transport; None until then."""
        ...

    async def cancel(self) -> DeliveredAudio:
        """Stop playback now, drop queued frames, return what was delivered. Idempotent."""
        ...

    async def wait_done(self) -> DeliveredAudio:
        """Await natural end of playback (queue drained)."""
        ...

    def is_active(self) -> bool:
        """True while frames are still being pulled or played out."""
        ...


@runtime_checkable
class CallTransport(Protocol):
    """The media plane of one call (§2.1, D9)."""

    async def connect(self, call_id: uuid.UUID) -> None:
        """Join the media room for this call. Idempotent; raises `TransportError` on failure."""
        ...

    def inbound_audio(self) -> AsyncIterator[AudioFrame]:
        """Trainee microphone frames, in capture order. Ends when the transport disconnects."""
        ...

    async def play(self, frames: AsyncIterator[AudioFrame]) -> PlaybackHandle:
        """Start pulling `frames` and emitting them. Returns as soon as playback is scheduled."""
        ...

    async def clear_outbound(self) -> None:
        """Discard every frame already queued in the transport's outbound buffer."""
        ...

    def events(self) -> AsyncIterator[TransportEvent]:
        """Media-plane notifications, in arrival order."""
        ...

    async def disconnect(self) -> None:
        """Leave the room and release the media resources. Idempotent."""
        ...
