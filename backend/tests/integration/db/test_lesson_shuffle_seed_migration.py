"""Migration `0020_lesson_shuffle_seed` (I7 E53, G12a; HLD 71 §71.19.53, HLD 20 §20.12.53).

A lesson written at `0019` reads back with `shuffle_seed IS NULL` (the instructor's own order); a
new lesson takes a seed up to 2^53 - 1; downgrade drops the column (the lessons survive) and
upgrade restores it.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from tests.integration.db import alembic_support as support
from tests.integration.db.test_trainee_groups_migration import _base_url, _dsn

pytestmark = pytest.mark.integration

PRE_0020 = "0019_audit_changes"
AT_0020 = "0020_lesson_shuffle_seed"
MAX_SEED = 2**53 - 1

_USER = (
    "INSERT INTO users (username, password_hash, display_name_ru)"
    " VALUES ($1, 'x', 'Инструктор') RETURNING id"
)
_LESSON = (
    "INSERT INTO lessons (id, title_ru, created_by_user_id, session_mode, participants,"
    " scenario_plan) VALUES (gen_random_uuid(), 'Занятие', $1, 'SINGLE_ROLE', '[]'::jsonb,"
    " '[]'::jsonb) RETURNING id"
)


async def _fetchval(url: str, query: str, *args: Any) -> Any:
    connection = await asyncpg.connect(_dsn(url))
    try:
        return await connection.fetchval(query, *args)
    finally:
        await connection.close()


def _has_column(url: str) -> bool:
    return bool(
        asyncio.run(
            _fetchval(
                url,
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'lessons' AND column_name = 'shuffle_seed'",
            )
        )
    )


def test_the_column_is_additive_and_the_revision_round_trips() -> None:
    base_url = _base_url()
    name = support.random_database_name("sim_0020_")
    url = support.replace_database(base_url, name)
    support.create_database(base_url, name)
    try:
        support.upgrade(url, PRE_0020)
        user: UUID = asyncio.run(_fetchval(url, _USER, "instructor-0020"))
        old: UUID = asyncio.run(_fetchval(url, _LESSON, user))
        assert not _has_column(url)

        support.upgrade(url, AT_0020)
        assert (
            asyncio.run(_fetchval(url, "SELECT shuffle_seed FROM lessons WHERE id = $1", old))
            is None
        )
        new: UUID = asyncio.run(_fetchval(url, _LESSON, user))
        asyncio.run(
            _fetchval(url, "UPDATE lessons SET shuffle_seed = $2 WHERE id = $1", new, MAX_SEED)
        )
        assert (
            asyncio.run(_fetchval(url, "SELECT shuffle_seed FROM lessons WHERE id = $1", new))
            == MAX_SEED
        )

        support.downgrade(url, "-1")
        assert not _has_column(url)
        assert asyncio.run(_fetchval(url, "SELECT count(*) FROM lessons")) == 2

        support.upgrade(url, AT_0020)
        assert _has_column(url)
    finally:
        support.drop_database(base_url, name)
