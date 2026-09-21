"""`SessionRecorder` — the call recording and its `audio_segments` index (§9.1, D9, SPEC §41).

Two WAV files per call, 16 kHz mono s16le, written incrementally as the audio goes past:

```
DATA_DIR/recordings/{session_id}/trainee-{call_id}.wav
DATA_DIR/recordings/{session_id}/caller-{call_id}.wav
```

The trainee file is *continuous* call audio — `_ingest` tees every resampled frame into it,
silence included — which is what makes a segment's `byte_offset` a plain arithmetic function of
its start offset and lets the Range endpoint of §9.1 serve a turn without scanning the file. The
caller file is teed from the frames the `PlaybackHandle` actually captured, so on a barge-in it
holds what was *heard* and not what was generated.

One `audio_segments` row per finalized turn. The row is built here and handed to the caller, which
inserts it **in the same Unit of Work transaction as the event append that names it** (§9.1's
ordering guarantee): `transcript_segments.audio_segment_id` is then never dangling, and killing
the transaction leaves neither the row nor the event — which is exactly what this task's
integration test asserts.

The byte plane is behind `AudioSink` so that the application layer stays free of file I/O; the
file-backed implementation is `app.infrastructure.recording.wav_writer.WavFileSink`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.application.ports.audio_segment_repository import AudioSpeaker, StoredAudioSegment
from app.application.ports.call_transport import AudioFrame
from app.application.ports.clock import Clock
from app.application.voice.config import BYTES_PER_SAMPLE, MS_PER_S, VoiceTurnConfig
from app.domain.common.ids import SessionId

__all__ = ["AudioSink", "RecordingPaths", "SessionRecorder"]


@runtime_checkable
class AudioSink(Protocol):
    """One growing PCM stream on disk (or in memory, in a test)."""

    @property
    def relative_path(self) -> str:
        """The path stored in `audio_segments.file_path`, relative to `Settings.data_dir`."""
        ...

    @property
    def bytes_written(self) -> int:
        """PCM bytes written so far, excluding any container header."""
        ...

    def write(self, pcm: bytes) -> None:
        """Append PCM s16le bytes."""
        ...

    def close(self) -> None:
        """Finalise the container (a WAV header needs its final sizes). Idempotent."""
        ...


@dataclass(frozen=True, slots=True)
class RecordingPaths:
    """Where one call's two recordings live, relative to `Settings.data_dir` (§9.1)."""

    trainee: str
    caller: str

    @staticmethod
    def for_call(session_id: SessionId, call_id: uuid.UUID) -> RecordingPaths:
        """`recordings/{session_id}/{trainee,caller}-{call_id}.wav`."""
        folder = f"recordings/{session_id}"
        return RecordingPaths(
            trainee=f"{folder}/trainee-{call_id}.wav",
            caller=f"{folder}/caller-{call_id}.wav",
        )


class SessionRecorder:
    """Tees call audio to disk and builds the `audio_segments` rows (§9.1)."""

    def __init__(
        self,
        *,
        session_id: SessionId,
        call_id: uuid.UUID,
        config: VoiceTurnConfig,
        clock: Clock,
        trainee_sink: AudioSink,
        caller_sink: AudioSink,
    ) -> None:
        self._session_id = session_id
        self._call_id = call_id
        self._config = config
        self._clock = clock
        self._sinks: dict[AudioSpeaker, AudioSink] = {
            "TRAINEE": trainee_sink,
            "CALLER": caller_sink,
        }
        #: Byte offset in the trainee file of the first sample this recorder ever saw, paired
        #: with that sample's session offset — the anchor every `byte_offset` is derived from.
        self._anchor_offset_ms: dict[AudioSpeaker, int] = {}
        self._closed = False

    @property
    def session_id(self) -> SessionId:
        """The session these recordings belong to."""
        return self._session_id

    @property
    def call_id(self) -> uuid.UUID:
        """The call these recordings belong to."""
        return self._call_id

    def bytes_written(self, speaker: AudioSpeaker) -> int:
        """PCM bytes written for one speaker so far."""
        return self._sinks[speaker].bytes_written

    def tee(self, speaker: AudioSpeaker, frame: AudioFrame) -> None:
        """Write one frame into the speaker's file (the `_ingest` / `_respond` tee of §9.1)."""
        if self._closed:
            raise RuntimeError("the recorder is closed")
        self._anchor_offset_ms.setdefault(speaker, frame.capture_offset_ms)
        self._sinks[speaker].write(frame.pcm)

    def segment_for(
        self,
        speaker: AudioSpeaker,
        *,
        start_ms: int,
        end_ms: int,
        segment_id: uuid.UUID | None = None,
    ) -> StoredAudioSegment:
        """Build the `audio_segments` row for `[start_ms, end_ms)` of this speaker's file.

        `start_ms` / `end_ms` are **session-relative** (D9), and `byte_offset` / `byte_length`
        locate the same interval inside the file, so an HTTP Range request needs no scan. Both
        are clamped to what has actually been written: a turn whose trailing silence was trimmed
        must not point past the end of the file.
        """
        if end_ms < start_ms:
            raise ValueError("an audio segment cannot end before it starts")
        anchor = self._anchor_offset_ms.get(speaker, start_ms)
        written = self._sinks[speaker].bytes_written
        byte_offset = min(written, self._ms_to_bytes(max(0, start_ms - anchor)))
        byte_length = min(written - byte_offset, self._ms_to_bytes(end_ms - start_ms))
        return StoredAudioSegment(
            id=segment_id if segment_id is not None else uuid.uuid4(),
            session_id=self._session_id,
            speaker=speaker,
            file_path=self._sinks[speaker].relative_path,
            format="wav",
            start_ms=start_ms,
            end_ms=end_ms,
            sample_rate=self._config.sample_rate,
            num_channels=1,
            byte_offset=byte_offset,
            byte_length=byte_length,
            purged_at=None,
            created_at=self._clock.now(),
        )

    def close(self) -> None:
        """Finalise both WAV containers. Idempotent."""
        if self._closed:
            return
        self._closed = True
        for sink in self._sinks.values():
            sink.close()

    def _ms_to_bytes(self, milliseconds: int) -> int:
        frame_bytes = self._config.sample_rate * BYTES_PER_SAMPLE
        aligned = (milliseconds * frame_bytes) // MS_PER_S
        return aligned - (aligned % BYTES_PER_SAMPLE)
