"""«было → стало» on the report rows (I7 E43, Q-E15-3; ТЗ ¶246 «без фиксации в журнале аудита»).

* `rescoreSession persist=true` reports the score before and after — the total and every rule
  whose points moved — under the real actor; a dry run reports nothing;
* `releaseReportToTrainee` reports the release (once — a repeat changes nothing);
* `createSessionComment` reports the text.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from app.domain.common.ids import UserId
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api._audit_changes import audit_ids, changes_by_field, new_row
from tests.api.conftest import auth
from tests.api.reports.conftest import OperatorFlow, release

pytestmark = pytest.mark.integration


async def _rescore(flow: OperatorFlow, *, persist: bool) -> dict[str, Any]:
    response = await flow.client.post(
        f"/api/v1/reports/{flow.session_id}/rescore",
        headers=auth(flow.instructor_token),
        json={"persist": persist},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_a_persisted_rescore_records_the_score_before_and_after(
    completed: OperatorFlow, migrated_engine: AsyncEngine, users: dict[str, UserId]
) -> None:
    original = await _rescore(completed, persist=False)
    rule = original["recomputed"]["results"][0]
    total = original["recomputed"]["total_points"]
    async with migrated_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "UPDATE score_results SET points_awarded = points_awarded + 999"
                " WHERE session_id = :session_id AND rule_id = :rule_id"
            ),
            {"session_id": completed.session_id, "rule_id": rule["rule_id"]},
        )

    before = await audit_ids(migrated_engine)
    await _rescore(completed, persist=False)
    dry_run = await new_row(migrated_engine, before, "rescoreSession")
    assert dry_run["changes"] is None, "a dry run changes nothing"

    before = await audit_ids(migrated_engine)
    persisted = await _rescore(completed, persist=True)
    assert persisted["persisted"] is True
    row = await new_row(migrated_engine, before, "rescoreSession")
    assert row["user_id"] == users["instructor1"]
    assert changes_by_field(row) == {
        "score.total_points": (total + 999, total),
        f"score.rule_points[{rule['rule_id']}]": (
            rule["points_awarded"] + 999,
            rule["points_awarded"],
        ),
    }


async def test_release_records_the_release_once(
    completed: OperatorFlow, migrated_engine: AsyncEngine
) -> None:
    before = await audit_ids(migrated_engine)
    first = await release(completed)
    assert first.status_code == 200, first.text
    row = await new_row(migrated_engine, before, "releaseReportToTrainee")
    assert changes_by_field(row) == {"report.released": (False, True)}

    before = await audit_ids(migrated_engine)
    again = await release(completed)
    assert again.status_code == 200
    assert (await new_row(migrated_engine, before, "releaseReportToTrainee"))["changes"] is None


async def test_a_session_comment_records_its_text(
    completed: OperatorFlow, migrated_engine: AsyncEngine
) -> None:
    before = await audit_ids(migrated_engine)
    response = await completed.client.post(
        f"/api/v1/reports/{completed.session_id}/comments",
        headers=auth(completed.instructor_token),
        json={"text": "Разбор: адрес уточнён поздно"},
    )
    assert response.status_code == 201, response.text
    assert changes_by_field(await new_row(migrated_engine, before, "createSessionComment")) == {
        "comment.text": (None, "Разбор: адрес уточнён поздно")
    }
