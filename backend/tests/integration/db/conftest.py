"""Fixtures shared by the database integration tests.

`seed_ids` inserts the minimum legal row chain the trigger and constraint tests need:
user -> scenario -> scenario_version -> session -> incident -> card -> revision -> snapshot,
plus one `session_events` row. It runs inside `db_session`'s outer transaction, so nothing it
writes outlives the test.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _scalar(session: AsyncSession, statement: str, **params: Any) -> UUID:
    result = await session.execute(text(statement), params)
    return UUID(str(result.scalar_one()))


@pytest.fixture
async def seed_ids(db_session: AsyncSession) -> dict[str, UUID]:
    """Insert one legal row per table the immutability triggers guard; return the ids."""
    ids: dict[str, UUID] = {}

    ids["user"] = await _scalar(
        db_session,
        "INSERT INTO users (username, password_hash, display_name_ru)"
        " VALUES ('trainee1', 'x', 'Стажёр') RETURNING id",
    )
    ids["scenario"] = await _scalar(
        db_session,
        "INSERT INTO scenarios (slug, title_ru) VALUES ('fire-01', 'Пожар') RETURNING id",
    )
    ids["scenario_version"] = await _scalar(
        db_session,
        "INSERT INTO scenario_versions"
        " (scenario_id, version, schema_version, title, deterministic_seed, role_chain,"
        "  content, content_sha256)"
        " VALUES (:scenario_id, 1, 1, 'v1', 'seed', ARRAY['OPERATOR_112'],"
        "  CAST(:content AS jsonb), 'sha') RETURNING id",
        scenario_id=ids["scenario"],
        content=json.dumps({"version": 1}),
    )
    ids["session"] = await _scalar(
        db_session,
        "INSERT INTO simulation_sessions"
        " (scenario_version_id, session_mode, session_seed, created_by_user_id)"
        " VALUES (:scenario_version_id, 'SINGLE_ROLE', 'seed', :user_id) RETURNING id",
        scenario_version_id=ids["scenario_version"],
        user_id=ids["user"],
    )
    ids["incident"] = await _scalar(
        db_session,
        "INSERT INTO incidents (session_id, scenario_version_id)"
        " VALUES (:session_id, :scenario_version_id) RETURNING id",
        session_id=ids["session"],
        scenario_version_id=ids["scenario_version"],
    )
    ids["card"] = await _scalar(
        db_session,
        "INSERT INTO incident_cards (incident_id) VALUES (:incident_id) RETURNING id",
        incident_id=ids["incident"],
    )
    ids["session_event"] = await _scalar(
        db_session,
        "INSERT INTO session_events"
        " (session_id, seq_no, event_type, monotonic_offset_ms, actor_type)"
        " VALUES (:session_id, 1, 'SESSION_CREATED', 0, 'SYSTEM') RETURNING id",
        session_id=ids["session"],
    )
    ids["card_revision"] = await _scalar(
        db_session,
        "INSERT INTO incident_card_revisions"
        " (card_id, revision_no, field_path, value_type, actor_type, at_offset_ms)"
        " VALUES (:card_id, 1, 'location.address', 'STRING', 'TRAINEE', 100) RETURNING id",
        card_id=ids["card"],
    )
    ids["snapshot"] = await _scalar(
        db_session,
        "INSERT INTO handoff_snapshots"
        " (incident_id, card_id, card_values, recipient_services, content_sha256,"
        "  created_by_user_id, created_at_offset_ms)"
        " VALUES (:incident_id, :card_id, CAST(:card_values AS jsonb), ARRAY['FIRE_RESCUE'],"
        "  'sha', :user_id, 200) RETURNING id",
        incident_id=ids["incident"],
        card_id=ids["card"],
        card_values=json.dumps({"location.address": "ул. Ленина, 1"}),
        user_id=ids["user"],
    )
    return ids
