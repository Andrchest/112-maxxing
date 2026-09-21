"""`TranscriptSegmentRepository` port — the `transcript_segments` table (HLD `20-db-schema.md`
§20.6, `50-voice-pipeline.md` §9.1, SPEC §19).

One row per finalized recognition: per `ASR_FINAL` on the trainee side (E12) and per completed or
interrupted caller utterance on the other (E14, `asr_provider` / `asr_model` both `NULL` there).
**Partials are never written** — §4.5 says so literally, and the reason is SPEC §17: a partial is
a hypothesis that may be withdrawn, and the transcript is the record the report and the scoring
timeline are read from.

The fields are SPEC §19's `TranscriptSegment` list, and `audio_segment_id` is what ties a line of
text to the audio it came from; §9.1 requires the row and the `ASR_FINAL` that names it to commit
in **one** transaction, which is why this is a Unit-of-Work repository and not a writer of its
own.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import SessionId

__all__ = [
    "StoredTranscriptSegment",
    "TranscriptSegmentRepository",
    "TranscriptSpeaker",
]

TranscriptSpeaker = Literal["TRAINEE", "CALLER"]
"""`transcript_segments.speaker`; the same literal pair as `audio_segments.speaker`."""


class StoredTranscriptSegment(BaseModel):
    """One `transcript_segments` row (§20.6, SPEC §19)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    session_id: SessionId
    audio_segment_id: UUID | None = None
    """The recording this text was produced from; `NULL` once the purge removed the segment."""

    speaker: TranscriptSpeaker
    start_ms: int
    """Session-relative, like every other offset in the voice path (D9)."""

    end_ms: int
    text: str
    is_final: bool = True
    confidence: float | None = None
    asr_provider: str | None = None
    """`None` for a caller row — the caller's words were generated, not recognised (§9.1)."""

    asr_model: str | None = None
    turn_index: int | None = None


@runtime_checkable
class TranscriptSegmentRepository(Protocol):
    """`transcript_segments`, bound to the caller's Unit of Work transaction."""

    async def add(self, segment: StoredTranscriptSegment) -> None:
        """Insert one segment.

        Idempotent by primary key: the id is derived before the `ASR_FINAL` append so the event
        can carry it, and a transaction retried after a serialisation failure must not leave a
        second row behind.
        """
        ...

    async def list_for_session(self, session_id: SessionId) -> list[StoredTranscriptSegment]:
        """Every segment of one session ordered by `start_ms` (§20.6's index order)."""
        ...
