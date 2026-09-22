"""`RecordingPurgeRepository` port — the `recording_purge_audit` reads/writes of the retention
purge (`docs/hld/50-voice-pipeline.md` §9.2, `docs/hld/20-db-schema.md` §20.6, D9, SPEC §41).

The purge never touches `session_events` (D9's own text: "the log is closed for a completed
session; the audit row is written instead"), so this port — not the event store — is where
`app.application.recording.purge_recordings.PurgeRecordings` reads what is eligible and records
what it did. `mark_purged` nulls `audio_segments.file_path` and sets `.purged_at`, keeping the row
(and therefore every offset, transcript and score that references it) intact — SPEC §28: the same
event log must reproduce the same score, purged or not.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import SessionId

__all__ = ["PurgeCandidateSegment", "RecordingPurgeRepository"]


class PurgeCandidateSegment(BaseModel):
    """One `audio_segments` row eligible for purge: `file_path IS NOT NULL AND purged_at IS NULL`
    and its session is past the retention window."""

    model_config = ConfigDict(frozen=True)

    audio_segment_id: UUID
    session_id: SessionId
    file_path: str
    """Relative to `Settings.data_dir` — the same convention `AudioSegmentRepository` uses."""

    retention_reference_at: datetime
    """`simulation_sessions.completed_at`, or `.created_at` for a session that never completed —
    the retention window's own reference instant (§9.2)."""


@runtime_checkable
class RecordingPurgeRepository(Protocol):
    """`audio_segments` reads for eligibility plus the `recording_purge_audit` write, bound to the
    caller's Unit of Work transaction."""

    async def list_candidates(
        self, *, cutoff: datetime, session_id: SessionId | None = None
    ) -> Sequence[PurgeCandidateSegment]:
        """Every not-yet-purged segment whose session's retention reference is before `cutoff`,
        ordered by `session_id` then `start_ms`; `session_id` narrows to one session (`purge
        --session_id`/`PurgeRecordingsRequest.session_id`)."""
        ...

    async def mark_purged(self, audio_segment_id: UUID, *, purged_at: datetime) -> None:
        """`audio_segments.file_path = NULL, purged_at = purged_at` for one row."""
        ...

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
        """One `recording_purge_audit` row (`reason` is `RETENTION_WINDOW`, `MANUAL_REQUEST` or
        `ADMIN_DELETE`, `20-db-schema.md` §20.6's `CHECK`). `bytes_freed` is `0` when the file was
        already missing on disk — the column is `NOT NULL`, never `NULL`, so a missing file is
        recorded as zero bytes freed rather than an absent value."""
        ...
