"""`SqlAlchemyAudioSegmentRepository` over `audio_segments` (§20.6, §9.1, D5, D9).

One table, one class. ORM rows never leave this module; the conversion to and from
`StoredAudioSegment` is the two private helpers below — `audio_segments` is written by exactly
one caller (`app.application.voice.recorder.SessionRecorder`) and read by exactly one (the Range
endpoint of §9.1), so the mapping has no second home to be shared with.

`add_all` inserts `ON CONFLICT (id) DO NOTHING` for the same reason the notification adapter
does: the recorder derives the segment id *before* the event append so that
`transcript_segments.audio_segment_id` can point at it, and a transaction retried after a
serialisation failure must not leave two rows behind.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.audio_segment_repository import (
    AudioSpeaker,
    StoredAudioSegment,
)
from app.db.models.events import AudioSegment as AudioSegmentRow
from app.domain.common.ids import SessionId

__all__ = ["SqlAlchemyAudioSegmentRepository"]

_AUDIO_SEGMENTS = AudioSegmentRow.__table__


def _row_values(segment: StoredAudioSegment) -> dict[str, Any]:
    return {
        "id": segment.id,
        "session_id": UUID(str(segment.session_id)),
        "speaker": segment.speaker,
        "file_path": segment.file_path,
        "format": segment.format,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "sample_rate": segment.sample_rate,
        "num_channels": segment.num_channels,
        "byte_offset": segment.byte_offset,
        "byte_length": segment.byte_length,
        "purged_at": segment.purged_at,
        "created_at": segment.created_at,
    }


def _from_row(row: Mapping[str, Any]) -> StoredAudioSegment:
    return StoredAudioSegment(
        id=row["id"],
        session_id=SessionId(row["session_id"]),
        speaker=row["speaker"],
        file_path=row["file_path"],
        format=row["format"],
        start_ms=row["start_ms"],
        end_ms=row["end_ms"],
        sample_rate=row["sample_rate"],
        num_channels=row["num_channels"],
        byte_offset=row["byte_offset"],
        byte_length=row["byte_length"],
        purged_at=row["purged_at"],
        created_at=row["created_at"],
    )


class SqlAlchemyAudioSegmentRepository:
    """`AudioSegmentRepository` over PostgreSQL, bound to one `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, segments: Sequence[StoredAudioSegment]) -> None:
        """Insert the segments; an id already present is left alone."""
        if not segments:
            return
        statement = pg_insert(_AUDIO_SEGMENTS).on_conflict_do_nothing(index_elements=["id"])
        await self._session.execute(statement, [_row_values(segment) for segment in segments])

    async def get(self, audio_segment_id: UUID) -> StoredAudioSegment | None:
        """One row by id, or `None`."""
        result = await self._session.execute(
            sa.select(_AUDIO_SEGMENTS).where(_AUDIO_SEGMENTS.c.id == audio_segment_id)
        )
        row = result.first()
        return None if row is None else _from_row(row._mapping)

    async def list_for_session(
        self, session_id: SessionId, *, speaker: AudioSpeaker | None = None
    ) -> list[StoredAudioSegment]:
        """Every segment of one session ordered by `start_ms`."""
        statement = sa.select(_AUDIO_SEGMENTS).where(
            _AUDIO_SEGMENTS.c.session_id == UUID(str(session_id))
        )
        if speaker is not None:
            statement = statement.where(_AUDIO_SEGMENTS.c.speaker == speaker)
        result = await self._session.execute(
            statement.order_by(_AUDIO_SEGMENTS.c.start_ms, _AUDIO_SEGMENTS.c.id)
        )
        return [_from_row(row._mapping) for row in result.all()]
