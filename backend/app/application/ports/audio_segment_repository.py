"""`AudioSegmentRepository` port — the `audio_segments` table (HLD `20-db-schema.md` §20.6,
`50-voice-pipeline.md` §9.1, D9, SPEC §41).

One row per finalized trainee turn and per caller utterance. The row is an **index into a local
WAV file**, never the audio itself: `file_path` is relative to `Settings.data_dir` so nothing
here pins an absolute machine path into the database, and the retention purge (§9.2) can null the
path while keeping the row, the offsets and the transcript intact (SPEC §28: the same event log
must reproduce the same score).

The ordering guarantee of §9.1 — "the `audio_segments` row is inserted in the same transaction as
the `ASR_FINAL` / `CALLER_TTS_ENDED` event append" — is what makes this a Unit-of-Work repository
rather than a writer of its own: `transcript_segments.audio_segment_id` is then never dangling.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import SessionId

__all__ = ["AudioSegmentRepository", "AudioSpeaker", "StoredAudioSegment"]

AudioSpeaker = Literal["TRAINEE", "CALLER"]
"""`audio_segments.speaker`; the HLD gives the two members literally and `app.domain.enums` has
no counterpart enum (`app.db.models.events.SPEAKERS` is the same pair)."""


class StoredAudioSegment(BaseModel):
    """One `audio_segments` row (§20.6). Values as §9.1's write-path table sets them."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    session_id: SessionId
    speaker: AudioSpeaker
    file_path: str | None
    """Relative to `Settings.data_dir`; `None` once the retention purge has deleted the WAV."""

    format: str = "wav"
    start_ms: int
    """Session-relative start (D9: session-relative, not file-relative)."""

    end_ms: int
    sample_rate: int = 16000
    num_channels: int = 1
    byte_offset: int
    """Offset of `start_ms` inside the file, so a Range request needs no scan."""

    byte_length: int
    purged_at: datetime | None = None
    created_at: datetime


@runtime_checkable
class AudioSegmentRepository(Protocol):
    """`audio_segments`, bound to the caller's Unit of Work transaction."""

    async def add_all(self, segments: Sequence[StoredAudioSegment]) -> None:
        """Insert the segments, in emission order.

        Idempotent by primary key: the recorder derives the id before the append, so a retried
        transaction must not produce a second row for the same segment.
        """
        ...

    async def get(self, audio_segment_id: UUID) -> StoredAudioSegment | None:
        """One row by id, or `None` — `404 NOT_FOUND` for the Range endpoint of §9.1."""
        ...

    async def list_for_session(
        self, session_id: SessionId, *, speaker: AudioSpeaker | None = None
    ) -> list[StoredAudioSegment]:
        """Every segment of one session ordered by `start_ms`, optionally one speaker only."""
        ...
