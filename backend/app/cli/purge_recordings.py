"""`python -m app.cli purge_recordings [--dry-run] [--older-than-days N] [--session-id UUID]`
(`docs/hld/50-voice-pipeline.md` §9.2, D9, SPEC §41, R8).

The CLI half of `PurgeRecordings` — the other half is `purgeRecordings`
(`POST /api/v1/admin/recordings/purge`, ADMIN only, E18-B's `routers/admin.py`); both call the
same use case (this task's ruling R8). `--dry-run` is the CLI's own default (matches
`PurgeRecordingsRequest.dry_run`'s own default of `True` — a maintenance command should never
delete anything on the strength of a bare invocation) and needs no flag; pass `--no-dry-run` to
actually purge. `--older-than-days` overrides `SIM_RECORDING_RETENTION_DAYS`; omitted, the run uses
the configured retention (`0` = never purge, both here and in the API).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

from app.application.recording import PurgeRecordings, PurgeRecordingsRequest, PurgeRecordingsResult
from app.config.settings import Settings
from app.db.session import create_engine, create_session_factory
from app.domain.common.ids import SessionId
from app.infrastructure.clock import SystemClock
from app.infrastructure.persistence.unit_of_work import unit_of_work_factory

__all__ = ["main", "purge_recordings"]


class _NullPublisher:
    """An `EventPublisher` that publishes nothing: the purge appends no session event (D9)."""

    async def publish(self, session_id: object, envelopes: object) -> None:
        """A no-op — there is nothing to fan out."""
        return None


async def purge_recordings(
    settings: Settings, request: PurgeRecordingsRequest
) -> PurgeRecordingsResult:
    """Run one purge (or dry run) against `settings.database_url` and `settings.data_dir`."""
    engine = create_engine(settings)
    try:
        unit_of_work = unit_of_work_factory(
            create_session_factory(engine), SystemClock(), _NullPublisher()
        )
        use_case = PurgeRecordings(
            unit_of_work,
            SystemClock(),
            recordings_dir=Path(settings.data_dir) / "recordings",
            default_retention_days=settings.recording_retention_days,
        )
        return await use_case(request)
    finally:
        await engine.dispose()


def _render(result: PurgeRecordingsResult) -> str:
    verb = "would purge" if result.dry_run else "purged"
    return (
        f"{verb} {result.segment_count} segment(s) across {result.session_count} session(s), "
        f"{result.bytes_freed} byte(s) freed (retention_days={result.retention_days}, "
        f"reason={result.reason}, purged_at={result.purged_at.isoformat()})"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli purge_recordings", description="Retention purge (§9.2, R8)"
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="list what would be purged without touching anything (the default)",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="actually delete the files and null the rows",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        help="override SIM_RECORDING_RETENTION_DAYS for this run (0 = never purge)",
    )
    parser.add_argument(
        "--session-id", type=str, default=None, help="limit the purge to one session"
    )
    args = parser.parse_args(argv)

    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as exc:
        print(f"purge_recordings could not start: invalid settings: {exc}", file=sys.stderr)
        return 2

    session_id = SessionId(UUID(args.session_id)) if args.session_id else None
    request = PurgeRecordingsRequest(
        dry_run=args.dry_run, older_than_days=args.older_than_days, session_id=session_id
    )

    try:
        result = asyncio.run(purge_recordings(settings, request))
    except Exception as exc:
        print(f"purge_recordings failed: {exc}", file=sys.stderr)
        return 2

    print(_render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
