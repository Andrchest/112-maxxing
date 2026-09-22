"""`PurgeRecordings` (§9.2, D9, SPEC §41, R8) — real PostgreSQL, real WAV files on disk.

Runs against the `completed` fixture's real 112 -> DDS -> close flow (`tests.api.reports.conftest`,
re-exported by this package's `conftest.py`): a session that is genuinely `COMPLETED`, genuinely
scored, and carries the two real `audio_segments` rows (+ WAV files under `api_settings.data_dir`)
E12/E14 would have written. `simulation_sessions.completed_at` is backdated by raw SQL so the
session reads as "past the retention window" without a test sleeping 30 real days.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.recording import PurgeRecordings, PurgeRecordingsRequest
from app.application.scoring.rescore_session import RescoreSession
from app.config.settings import Settings
from app.domain.common.ids import SessionId, UserId
from app.infrastructure.clock import SystemClock

from tests.api.reports.conftest import OperatorFlow

pytestmark = pytest.mark.integration

_RETENTION_DAYS = 30


async def _backdate_completed_at(uow_factory: Any, session_id: UUID, *, days_ago: int) -> None:
    """`simulation_sessions.completed_at = now() - days_ago` — puts the session past the window."""
    async with uow_factory() as uow:
        await uow.session.execute(
            sa.text("UPDATE simulation_sessions SET completed_at = :completed_at WHERE id = :id"),
            {"completed_at": datetime.now(UTC) - timedelta(days=days_ago), "id": session_id},
        )
        await uow.commit()


async def _segment_rows(uow_factory: Any, session_id: UUID) -> list[dict[str, Any]]:
    async with uow_factory() as uow:
        rows = (
            (
                await uow.session.execute(
                    sa.text(
                        "SELECT id, file_path, purged_at FROM audio_segments"
                        " WHERE session_id = :sid ORDER BY start_ms"
                    ),
                    {"sid": session_id},
                )
            )
            .mappings()
            .all()
        )
        await uow.commit()
    return [dict(row) for row in rows]


async def _audit_rows(uow_factory: Any, session_id: UUID) -> list[dict[str, Any]]:
    async with uow_factory() as uow:
        rows = (
            (
                await uow.session.execute(
                    sa.text(
                        "SELECT audio_segment_id, bytes, reason, retention_days, file_path_was"
                        " FROM recording_purge_audit WHERE session_id = :sid"
                    ),
                    {"sid": session_id},
                )
            )
            .mappings()
            .all()
        )
        await uow.commit()
    return [dict(row) for row in rows]


async def _event_count(uow_factory: Any, session_id: UUID) -> int:
    async with uow_factory() as uow:
        count = (
            await uow.session.execute(
                sa.text("SELECT count(*) FROM session_events WHERE session_id = :sid"),
                {"sid": session_id},
            )
        ).scalar_one()
        await uow.commit()
    return int(count)


def _purge_recordings(
    uow_factory: Any, api_settings: Settings, *, default_retention_days: int = _RETENTION_DAYS
) -> PurgeRecordings:
    return PurgeRecordings(
        uow_factory,
        SystemClock(),
        recordings_dir=Path(api_settings.data_dir) / "recordings",
        default_retention_days=default_retention_days,
    )


async def test_dry_run_lists_without_touching_a_file_or_a_row(
    completed: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> None:
    session_id = UUID(str(completed.session_id))
    before = await _segment_rows(uow_factory, session_id)
    paths = [Path(api_settings.data_dir) / row["file_path"] for row in before]
    assert all(path.is_file() for path in paths)
    await _backdate_completed_at(uow_factory, session_id, days_ago=40)

    use_case = _purge_recordings(uow_factory, api_settings)
    result = await use_case(PurgeRecordingsRequest(dry_run=True, session_id=SessionId(session_id)))

    assert result.dry_run is True
    assert result.segment_count == len(before)
    assert result.bytes_freed > 0
    assert all(path.is_file() for path in paths), "dry-run must not delete a file"
    after = await _segment_rows(uow_factory, session_id)
    assert after == before, "dry-run must not touch a row"
    assert await _audit_rows(uow_factory, session_id) == []


async def test_a_real_purge_deletes_files_nulls_rows_and_writes_one_audit_row_each(
    completed: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> None:
    session_id = UUID(str(completed.session_id))
    before = await _segment_rows(uow_factory, session_id)
    paths = [Path(api_settings.data_dir) / row["file_path"] for row in before]
    await _backdate_completed_at(uow_factory, session_id, days_ago=40)

    # No `session_id` on the request: the routine sweep, `reason = RETENTION_WINDOW`
    # (`openapi.yaml`'s `PurgeRecordingsRequest.session_id` reserves `MANUAL_REQUEST` for a
    # request that names one session — covered separately below). `clean_database` truncates
    # before every test, so this session is the only one the sweep can find.
    use_case = _purge_recordings(uow_factory, api_settings)
    result = await use_case(PurgeRecordingsRequest(dry_run=False))

    assert result.dry_run is False
    assert result.segment_count == len(before)
    assert result.session_count == 1
    assert result.bytes_freed > 0
    assert all(not path.is_file() for path in paths), "the WAV files must be deleted"

    after = await _segment_rows(uow_factory, session_id)
    assert all(row["file_path"] is None for row in after), "file_path must be nulled"
    assert all(row["purged_at"] is not None for row in after), "purged_at must be set"
    assert [row["id"] for row in after] == [row["id"] for row in before], "the rows must survive"

    audit = await _audit_rows(uow_factory, session_id)
    assert len(audit) == len(before), "one recording_purge_audit row per purged segment"
    assert {row["audio_segment_id"] for row in audit} == {row["id"] for row in before}
    assert all(row["reason"] == "RETENTION_WINDOW" for row in audit)
    assert all(row["retention_days"] == _RETENTION_DAYS for row in audit)
    assert sum(row["bytes"] for row in audit) == result.bytes_freed


async def test_a_session_scoped_request_is_recorded_as_manual_request(
    completed: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> None:
    """`session_id` on the request names `MANUAL_REQUEST`, not the routine sweep's reason."""
    session_id = UUID(str(completed.session_id))
    before = await _segment_rows(uow_factory, session_id)
    await _backdate_completed_at(uow_factory, session_id, days_ago=40)

    use_case = _purge_recordings(uow_factory, api_settings)
    result = await use_case(PurgeRecordingsRequest(dry_run=False, session_id=SessionId(session_id)))

    assert result.reason == "MANUAL_REQUEST"
    assert result.segment_count == len(before)
    audit = await _audit_rows(uow_factory, session_id)
    assert all(row["reason"] == "MANUAL_REQUEST" for row in audit)


async def test_a_second_run_purges_nothing(
    completed: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> None:
    session_id = UUID(str(completed.session_id))
    await _backdate_completed_at(uow_factory, session_id, days_ago=40)
    use_case = _purge_recordings(uow_factory, api_settings)
    first = await use_case(PurgeRecordingsRequest(dry_run=False, session_id=SessionId(session_id)))
    assert first.segment_count > 0

    second = await use_case(PurgeRecordingsRequest(dry_run=False, session_id=SessionId(session_id)))

    assert second.segment_count == 0
    assert second.bytes_freed == 0
    audit = await _audit_rows(uow_factory, session_id)
    assert len(audit) == first.segment_count, "the second run must add no new audit rows"


async def test_retention_zero_never_purges(
    completed: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> None:
    session_id = UUID(str(completed.session_id))
    before = await _segment_rows(uow_factory, session_id)
    await _backdate_completed_at(uow_factory, session_id, days_ago=4000)  # far past any window

    use_case = _purge_recordings(uow_factory, api_settings, default_retention_days=0)
    result = await use_case(PurgeRecordingsRequest(dry_run=False, session_id=SessionId(session_id)))

    assert result.segment_count == 0
    assert result.bytes_freed == 0
    after = await _segment_rows(uow_factory, session_id)
    assert after == before


async def test_a_missing_file_on_disk_still_writes_an_audit_row_with_zero_bytes(
    completed: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> None:
    session_id = UUID(str(completed.session_id))
    before = await _segment_rows(uow_factory, session_id)
    # Delete one file out-of-band, as if the retention purge had already run once for it manually.
    missing = Path(api_settings.data_dir) / before[0]["file_path"]
    missing.unlink()
    await _backdate_completed_at(uow_factory, session_id, days_ago=40)

    use_case = _purge_recordings(uow_factory, api_settings)
    result = await use_case(PurgeRecordingsRequest(dry_run=False, session_id=SessionId(session_id)))

    assert result.segment_count == len(before), "a missing file is still a purged, audited segment"
    audit = {row["audio_segment_id"]: row for row in await _audit_rows(uow_factory, session_id)}
    assert audit[before[0]["id"]]["bytes"] == 0
    after = {row["id"]: row for row in await _segment_rows(uow_factory, session_id)}
    assert after[before[0]["id"]]["file_path"] is None
    assert after[before[0]["id"]]["purged_at"] is not None


async def test_no_session_events_row_is_appended(
    completed: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> None:
    session_id = UUID(str(completed.session_id))
    await _backdate_completed_at(uow_factory, session_id, days_ago=40)
    before_count = await _event_count(uow_factory, session_id)

    use_case = _purge_recordings(uow_factory, api_settings)
    result = await use_case(PurgeRecordingsRequest(dry_run=False, session_id=SessionId(session_id)))

    assert result.segment_count > 0
    after_count = await _event_count(uow_factory, session_id)
    assert after_count == before_count, "the purge must not append to the closed event log"


async def test_rescore_checksum_is_identical_before_and_after_purge(
    completed: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> None:
    """SPEC §28: the same event log must reproduce the same score, purged or not."""
    session_id = SessionId(UUID(str(completed.session_id)))
    await _backdate_completed_at(uow_factory, session_id, days_ago=40)
    instructor = AuthenticatedUser(
        user_id=UserId(UUID(int=1)),
        username="instructor1",
        display_name_ru="Инструктор",
        user_role=UserRole.INSTRUCTOR,
    )
    rescore = RescoreSession(uow_factory)

    before = await rescore(session_id, instructor, persist=False)
    assert before.stored_checksum is not None, "the close flow must have already scored it"

    use_case = _purge_recordings(uow_factory, api_settings)
    purged = await use_case(PurgeRecordingsRequest(dry_run=False, session_id=session_id))
    assert purged.segment_count > 0

    after = await rescore(session_id, instructor, persist=False)

    assert after.stored_checksum == before.stored_checksum
    assert after.recomputed_checksum == before.recomputed_checksum
    assert after.identical_to_stored == before.identical_to_stored is True
