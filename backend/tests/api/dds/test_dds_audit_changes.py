"""«было → стало» on the session-flow rows it is cheap for (I7 E43): the session's state on
`startSession` / `abortSession`, and a leg's status on `setDdsServiceStatus`.

Everything else a session command changes stays in the session's own event log (D5), which already
carries each value; those rows have no `changes`.
"""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from app.domain.common.ids import ScenarioVersionId, UserId
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api._audit_changes import audit_ids, changes_by_field, new_row
from tests.api.conftest import auth
from tests.api.dds.test_memo_mode import (
    API,
    legs,
    rubbish_version_id,  # noqa: F401 - a fixture, used by name
    set_status,
    start_session,
)

pytestmark = pytest.mark.integration


async def test_start_status_and_abort_record_their_before_and_after(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,  # noqa: F811 - the imported fixture
    migrated_engine: AsyncEngine,
) -> None:
    before = await audit_ids(migrated_engine)
    session_id: UUID = await start_session(client, tokens, users, rubbish_version_id)
    assert changes_by_field(await new_row(migrated_engine, before, "createSession")) == {}
    assert changes_by_field(await new_row(migrated_engine, before, "startSession")) == {
        "session.state": ("READY", "ACTIVE")
    }

    token = tokens["trainee2"]
    fire = (await legs(client, token, session_id))["FIRE_RESCUE"]["assignment_id"]
    before = await audit_ids(migrated_engine)
    accepted = await set_status(client, token, session_id, fire, "ACCEPTED")
    assert accepted.status_code == 200, accepted.text
    assert changes_by_field(await new_row(migrated_engine, before, "setDdsServiceStatus")) == {
        "dds_leg.response_status": ("ADDED", "ACCEPTED")
    }

    before = await audit_ids(migrated_engine)
    aborted = await client.post(
        f"{API}/{session_id}/abort", headers=auth(tokens["instructor1"]), json={"reason": "тест"}
    )
    assert aborted.status_code == 200, aborted.text
    assert changes_by_field(await new_row(migrated_engine, before, "abortSession")) == {
        "session.state": ("ACTIVE", "ABORTED")
    }
