"""`SqlAlchemyTranscriptSegmentRepository` over `transcript_segments` (§20.6, §9.1, D5, SPEC §19).

`add` inserts `ON CONFLICT (id) DO NOTHING` for the same reason the audio-segment adapter does:
the responder derives the segment id *before* the `ASR_FINAL` append so the event can carry it in
`transcript_segment_id`, and a transaction retried after a serialisation failure must not leave a
second row behind.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.db.models.events import TranscriptSegment as TranscriptSegmentRow
from app.domain.common.ids import SessionId

__all__ = ["SqlAlchemyTranscriptSegmentRepository"]

_TRANSCRIPT_SEGMENTS = TranscriptSegmentRow.__table__


def _row_values(segment: StoredTranscriptSegment) -> dict[str, Any]:
    return {
        "id": segment.id,
        "session_id": UUID(str(segment.session_id)),
        "audio_segment_id": segment.audio_segment_id,
        "speaker": segment.speaker,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "text": segment.text,
        "is_final": segment.is_final,
        "confidence": segment.confidence,
        "asr_provider": segment.asr_provider,
        "asr_model": segment.asr_model,
        "turn_index": segment.turn_index,
    }


def _from_row(row: Mapping[str, Any]) -> StoredTranscriptSegment:
    return StoredTranscriptSegment(
        id=row["id"],
        session_id=SessionId(row["session_id"]),
        audio_segment_id=row["audio_segment_id"],
        speaker=row["speaker"],
        start_ms=row["start_ms"],
        end_ms=row["end_ms"],
        text=row["text"],
        is_final=row["is_final"],
        confidence=row["confidence"],
        asr_provider=row["asr_provider"],
        asr_model=row["asr_model"],
        turn_index=row["turn_index"],
    )


class SqlAlchemyTranscriptSegmentRepository:
    """`TranscriptSegmentRepository` over PostgreSQL, bound to one `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, segment: StoredTranscriptSegment) -> None:
        """Insert the segment; an id already present is left alone."""
        statement = pg_insert(_TRANSCRIPT_SEGMENTS).on_conflict_do_nothing(index_elements=["id"])
        await self._session.execute(statement, _row_values(segment))

    async def list_for_session(self, session_id: SessionId) -> list[StoredTranscriptSegment]:
        """Every segment of one session ordered by `start_ms`."""
        result = await self._session.execute(
            sa.select(_TRANSCRIPT_SEGMENTS)
            .where(_TRANSCRIPT_SEGMENTS.c.session_id == UUID(str(session_id)))
            .order_by(_TRANSCRIPT_SEGMENTS.c.start_ms, _TRANSCRIPT_SEGMENTS.c.id)
        )
        return [_from_row(row._mapping) for row in result.all()]
