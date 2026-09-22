"""`PurgeRecordings` — the retention purge use case (`docs/hld/50-voice-pipeline.md` §9.2,
`docs/hld/20-db-schema.md` §20.6, D9, SPEC §41, R8).

**One use case, two front doors** (this task's ruling R8): `python -m app.cli purge_recordings
[--dry-run] [--older-than-days N]` (`app.cli.purge_recordings`) and `POST
/api/v1/admin/recordings/purge` (`purgeRecordings`, ADMIN only, E18-B's `routers/admin.py`) both
call this class — neither re-implements the retention rule.

**What it does, in order**, for every `audio_segments` row not yet purged whose session's
retention reference (`completed_at`, or `created_at` for a session that never completed) is older
than the window:

1. delete the WAV file from `Settings.data_dir / "recordings"` (a missing file is not an error —
   `bytes_freed` is `0`, never a fabricated number, SPEC §27's "measured, never invented");
2. null `audio_segments.file_path` and set `.purged_at` (the row, its offsets, its transcript and
   every score that reproduces from the event log stay exactly as they were — SPEC §28);
3. write one `recording_purge_audit` row — never a `session_events` append (D9: "the log is closed
   for a completed session; the audit row is written instead").

**Dry run** (`request.dry_run`, default `True`, matching `PurgeRecordingsRequest`'s own default)
lists the candidates and reports the bytes an eventual purge would free, without touching a file, a
row or the audit table.

**Retention `<= 0` never purges** — `RECORDING_RETENTION_DAYS=0` per §9.2, generalised here to any
non-positive `older_than_days` override, since "0 or negative" both read as "no window at all"
rather than "everything is already past the window".

**A file shared by more than one segment** (the recorder packs one speaker's whole call into one
WAV, sliced by `byte_offset`/`byte_length`, `50-voice-pipeline.md` §9.1) is deleted once, by
whichever candidate is processed first; every later candidate that names the same path finds it
already gone and is recorded with `bytes_freed = 0` — still a purged, audited row, never a skipped
one, and never a *second* charge for bytes this purge already freed.

**HLD gap** (see this task's report): `recording_purge_audit.actor_type` is `ActorType`
(`TRAINEE|INSTRUCTOR|SIMULATION|MODEL|SYSTEM`, `app.domain.enums`) — there is no `ADMIN` member,
even though `purgeRecordings` is ADMIN-only. `INSTRUCTOR` is used for any authenticated caller
(`AuthenticatedUser.is_instructor_or_admin` already treats the two roles as one authorization
tier elsewhere, e.g. `app.application.reports.visibility`); the CLI, which has no authenticated
user, uses `SYSTEM`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.clock import Clock
from app.application.ports.recording_purge_repository import PurgeCandidateSegment
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.ids import SessionId

__all__ = ["PurgeRecordings", "PurgeRecordingsRequest", "PurgeRecordingsResult"]


def _reason_for(request: PurgeRecordingsRequest) -> str:
    """`recording_purge_audit.reason` / `PurgeRecordingsResult.reason` (§20.6's `CHECK`).

    `openapi.yaml`'s `PurgeRecordingsRequest.session_id` documents itself as `"Restrict the purge
    to one session (reason = MANUAL_REQUEST)"` — a caller who names a session is asking for that
    session's recordings specifically, not describing the routine sweep, even though the same
    retention-window filter still applies (nothing in the schema says `session_id` bypasses the
    window, and `ADMIN_DELETE` — §20.6's third `CHECK` member — is a future, no-retention-check
    deletion flow this use case does not implement). No `session_id` is the routine sweep:
    `RETENTION_WINDOW`.
    """
    return "MANUAL_REQUEST" if request.session_id is not None else "RETENTION_WINDOW"


@dataclass(frozen=True, slots=True)
class PurgeRecordingsRequest:
    """`openapi.yaml`'s `PurgeRecordingsRequest`, property names literal."""

    dry_run: bool = True
    older_than_days: int | None = None
    session_id: SessionId | None = None


@dataclass(frozen=True, slots=True)
class PurgeRecordingsResult:
    """`openapi.yaml`'s `PurgeRecordingsResult`, property names literal."""

    dry_run: bool
    retention_days: int
    session_count: int
    segment_count: int
    bytes_freed: int
    purged_at: datetime
    reason: str


class PurgeRecordings:
    """Retention purge (§9.2). `older_than_days` overrides `RECORDING_RETENTION_DAYS`."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        *,
        recordings_dir: Path,
        default_retention_days: int,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        #: `Settings.data_dir / "recordings"` — the same directory `ServeAudioSegment` resolves
        #: every served path inside of (SPEC §41: nothing outside it is ever touched).
        self._recordings_dir = recordings_dir
        self._default_retention_days = default_retention_days

    async def __call__(
        self, request: PurgeRecordingsRequest, *, actor: AuthenticatedUser | None = None
    ) -> PurgeRecordingsResult:
        retention_days = (
            request.older_than_days
            if request.older_than_days is not None
            else self._default_retention_days
        )
        now = self._clock.now()
        reason = _reason_for(request)
        if retention_days <= 0:
            return PurgeRecordingsResult(
                dry_run=request.dry_run,
                retention_days=retention_days,
                session_count=0,
                segment_count=0,
                bytes_freed=0,
                purged_at=now,
                reason=reason,
            )
        cutoff = now - timedelta(days=retention_days)

        async with self._unit_of_work() as uow:
            candidates = list(
                await uow.recording_purge.list_candidates(
                    cutoff=cutoff, session_id=request.session_id
                )
            )

            if request.dry_run:
                await uow.commit()  # a read-only transaction; nothing was written
                return PurgeRecordingsResult(
                    dry_run=True,
                    retention_days=retention_days,
                    session_count=_session_count(candidates),
                    segment_count=len(candidates),
                    bytes_freed=sum(self._file_size(candidate) for candidate in candidates),
                    purged_at=now,
                    reason=reason,
                )

            actor_type = "INSTRUCTOR" if actor is not None else "SYSTEM"
            actor_user_id = UUID(str(actor.user_id)) if actor is not None else None
            bytes_freed = 0
            for candidate in candidates:
                freed = self._delete_file(candidate)
                bytes_freed += freed
                await uow.recording_purge.mark_purged(candidate.audio_segment_id, purged_at=now)
                await uow.recording_purge.add_audit_row(
                    audio_segment_id=candidate.audio_segment_id,
                    session_id=candidate.session_id,
                    file_path_was=candidate.file_path,
                    bytes_freed=freed,
                    retention_days=retention_days,
                    reason=reason,
                    actor_type=actor_type,
                    actor_user_id=actor_user_id,
                    purged_at=now,
                )
            await uow.commit()

        return PurgeRecordingsResult(
            dry_run=False,
            retention_days=retention_days,
            session_count=_session_count(candidates),
            segment_count=len(candidates),
            bytes_freed=bytes_freed,
            purged_at=now,
            reason=reason,
        )

    # -- the filesystem half -------------------------------------------------------------------
    # SPEC §41: the only input to a path is the row's own *relative* `file_path`, joined onto
    # `recordings_dir` and refused unless the resolved path is still inside it — the same
    # containment check `ServeAudioSegment._resolved_path` uses for the same reason.

    def _resolved_path(self, candidate: PurgeCandidateSegment) -> Path | None:
        base = self._recordings_dir.resolve()
        candidate_path = (base.parent / candidate.file_path).resolve()
        if not candidate_path.is_relative_to(base):
            return None
        return candidate_path

    def _file_size(self, candidate: PurgeCandidateSegment) -> int:
        path = self._resolved_path(candidate)
        if path is None or not path.is_file():
            return 0
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _delete_file(self, candidate: PurgeCandidateSegment) -> int:
        """Delete the file and return the bytes freed; `0` (never an exception) if it is already
        gone — a file another candidate's delete already removed, or one purged out-of-band."""
        path = self._resolved_path(candidate)
        if path is None or not path.is_file():
            return 0
        try:
            size = path.stat().st_size
            path.unlink()
            return size
        except OSError:
            return 0


def _session_count(candidates: list[PurgeCandidateSegment]) -> int:
    return len({candidate.session_id for candidate in candidates})
