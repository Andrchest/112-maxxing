"""`rescoreSession persist=true` is audited under its real INSTRUCTOR/ADMIN actor (I4 E25,
`71-i4-wave4.md` §71.2, ТЗ ¶246 «без фиксации в журнале аудита», analysis F-17).

The persisted score's own session events keep the `SYSTEM` actor scoring always had (D5, D11 — the
scoring record is unchanged); the change of grades is attributed to the person in `audit_log`.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.common.ids import UserId
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth
from tests.api.reports.conftest import OperatorFlow

pytestmark = pytest.mark.integration


async def _rescore_rows(engine: AsyncEngine, session_id: Any) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT * FROM audit_log WHERE operation_id = 'rescoreSession'"
                " AND target_ids ->> 'session_id' = :session_id ORDER BY ts, id"
            ),
            {"session_id": str(session_id)},
        )
        return [dict(row._mapping) for row in result]


@pytest.mark.parametrize("account", ["instructor1", "admin1"])
async def test_a_persisted_rescore_is_audited_under_the_real_actor(
    completed: OperatorFlow,
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
    account: str,
) -> None:
    response = await completed.client.post(
        f"/api/v1/reports/{completed.session_id}/rescore",
        headers=auth(tokens[account]),
        json={"persist": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["persisted"] is True

    (row,) = await _rescore_rows(migrated_engine, completed.session_id)
    assert row["user_id"] == users[account]
    assert row["role"] == ("INSTRUCTOR" if account == "instructor1" else "ADMIN")
    assert (row["action"], row["outcome"], row["status"]) == ("HTTP_REQUEST", "OK", 200)
    assert row["method"] == "POST"
    assert row["path_template"] == "/api/v1/reports/{session_id}/rescore"
    assert row["target_ids"] == {"session_id": str(completed.session_id)}


async def test_a_trainee_s_rescore_attempt_is_an_access_denied(
    completed: OperatorFlow, migrated_engine: AsyncEngine, users: dict[str, UserId]
) -> None:
    response = await completed.client.post(
        f"/api/v1/reports/{completed.session_id}/rescore",
        headers=auth(completed.operator_token),
        json={"persist": True},
    )
    assert response.status_code == 403
    (row,) = await _rescore_rows(migrated_engine, completed.session_id)
    assert (row["action"], row["outcome"], row["status"]) == ("ACCESS_DENIED", "DENIED", 403)
    assert row["user_id"] == completed.operator_user_id
