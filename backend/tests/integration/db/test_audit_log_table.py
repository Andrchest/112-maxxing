"""`audit_log` (migration `0016_audit_log`, I4 E25; HLD 20 §20.6, §20.9, D31).

The legal INSERT is accepted; UPDATE and DELETE are rejected by the database's own
`audit_log_append_only` trigger — asserted on the error it raises, not on Python-side logic, the
same way `test_immutability_triggers.py` asserts the §20.9 tables. The three CHECK lists bite.
Everything runs inside `db_session`'s rolled-back transaction.
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_INSERT = (
    "INSERT INTO audit_log (user_id, role, action, operation_id, method, path_template,"
    " target_ids, status, client_ip, outcome)"
    " VALUES (:user_id, :role, :action, 'getSession', 'GET', '/api/v1/sessions/{session_id}',"
    " CAST(:target_ids AS jsonb), 200, '127.0.0.1', :outcome) RETURNING id"
)


async def _insert(
    session: AsyncSession,
    user_id: UUID | None,
    *,
    role: str | None = "TRAINEE",
    action: str = "HTTP_REQUEST",
    outcome: str = "OK",
) -> UUID:
    result = await session.execute(
        text(_INSERT),
        {
            "user_id": user_id,
            "role": role,
            "action": action,
            "outcome": outcome,
            "target_ids": json.dumps({"session_id": "x"}),
        },
    )
    return UUID(str(result.scalar_one()))


async def test_a_legal_insert_is_accepted_with_its_defaults(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    row_id = await _insert(db_session, seed_ids["user"])
    row = (
        await db_session.execute(
            text("SELECT ts, target_ids FROM audit_log WHERE id = :id"), {"id": row_id}
        )
    ).one()
    assert row.ts is not None
    assert row.target_ids == {"session_id": "x"}


async def test_an_unauthenticated_entry_has_no_user_and_no_role(db_session: AsyncSession) -> None:
    row_id = await _insert(db_session, None, role=None, action="ACCESS_DENIED", outcome="DENIED")
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM audit_log WHERE id = :id AND user_id IS NULL"),
            {"id": row_id},
        )
    ).scalar_one()
    assert count == 1


async def test_update_is_rejected(db_session: AsyncSession, seed_ids: dict[str, UUID]) -> None:
    row_id = await _insert(db_session, seed_ids["user"])
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text("UPDATE audit_log SET status = 500 WHERE id = :id"), {"id": row_id}
        )
    assert "append-only" in str(excinfo.value)
    assert "UPDATE" in str(excinfo.value)


async def test_delete_is_rejected(db_session: AsyncSession, seed_ids: dict[str, UUID]) -> None:
    row_id = await _insert(db_session, seed_ids["user"])
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": row_id})
    assert "append-only" in str(excinfo.value)
    assert "DELETE" in str(excinfo.value)


@pytest.mark.parametrize(
    ("column", "value"),
    [("role", "SYSTEM"), ("action", "LOGIN_ATTEMPTED"), ("outcome", "MAYBE")],
)
async def test_the_check_lists_bite(
    db_session: AsyncSession, seed_ids: dict[str, UUID], column: str, value: str
) -> None:
    arguments = {"role": "TRAINEE", "action": "HTTP_REQUEST", "outcome": "OK", column: value}
    with pytest.raises(IntegrityError):
        await _insert(db_session, seed_ids["user"], **arguments)
