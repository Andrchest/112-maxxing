"""Migration `0019_audit_changes` (I7 E43; HLD `71-i4-wave4.md` §71.19.43, HLD 20 `audit_log`).

* upgrade: a row written at `0018` reads back with `changes IS NULL`; a new row takes a JSON list;
  downgrade drops the column (the old row survives), upgrade restores it;
* the table is still append-only: an UPDATE that would add `changes` to an existing row is refused
  by `audit_log_append_only`, exactly as every other UPDATE.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.db import alembic_support as support
from tests.integration.db.test_trainee_groups_migration import _base_url, _dsn

pytestmark = pytest.mark.integration

PRE_0019 = "0018_training_materials"
AT_0019 = "0019_audit_changes"

_INSERT = (
    "INSERT INTO audit_log (action, method, path_template, status, outcome)"
    " VALUES ('HTTP_REQUEST', 'POST', '/api/v1/admin/users', 201, 'OK') RETURNING id"
)


async def _fetch(url: str, query: str, *args: Any) -> Any:
    connection = await asyncpg.connect(_dsn(url))
    try:
        await connection.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )
        return await connection.fetchrow(query, *args)
    finally:
        await connection.close()


def _columns(url: str) -> set[str]:
    row = asyncio.run(
        _fetch(
            url,
            "SELECT array_agg(column_name::text) AS names FROM information_schema.columns"
            " WHERE table_name = 'audit_log'",
        )
    )
    return set(row["names"])


def test_the_column_is_additive_and_the_revision_round_trips() -> None:
    base_url = _base_url()
    name = support.random_database_name("sim_0019_")
    url = support.replace_database(base_url, name)
    support.create_database(base_url, name)
    try:
        support.upgrade(url, PRE_0019)
        old_id: UUID = asyncio.run(_fetch(url, _INSERT))["id"]
        assert "changes" not in _columns(url)

        support.upgrade(url, AT_0019)
        old = asyncio.run(_fetch(url, "SELECT changes FROM audit_log WHERE id = $1", old_id))
        assert old["changes"] is None
        changes = [{"field": "user.user_role", "before": "TRAINEE", "after": "INSTRUCTOR"}]
        new = asyncio.run(
            _fetch(
                url,
                "INSERT INTO audit_log (action, method, path_template, status, outcome, changes)"
                " VALUES ('HTTP_REQUEST', 'PATCH', '/api/v1/admin/users/{user_id}', 200, 'OK', $1)"
                " RETURNING changes",
                changes,
            )
        )
        assert new["changes"] == changes

        support.downgrade(url, "-1")
        assert "changes" not in _columns(url)
        assert asyncio.run(_fetch(url, "SELECT id FROM audit_log WHERE id = $1", old_id))

        support.upgrade(url, AT_0019)
        assert "changes" in _columns(url)
    finally:
        support.drop_database(base_url, name)


async def test_adding_changes_to_an_existing_row_is_rejected(db_session: AsyncSession) -> None:
    row_id = (await db_session.execute(text(_INSERT))).scalar_one()
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text('UPDATE audit_log SET changes = \'[{"field": "x"}]\'::jsonb WHERE id = :id'),
            {"id": row_id},
        )
    assert "append-only" in str(excinfo.value)
