"""Migration `0011_lessons` (I3 E4a; HLD `70-i3-alignment.md` §70.3, §70.4.6, §70.8).

The load-bearing part is the **backfill**: `incidents.card_status` of every incident that exists
before the upgrade is computed by the §70.4.6 function with the §70.4.4 picker mirror, over
existing columns only. Four pre-existing sessions, one per branch the backfill can take, are
written at revision `0010` on a throwaway database; after `upgrade head` each has its status, every
incident has a distinct `display_number`, and `downgrade -1` / `upgrade` round-trips.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from tests.integration.db import alembic_support as support

pytestmark = pytest.mark.integration

PRE_0011 = "0010_service_id_open"

#: `(label, session state, started, released, last event offset, legs)` — a leg is
#: `(state, received_at, acknowledged_at, closure_reason)`.
SESSIONS: tuple[
    tuple[str, str, bool, bool, int, tuple[tuple[str, int, int | None, str | None], ...]], ...
] = (
    # Closed RESOLVED, acknowledged in time: every leg COMPLETED.
    (
        "completed",
        "COMPLETED",
        True,
        False,
        600_000,
        (("CLOSED", 1_000, 5_000, "RESOLVED"), ("CLOSED", 1_000, 5_000, "RESOLVED")),
    ),
    # Acknowledged 44 s after receipt: the 30 s accept deadline was missed — sticky.
    ("not_notified", "COMPLETED", True, True, 300_000, (("WORKING", 1_000, 45_000, None),)),
    # Acknowledged in time, still working, report released: CHECKED.
    ("checked", "COMPLETED", True, True, 200_000, (("ACKNOWLEDGED", 1_000, 10_000, None),)),
    # Handed off, acknowledged in time, not released: WORKED.
    ("worked", "ACTIVE", True, False, 50_000, (("DISPATCHED", 1_000, 2_000, None),)),
    # Never started.
    ("registered", "READY", False, False, 0, ()),
)
EXPECTED = {
    "completed": "COMPLETED",
    "not_notified": "NOT_NOTIFIED",
    "checked": "CHECKED",
    "worked": "WORKED",
    "registered": "REGISTERED",
}


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def seed_pre_0011(url: str) -> dict[str, UUID]:
    """Write `SESSIONS` at revision `0010`; returns `label -> incident id`."""
    connection = await asyncpg.connect(_dsn(url))
    incidents: dict[str, UUID] = {}
    try:
        user = await connection.fetchval(
            "INSERT INTO users (username, password_hash, display_name_ru)"
            " VALUES ('instructor-0011', 'x', 'Инструктор') RETURNING id"
        )
        scenario = await connection.fetchval(
            "INSERT INTO scenarios (slug, title_ru) VALUES ('fire-0011', 'Пожар') RETURNING id"
        )
        version = await connection.fetchval(
            "INSERT INTO scenario_versions (scenario_id, version, schema_version, title,"
            " deterministic_seed, role_chain, content, content_sha256)"
            " VALUES ($1, 1, 1, 'v1', 'seed', ARRAY['DDS'], '{}'::jsonb, 'sha') RETURNING id",
            scenario,
        )
        for label, state, started, released, last_offset, legs in SESSIONS:
            session = await connection.fetchval(
                "INSERT INTO simulation_sessions (scenario_version_id, session_mode, state,"
                " session_seed, created_by_user_id, started_at, report_released_at,"
                " report_released_by_user_id)"
                " VALUES ($1, 'SINGLE_ROLE', $2, 'seed', $3,"
                " CASE WHEN $4 THEN now() END, CASE WHEN $5 THEN now() END,"
                " CASE WHEN $5 THEN $3::uuid END) RETURNING id",
                version,
                state,
                user,
                started,
                released,
            )
            incident = await connection.fetchval(
                "INSERT INTO incidents (session_id, scenario_version_id) VALUES ($1, $2)"
                " RETURNING id",
                session,
                version,
            )
            incidents[label] = incident
            await connection.execute(
                "INSERT INTO session_events (session_id, seq_no, event_type, monotonic_offset_ms,"
                " actor_type) VALUES ($1, 1, 'SESSION_CREATED', 0, 'SYSTEM'),"
                " ($1, 2, 'SESSION_STARTED', $2, 'INSTRUCTOR')",
                session,
                last_offset,
            )
            if not legs:
                continue
            stage = await connection.fetchval(
                "INSERT INTO role_stages (session_id, incident_id, role_type, order_index, state)"
                " VALUES ($1, $2, 'DDS', 0, 'RECEIVED') RETURNING id",
                session,
                incident,
            )
            card = await connection.fetchval(
                "INSERT INTO incident_cards (incident_id) VALUES ($1) RETURNING id", incident
            )
            snapshot = await connection.fetchval(
                "INSERT INTO handoff_snapshots (incident_id, card_id, card_values,"
                " recipient_services, content_sha256, created_by_user_id, created_at_offset_ms)"
                " VALUES ($1, $2, $3::jsonb, ARRAY['FIRE_RESCUE'], 'sha', $4, 1000) RETURNING id",
                incident,
                card,
                json.dumps({}),
                user,
            )
            for index, (leg_state, received, acknowledged, closure) in enumerate(legs):
                await connection.execute(
                    "INSERT INTO dds_assignments (incident_id, role_stage_id, snapshot_id,"
                    " service_type, state, received_at_offset_ms, acknowledged_at_offset_ms,"
                    " closure_reason) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                    incident,
                    stage,
                    snapshot,
                    ("FIRE_RESCUE", "AMBULANCE")[index],
                    leg_state,
                    received,
                    acknowledged,
                    closure,
                )
    finally:
        await connection.close()
    return incidents


async def card_statuses(url: str) -> dict[UUID, tuple[str, int]]:
    connection = await asyncpg.connect(_dsn(url))
    try:
        rows = await connection.fetch("SELECT id, card_status, display_number FROM incidents")
    finally:
        await connection.close()
    return {row["id"]: (row["card_status"], row["display_number"]) for row in rows}


def _base_url() -> str:
    return os.environ.get(
        "SIM_DATABASE_URL", "postgresql+asyncpg://sim:sim@localhost:55432/sim_test"
    )


def test_the_backfill_derives_every_existing_card_status_and_round_trips() -> None:
    base_url = _base_url()
    name = support.random_database_name("sim_0011_")
    url = support.replace_database(base_url, name)
    support.create_database(base_url, name)
    try:
        support.upgrade(url, PRE_0011)
        incidents = asyncio.run(seed_pre_0011(url))

        support.upgrade(url)
        after: dict[UUID, Any] = asyncio.run(card_statuses(url))
        assert {label: after[incident][0] for label, incident in incidents.items()} == EXPECTED
        numbers = [number for _status, number in after.values()]
        assert len(set(numbers)) == len(numbers) == len(SESSIONS)

        support.downgrade(url, "-1")
        support.upgrade(url)
        again = asyncio.run(card_statuses(url))
        assert {label: again[incident][0] for label, incident in incidents.items()} == EXPECTED
        support.check(url)
    finally:
        support.drop_database(base_url, name)
