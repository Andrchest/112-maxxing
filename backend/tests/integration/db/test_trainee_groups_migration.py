"""Migration `0013_trainee_groups` (I3 E9a; HLD `70-i3-alignment.md` §70.3.7, HLD 20 §20.2).

A lesson written at revision `0012` reads back after `upgrade 0013` with no group, no proposals
and its plan — every weight — byte-for-byte unchanged, so its report is the same sum as before;
`downgrade -1` removes the two tables and the two columns, and `upgrade` restores them.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from app.infrastructure.persistence.lesson_repository import lesson_from_row

from tests.integration.db import alembic_support as support

pytestmark = pytest.mark.integration

PRE_0013 = "0012_dds_response_status"
AT_0013 = "0013_trainee_groups"

PLAN: list[dict[str, Any]] = [
    {
        "position": position,
        "scenario_version_id": "3f6c1a20-0e1a-4b1e-9d2a-0a7c5b2f1d11",
        "arrival": {"kind": "AT_OFFSET", "offset_ms": 0, "delay_ms": 0},
        "variants": None,
        "participants": None,
        "weight": weight,
    }
    for position, weight in ((1, 1.0), (2, 2.5))
]


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _seed_lesson(url: str) -> UUID:
    connection = await asyncpg.connect(_dsn(url))
    try:
        user = await connection.fetchval(
            "INSERT INTO users (username, password_hash, display_name_ru)"
            " VALUES ('instructor-0013', 'x', 'Инструктор') RETURNING id"
        )
        lesson: UUID = await connection.fetchval(
            "INSERT INTO lessons (id, title_ru, created_by_user_id, session_mode, participants,"
            " scenario_plan) VALUES (gen_random_uuid(), 'Занятие', $1, 'SINGLE_ROLE',"
            " $2::jsonb, $3::jsonb) RETURNING id",
            user,
            json.dumps([{"user_id": str(user), "assigned_role_type": "DDS"}]),
            json.dumps(PLAN),
        )
        return lesson
    finally:
        await connection.close()


async def _lesson_row(url: str, lesson_id: UUID) -> dict[str, Any]:
    connection = await asyncpg.connect(_dsn(url))
    try:
        await connection.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )
        row = await connection.fetchrow("SELECT * FROM lessons WHERE id = $1", lesson_id)
    finally:
        await connection.close()
    assert row is not None
    return dict(row)


def _base_url() -> str:
    return os.environ.get(
        "SIM_DATABASE_URL", "postgresql+asyncpg://sim:sim@localhost:55432/sim_test"
    )


def test_an_existing_lesson_keeps_its_plan_and_weights_and_the_revision_round_trips() -> None:
    base_url = _base_url()
    name = support.random_database_name("sim_0013_")
    url = support.replace_database(base_url, name)
    support.create_database(base_url, name)
    try:
        support.upgrade(url, PRE_0013)
        lesson_id = asyncio.run(_seed_lesson(url))

        support.upgrade(url, AT_0013)
        row = asyncio.run(_lesson_row(url, lesson_id))
        assert row["group_id"] is None and row["weight_proposals"] is None
        assert row["scenario_plan"] == PLAN
        lesson = lesson_from_row(row)
        assert [entry.weight for entry in lesson.scenario_plan] == [1.0, 2.5]
        assert lesson.group_id is None and lesson.weight_proposals is None
        assert {"trainee_groups", "trainee_group_members"} <= support.table_names(url)

        support.downgrade(url, "-1")
        assert not {"trainee_groups", "trainee_group_members"} & support.table_names(url)
        assert "group_id" not in asyncio.run(_lesson_row(url, lesson_id))

        support.upgrade(url, AT_0013)
        assert asyncio.run(_lesson_row(url, lesson_id))["scenario_plan"] == PLAN
    finally:
        support.drop_database(base_url, name)
