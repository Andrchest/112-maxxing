"""The §20.9 immutability triggers and the §20.2 scenario-version lock trigger bite (epic E4).

Each guarded table gets three assertions: the legal INSERT is accepted, UPDATE is rejected and
DELETE is rejected — asserted on the database error the trigger raises, not on Python-side logic
(SPEC §8, §9, §10, §42 test 6, D3, D4, D5).
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

APPEND_ONLY_TABLES = ("session_events", "handoff_snapshots", "incident_card_revisions")


async def _row_count(session: AsyncSession, table: str, row_id: UUID) -> int:
    result = await session.execute(
        text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": row_id}
    )
    return int(result.scalar_one())


@pytest.mark.parametrize(
    ("table", "seed_key"),
    [
        ("session_events", "session_event"),
        ("handoff_snapshots", "snapshot"),
        ("incident_card_revisions", "card_revision"),
    ],
)
async def test_legal_insert_is_accepted(
    db_session: AsyncSession, seed_ids: dict[str, UUID], table: str, seed_key: str
) -> None:
    """`seed_ids` inserted one row per guarded table; the trigger must not block INSERT."""
    assert await _row_count(db_session, table, seed_ids[seed_key]) == 1


@pytest.mark.parametrize(
    ("table", "seed_key", "assignment"),
    [
        ("session_events", "session_event", "monotonic_offset_ms = 999"),
        ("handoff_snapshots", "snapshot", "content_sha256 = 'tampered'"),
        ("incident_card_revisions", "card_revision", "field_path = 'tampered'"),
    ],
)
async def test_update_is_rejected(
    db_session: AsyncSession,
    seed_ids: dict[str, UUID],
    table: str,
    seed_key: str,
    assignment: str,
) -> None:
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text(f"UPDATE {table} SET {assignment} WHERE id = :id"), {"id": seed_ids[seed_key]}
        )
    assert "append-only" in str(excinfo.value)
    assert "UPDATE" in str(excinfo.value)


@pytest.mark.parametrize(
    ("table", "seed_key"),
    [
        ("session_events", "session_event"),
        ("handoff_snapshots", "snapshot"),
        ("incident_card_revisions", "card_revision"),
    ],
)
async def test_delete_is_rejected(
    db_session: AsyncSession, seed_ids: dict[str, UUID], table: str, seed_key: str
) -> None:
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text(f"DELETE FROM {table} WHERE id = :id"), {"id": seed_ids[seed_key]}
        )
    assert "append-only" in str(excinfo.value)
    assert "DELETE" in str(excinfo.value)


async def test_unlocked_scenario_version_content_may_be_updated(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    """While `locked_at` is null the scenario version is ordinary mutable reference data (D4)."""
    await db_session.execute(
        text(
            "UPDATE scenario_versions SET content = CAST(:content AS jsonb),"
            " content_sha256 = 'new-sha' WHERE id = :id"
        ),
        {"content": json.dumps({"version": 2}), "id": seed_ids["scenario_version"]},
    )
    result = await db_session.execute(
        text("SELECT content_sha256 FROM scenario_versions WHERE id = :id"),
        {"id": seed_ids["scenario_version"]},
    )
    assert result.scalar_one() == "new-sha"


async def test_locked_scenario_version_content_update_is_rejected(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    """Once `locked_at` is set, `content` / `content_sha256` freeze (D4, §42 test 6)."""
    await db_session.execute(
        text("UPDATE scenario_versions SET locked_at = now() WHERE id = :id"),
        {"id": seed_ids["scenario_version"]},
    )
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text("UPDATE scenario_versions SET content = CAST(:content AS jsonb) WHERE id = :id"),
            {"content": json.dumps({"version": 3}), "id": seed_ids["scenario_version"]},
        )
    assert "is locked since" in str(excinfo.value)


async def test_locked_scenario_version_metadata_update_stays_legal(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    """The lock trigger is conditional: ordinary metadata updates stay legal (§20.9)."""
    await db_session.execute(
        text("UPDATE scenario_versions SET locked_at = now() WHERE id = :id"),
        {"id": seed_ids["scenario_version"]},
    )
    await db_session.execute(
        text("UPDATE scenario_versions SET description = 'обновлено' WHERE id = :id"),
        {"id": seed_ids["scenario_version"]},
    )
    result = await db_session.execute(
        text("SELECT description FROM scenario_versions WHERE id = :id"),
        {"id": seed_ids["scenario_version"]},
    )
    assert result.scalar_one() == "обновлено"
