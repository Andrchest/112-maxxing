"""`SqlAlchemyRecordingPurgeRepository` over `audio_segments` + `recording_purge_audit` (§9.2,
§20.6, D9, D5).

`list_candidates` joins `audio_segments` to `simulation_sessions` for the retention reference
(`completed_at`, or `created_at` for a session that never completed — §9.2's own wording) rather
than reading the session aggregate through `SessionRepository`: the purge is a bulk, cross-session
sweep, and loading every eligible session's full aggregate to read two columns would be exactly the
kind of "session-domain porcelain for a bulk maintenance job" `50-voice-pipeline.md` §9.1's own
audio-index reasoning already argues against for a single segment's playback.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.recording_purge_repository import PurgeCandidateSegment
from app.db.models.events import AudioSegment as AudioSegmentRow
from app.db.models.events import RecordingPurgeAudit as RecordingPurgeAuditRow
from app.db.models.session import SimulationSession as SimulationSessionRow
from app.domain.common.ids import SessionId

__all__ = ["SqlAlchemyRecordingPurgeRepository"]

_AUDIO_SEGMENTS = AudioSegmentRow.__table__
_SESSIONS = SimulationSessionRow.__table__
_PURGE_AUDIT = RecordingPurgeAuditRow.__table__

#: `simulation_sessions.completed_at`, or `.created_at` when the session never completed — the
#: retention window's own reference instant (§9.2).
_RETENTION_REFERENCE = sa.func.coalesce(_SESSIONS.c.completed_at, _SESSIONS.c.created_at)


class SqlAlchemyRecordingPurgeRepository:
    """`RecordingPurgeRepository` over one `AsyncSession` (bound to the caller's Unit of Work)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_candidates(
        self, *, cutoff: datetime, session_id: SessionId | None = None
    ) -> Sequence[PurgeCandidateSegment]:
        query = (
            sa.select(
                _AUDIO_SEGMENTS.c.id,
                _AUDIO_SEGMENTS.c.session_id,
                _AUDIO_SEGMENTS.c.file_path,
                _RETENTION_REFERENCE.label("retention_reference_at"),
            )
            .select_from(
                _AUDIO_SEGMENTS.join(_SESSIONS, _SESSIONS.c.id == _AUDIO_SEGMENTS.c.session_id)
            )
            .where(_AUDIO_SEGMENTS.c.file_path.is_not(None))
            .where(_AUDIO_SEGMENTS.c.purged_at.is_(None))
            .where(cutoff > _RETENTION_REFERENCE)
            .order_by(_AUDIO_SEGMENTS.c.session_id, _AUDIO_SEGMENTS.c.start_ms)
        )
        if session_id is not None:
            query = query.where(_AUDIO_SEGMENTS.c.session_id == UUID(str(session_id)))
        rows = (await self._session.execute(query)).all()
        return [
            PurgeCandidateSegment(
                audio_segment_id=row.id,
                session_id=SessionId(row.session_id),
                file_path=row.file_path,
                retention_reference_at=row.retention_reference_at,
            )
            for row in rows
        ]

    async def mark_purged(self, audio_segment_id: UUID, *, purged_at: datetime) -> None:
        await self._session.execute(
            sa.update(_AUDIO_SEGMENTS)
            .where(_AUDIO_SEGMENTS.c.id == audio_segment_id)
            .values(file_path=None, purged_at=purged_at)
        )

    async def add_audit_row(
        self,
        *,
        audio_segment_id: UUID,
        session_id: SessionId,
        file_path_was: str,
        bytes_freed: int,
        retention_days: int,
        reason: str,
        actor_type: str,
        actor_user_id: UUID | None,
        purged_at: datetime,
    ) -> None:
        await self._session.execute(
            sa.insert(_PURGE_AUDIT).values(
                purged_at=purged_at,
                actor_type=actor_type,
                actor_user_id=actor_user_id,
                session_id=UUID(str(session_id)),
                audio_segment_id=audio_segment_id,
                file_path_was=file_path_was,
                bytes=bytes_freed,
                retention_days=retention_days,
                reason=reason,
            )
        )
