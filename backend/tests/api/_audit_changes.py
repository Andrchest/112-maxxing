"""Helpers for the I7 E43 «было → стало» tests: find the one `audit_log` row a request wrote.

The table is shared by every test of the worker and append-only by design, so a row is told apart
the way `tests/api/test_audit_log.py` does it — by subtracting the ids present before the request.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def audit_ids(engine: AsyncEngine) -> set[UUID]:
    """Every `audit_log` id present now."""
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT id FROM audit_log"))
        return {row[0] for row in result}


async def new_row(engine: AsyncEngine, before: set[UUID], operation_id: str) -> dict[str, Any]:
    """The one row with `operation_id` written since `before` was read."""
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT * FROM audit_log WHERE operation_id = :operation_id ORDER BY ts, id"),
            {"operation_id": operation_id},
        )
        rows = [dict(row._mapping) for row in result if row.id not in before]
    assert len(rows) == 1, rows
    return rows[0]


def changes_by_field(row: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """`{field: (before, after)}` of a row's `changes` (empty when the column is NULL)."""
    changes = row["changes"] or []
    fields = [change["field"] for change in changes]
    assert len(fields) == len(set(fields)), f"a field is reported twice: {fields}"
    return {change["field"]: (change["before"], change["after"]) for change in changes}
