"""ADMIN's read of a lesson report is audited by name and target (I5 E37, Q-E14-1 variant б).

`GetLessonReport` already treats `ADMIN` like `INSTRUCTOR` (`user.is_instructor_or_admin`); this
proves the audit half — E25's `AuditMiddleware` names the caller and, from the path's own
`lesson_id`, the target, for every request (`app.api.main._record`). The lesson only needs to be
*terminal* for `getLessonReport` to answer (`LessonReportNotReadyError` otherwise, D34) — an
aborted lesson with one unscored card is the cheapest terminal lesson to reach.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.common.ids import ScenarioVersionId, UserId
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth
from tests.api.lessons.conftest import Lessons, plan_entry

pytestmark = pytest.mark.integration


async def _rows(engine: AsyncEngine, operation_id: str, lesson_id: Any) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT * FROM audit_log WHERE operation_id = :op"
                " AND target_ids ->> 'lesson_id' = :lesson_id ORDER BY ts, id"
            ),
            {"op": operation_id, "lesson_id": str(lesson_id)},
        )
        return [dict(row._mapping) for row in result]


async def test_an_admin_s_lesson_report_read_is_audited_by_name_and_target(
    lessons: Lessons,
    demo_version_id: ScenarioVersionId,
    migrated_engine: AsyncEngine,
    users: dict[str, UserId],
) -> None:
    detail = await lessons.created([plan_entry(1, demo_version_id)])
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    aborted = await lessons.client.post(
        f"/api/v1/lessons/{lesson_id}/abort", headers=lessons.instructor, json={"reason": "тест"}
    )
    assert aborted.status_code == 200, aborted.text

    response = await lessons.client.get(
        f"/api/v1/lessons/{lesson_id}/report", headers=auth(lessons.tokens["admin1"])
    )
    assert response.status_code == 200, response.text

    (row,) = await _rows(migrated_engine, "getLessonReport", lesson_id)
    assert row["user_id"] == users["admin1"]
    assert row["role"] == "ADMIN"
    assert (row["action"], row["outcome"], row["status"]) == ("HTTP_REQUEST", "OK", 200)
    assert row["target_ids"] == {"lesson_id": str(lesson_id)}
