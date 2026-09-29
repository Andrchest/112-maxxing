"""The ДДС screen's «ЧС» / «ЧП» marks over HTTP (I7 E55; owner decision 2026-09-29, Q9).

`setDdsCardMarks` on the committed memo example `street-rubbish-fire`:

* both marks start `false`; a change appends one `DDS_CARD_MARKS_SET` (TRAINEE) and answers with
  the work item carrying the new marks; the same pair again appends nothing;
* the marks reach every reader — `getDdsWorkItem`, the restore snapshot and, read-only, the
  instructor overview;
* the audit row's «было → стало» carries `dds_card.chs` / `dds_card.chp` (I7 E43);
* the instructor may not set them (`403`), and a picker session refuses them (`409`).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
from app.domain.common.ids import ScenarioVersionId, UserId
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api._audit_changes import audit_ids, changes_by_field, new_row
from tests.api.conftest import auth
from tests.api.dds.test_memo_mode import (
    API,
    events,
    rubbish_version_id,  # noqa: F401 - a fixture, used by name
    start_session,
)

pytestmark = pytest.mark.integration


async def _set_marks(
    client: httpx.AsyncClient, token: str, session_id: UUID, *, chs: bool, chp: bool
) -> httpx.Response:
    return await client.post(
        f"{API}/{session_id}/dds/card-marks", headers=auth(token), json={"chs": chs, "chp": chp}
    )


async def _marks_events(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID
) -> list[dict[str, Any]]:
    return [
        item["payload"]
        for item in await events(client, tokens, session_id)
        if item["event_type"] == "DDS_CARD_MARKS_SET"
    ]


async def test_the_dds_sets_the_marks_and_every_reader_sees_them(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,  # noqa: F811 - the imported fixture
    migrated_engine: AsyncEngine,
) -> None:
    session_id = await start_session(client, tokens, users, rubbish_version_id)
    token = tokens["trainee2"]
    item = await client.get(f"{API}/{session_id}/dds/work-item", headers=auth(token))
    assert item.status_code == 200, item.text
    assert item.json()["dds_marks"] == {"chs": False, "chp": False}

    before = await audit_ids(migrated_engine)
    response = await _set_marks(client, token, session_id, chs=True, chp=False)
    assert response.status_code == 200, response.text
    assert response.json()["dds_marks"] == {"chs": True, "chp": False}
    assert changes_by_field(await new_row(migrated_engine, before, "setDdsCardMarks")) == {
        "dds_card.chs": (False, True)
    }
    payloads = await _marks_events(client, tokens, session_id)
    assert len(payloads) == 1
    assert {key: payloads[0][key] for key in ("previous_chs", "previous_chp", "chs", "chp")} == {
        "previous_chs": False,
        "previous_chp": False,
        "chs": True,
        "chp": False,
    }
    assert payloads[0]["actor_user_id"] == str(users["trainee2"])

    # The same pair again: nothing appended, nothing in «было → стало».
    before = await audit_ids(migrated_engine)
    again = await _set_marks(client, token, session_id, chs=True, chp=False)
    assert again.status_code == 200, again.text
    assert len(await _marks_events(client, tokens, session_id)) == 1
    assert changes_by_field(await new_row(migrated_engine, before, "setDdsCardMarks")) == {}

    both = await _set_marks(client, token, session_id, chs=False, chp=True)
    assert both.status_code == 200, both.text
    expected = {"chs": False, "chp": True}
    item = await client.get(f"{API}/{session_id}/dds/work-item", headers=auth(token))
    assert item.json()["dds_marks"] == expected
    snapshot = await client.get(f"{API}/{session_id}/snapshot", headers=auth(token))
    assert snapshot.json()["work_item"]["dds_marks"] == expected
    overview = await client.get(
        f"/api/v1/instructor/sessions/{session_id}/overview",
        headers=auth(tokens["instructor1"]),
    )
    assert overview.status_code == 200, overview.text
    assert {tuple(a["dds_marks"].values()) for a in overview.json()["assignments"]} == {
        (False, True)
    }


async def test_the_instructor_may_not_set_the_marks(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,  # noqa: F811 - the imported fixture
) -> None:
    session_id = await start_session(client, tokens, users, rubbish_version_id)
    refused = await _set_marks(client, tokens["instructor1"], session_id, chs=True, chp=True)
    assert refused.status_code == 403, refused.text
    assert await _marks_events(client, tokens, session_id) == []


async def test_a_picker_session_refuses_the_marks(
    client: httpx.AsyncClient, tokens: dict[str, str], dds_only_session: UUID
) -> None:
    refused = await _set_marks(client, tokens["trainee2"], dds_only_session, chs=True, chp=False)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ACTION_NOT_AVAILABLE"
