"""Migration `0012_dds_response_status` (I3 E5a; HLD `70-i3-alignment.md` §70.4.3, §70.4.4, §70.8).

The load-bearing part is the **backfill**: `dds_assignments.response_status` of every leg that
exists before the upgrade is §70.4.4's picker map of its `state`. The five pre-existing sessions of
`test_lessons_migration.py` are written at revision `0011` on a throwaway database — among them a
picker leg in `DISPATCHED`, which must come out `ACCEPTED` — and after `upgrade head` each leg has
its mirrored status; `downgrade -1` / `upgrade` round-trips, `alembic check` finds no drift, and the
new `dds_service_status_history` rejects UPDATE and DELETE like `session_events`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import pytest

from tests.integration.db import alembic_support as support
from tests.integration.db.test_lessons_migration import _base_url, _dsn, seed_pre_0011

pytestmark = pytest.mark.integration

PRE_0012 = "0011_lessons"

#: `(state, closure_reason) -> backfilled response_status`, per §70.4.4's picker map.
EXPECTED = {
    ("CLOSED", "RESOLVED"): "COMPLETED",
    ("WORKING", None): "WORKING",
    ("ACKNOWLEDGED", None): "ACCEPTED",
    ("DISPATCHED", None): "ACCEPTED",
}


async def legs(url: str) -> list[dict[str, Any]]:
    connection = await asyncpg.connect(_dsn(url))
    try:
        rows = await connection.fetch(
            "SELECT id, state, closure_reason, received_at_offset_ms, acknowledged_at_offset_ms,"
            " response_status, response_status_at_offset_ms, accept_missed, responder,"
            " bound_user_id FROM dds_assignments ORDER BY state, id"
        )
    finally:
        await connection.close()
    return [dict(row) for row in rows]


async def history_rejects_mutation(url: str) -> tuple[str, str]:
    """Insert one history row, then try to UPDATE and DELETE it; returns both error messages."""
    connection = await asyncpg.connect(_dsn(url))
    try:
        leg = await connection.fetchrow(
            "SELECT a.id, s.session_id FROM dds_assignments a"
            " JOIN role_stages s ON s.id = a.role_stage_id LIMIT 1"
        )
        event = await connection.fetchval(
            "SELECT id FROM session_events WHERE session_id = $1 ORDER BY seq_no LIMIT 1",
            leg["session_id"],
        )
        await connection.execute(
            "INSERT INTO dds_service_status_history (session_id, assignment_id, event_id, seq_no,"
            " previous_status, new_status, source, actor_type, at_offset_ms)"
            " VALUES ($1, $2, $3, 1, 'ADDED', 'RECEIVED', 'SYSTEM', 'SIMULATION', 0)",
            leg["session_id"],
            leg["id"],
            event,
        )
        messages: list[str] = []
        for statement in (
            "UPDATE dds_service_status_history SET new_status = 'ACCEPTED'",
            "DELETE FROM dds_service_status_history",
        ):
            with pytest.raises(asyncpg.RestrictViolationError) as excinfo:
                await connection.execute(statement)
            messages.append(str(excinfo.value))
    finally:
        await connection.close()
    return messages[0], messages[1]


def test_the_backfill_mirrors_every_existing_leg_and_round_trips() -> None:
    base_url = _base_url()
    name = support.random_database_name("sim_0012_")
    url = support.replace_database(base_url, name)
    support.create_database(base_url, name)
    try:
        support.upgrade(url, PRE_0012)
        asyncio.run(seed_pre_0011(url))

        support.upgrade(url)
        after = asyncio.run(legs(url))
        assert len(after) == 5
        for leg in after:
            assert leg["response_status"] == EXPECTED[(leg["state"], leg["closure_reason"])], leg
            assert leg["accept_missed"] is False
            assert leg["responder"] == "TRAINEE"
            assert leg["bound_user_id"] is None
        dispatched = next(leg for leg in after if leg["state"] == "DISPATCHED")
        assert dispatched["response_status"] == "ACCEPTED"
        assert dispatched["response_status_at_offset_ms"] == dispatched["acknowledged_at_offset_ms"]

        support.downgrade(url, "-1")
        support.upgrade(url)
        again = asyncio.run(legs(url))
        assert [leg["response_status"] for leg in again] == [
            leg["response_status"] for leg in after
        ]
        support.check(url)

        update_error, delete_error = asyncio.run(history_rejects_mutation(url))
        assert "append-only" in update_error
        assert "append-only" in delete_error
    finally:
        support.drop_database(base_url, name)
