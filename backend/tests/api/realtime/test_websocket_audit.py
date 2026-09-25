"""WebSocket connects are audited (I4 E25, `71-i4-wave4.md` §71.2, HLD 20 §20.6 `audit_log`).

A connect is one entry, written at the accept: `WS_CONNECTED` naming the caller, or — for a socket
accepted only to deliver a §40.1 close code — `ACCESS_DENIED` (`4401`, `4403`) or an `ERROR`
connect (`4404`). The token travels in the query string and never reaches the entry.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import create_demo_session, participant
from tests.api.realtime.conftest import ASGIWebSocket

pytestmark = pytest.mark.integration

UNKNOWN_SESSION = "22222222-2222-4222-8222-222222222222"
_WS_TEMPLATE = "/api/v1/ws/sessions/{session_id}"


@pytest.fixture
async def session_id(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
) -> SessionId:
    """A 112 → DDS session with `trainee1` on 112 and `trainee2` on DDS."""
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [
            participant(users["trainee1"], "OPERATOR_112"),
            participant(users["trainee2"], "DDS"),
        ],
    )
    return SessionId(detail["id"])


async def _audit_ids(engine: AsyncEngine) -> set[UUID]:
    async with engine.connect() as connection:
        return {row[0] for row in await connection.execute(text("SELECT id FROM audit_log"))}


async def _rows_since(engine: AsyncEngine, before: set[UUID]) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT a.*, row_to_json(a)::text AS raw FROM audit_log a ORDER BY ts, id")
        )
        return [dict(row._mapping) for row in result if row._mapping["id"] not in before]


async def test_a_connect_is_one_ws_connected_entry_naming_the_caller(
    websocket: Callable[..., ASGIWebSocket],
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
    session_id: SessionId,
) -> None:
    before = await _audit_ids(migrated_engine)
    async with websocket(session_id, token=tokens["trainee1"]) as socket:
        await socket.send_json({"type": "resume", "after_seq_no": 0})
        await socket.receive_until("resume_complete")

    (row,) = await _rows_since(migrated_engine, before)
    assert (row["action"], row["outcome"], row["status"]) == ("WS_CONNECTED", "OK", 101)
    assert (row["user_id"], row["role"]) == (users["trainee1"], "TRAINEE")
    assert row["path_template"] == _WS_TEMPLATE
    assert row["target_ids"] == {"session_id": str(session_id)}
    assert row["operation_id"] is None
    assert tokens["trainee1"] not in row["raw"]


async def test_a_missing_token_is_an_access_denied_4401(
    websocket: Callable[..., ASGIWebSocket],
    migrated_engine: AsyncEngine,
    session_id: SessionId,
) -> None:
    before = await _audit_ids(migrated_engine)
    async with websocket(session_id) as socket:
        assert await socket.expect_close() == 4401

    (row,) = await _rows_since(migrated_engine, before)
    assert (row["action"], row["outcome"], row["status"]) == ("ACCESS_DENIED", "DENIED", 4401)
    assert row["user_id"] is None


async def test_an_invalid_token_is_denied_and_never_stored(
    websocket: Callable[..., ASGIWebSocket],
    migrated_engine: AsyncEngine,
    session_id: SessionId,
) -> None:
    before = await _audit_ids(migrated_engine)
    async with websocket(session_id, token="e25-not-a-jwt") as socket:
        assert await socket.expect_close() == 4401

    (row,) = await _rows_since(migrated_engine, before)
    assert row["action"] == "ACCESS_DENIED"
    assert "e25-not-a-jwt" not in row["raw"]


async def test_a_non_participant_is_an_access_denied_4403_naming_them(
    websocket: Callable[..., ASGIWebSocket],
    migrated_engine: AsyncEngine,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [
            participant(users["trainee1"], "OPERATOR_112"),
            participant(users["instructor1"], "DDS"),
        ],
    )
    before = await _audit_ids(migrated_engine)
    async with websocket(detail["id"], token=tokens["trainee2"]) as socket:
        assert await socket.expect_close() == 4403

    (row,) = await _rows_since(migrated_engine, before)
    assert (row["action"], row["outcome"], row["status"]) == ("ACCESS_DENIED", "DENIED", 4403)
    assert row["user_id"] == users["trainee2"]


async def test_an_unknown_session_is_an_error_connect_4404(
    websocket: Callable[..., ASGIWebSocket],
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    before = await _audit_ids(migrated_engine)
    async with websocket(UNKNOWN_SESSION, token=tokens["instructor1"]) as socket:
        assert await socket.expect_close() == 4404

    (row,) = await _rows_since(migrated_engine, before)
    assert (row["action"], row["outcome"], row["status"]) == ("WS_CONNECTED", "ERROR", 4404)
    assert row["user_id"] == users["instructor1"]
