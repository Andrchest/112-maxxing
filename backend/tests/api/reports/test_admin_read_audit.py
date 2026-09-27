"""ADMIN's read access to session reports, transcripts and recordings is audited by name and by
target (I5 E37, Q-E14-1 variant б: "видит, но каждый просмотр пишется в журнал аудита").

`report_visibility` (`app.application.reports.visibility`) already treats `ADMIN` exactly like
`INSTRUCTOR` (`user.is_instructor_or_admin`), so this suite is not proving a new access grant —
it is proving the audit half of the owner's answer: E25's `AuditMiddleware` already writes one row
per HTTP request naming the caller (`user_id`, `role`) and the path's own parameters as
`target_ids` (`app.api.main._record`, `_target_ids`), so every operation below gets its target for
free from its own path — `session_id` and, for the two audio downloads, `audio_segment_id` too.
One test per read operation, as the epic's `CHECK` asks: `getSessionReport` (covers the
transcript, SPEC §29 items 5-7), `getAudioSegment` (WAV) and `getAudioSegmentMp3`.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.common.ids import UserId
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth
from tests.api.reports.conftest import OperatorFlow, RecordedSegment

pytestmark = pytest.mark.integration


async def _rows(engine: AsyncEngine, operation_id: str, session_id: Any) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT * FROM audit_log WHERE operation_id = :op"
                " AND target_ids ->> 'session_id' = :session_id ORDER BY ts, id"
            ),
            {"op": operation_id, "session_id": str(session_id)},
        )
        return [dict(row._mapping) for row in result]


async def test_an_admin_s_session_report_read_is_audited_by_name_and_target(
    completed: OperatorFlow,
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    response = await completed.client.get(
        f"/api/v1/reports/{completed.session_id}", headers=auth(tokens["admin1"])
    )
    assert response.status_code == 200, response.text

    (row,) = await _rows(migrated_engine, "getSessionReport", completed.session_id)
    assert row["user_id"] == users["admin1"]
    assert row["role"] == "ADMIN"
    assert (row["action"], row["outcome"], row["status"]) == ("HTTP_REQUEST", "OK", 200)
    assert row["target_ids"] == {"session_id": str(completed.session_id)}


async def test_an_admin_s_wav_download_is_audited_by_name_and_target(
    completed: OperatorFlow,
    recorded_segment: RecordedSegment,
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    response = await completed.client.get(
        f"/api/v1/sessions/{completed.session_id}/audio/{recorded_segment.audio_segment_id}",
        headers=auth(tokens["admin1"]),
    )
    assert response.status_code == 200, response.text

    (row,) = await _rows(migrated_engine, "getAudioSegment", completed.session_id)
    assert row["user_id"] == users["admin1"]
    assert row["role"] == "ADMIN"
    assert (row["action"], row["outcome"], row["status"]) == ("HTTP_REQUEST", "OK", 200)
    assert row["target_ids"] == {
        "session_id": str(completed.session_id),
        "audio_segment_id": str(recorded_segment.audio_segment_id),
    }


async def test_an_admin_s_mp3_download_is_audited_by_name_and_target(
    completed: OperatorFlow,
    recorded_segment: RecordedSegment,
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    response = await completed.client.get(
        f"/api/v1/sessions/{completed.session_id}/audio/{recorded_segment.audio_segment_id}/mp3",
        headers=auth(tokens["admin1"]),
    )
    assert response.status_code == 200, response.text

    (row,) = await _rows(migrated_engine, "getAudioSegmentMp3", completed.session_id)
    assert row["user_id"] == users["admin1"]
    assert row["role"] == "ADMIN"
    assert (row["action"], row["outcome"], row["status"]) == ("HTTP_REQUEST", "OK", 200)
    assert row["target_ids"] == {
        "session_id": str(completed.session_id),
        "audio_segment_id": str(recorded_segment.audio_segment_id),
    }
