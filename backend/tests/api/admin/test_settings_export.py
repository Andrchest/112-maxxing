"""`exportSettingsXml` over real HTTP (I5 E37, Q-E16-1): ADMIN only, no secret name in the body,
and every read leaves its own `audit_log` row (E25).

The secret list is derived from `Settings` itself (`app.config.settings_xml.SECRET_FIELD_NAMES`),
never retyped here (this epic's own `CHECK`) — the assertion below re-derives it independently
from `Settings.model_fields` so a future secret field that forgets `repr=False` would fail this
test too, not just `test_settings_xml.py`'s unit one.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.api.container import Container
from app.config.settings import Settings
from app.domain.common.ids import UserId
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth

pytestmark = pytest.mark.integration


async def _rows(engine: AsyncEngine, operation_id: str) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT * FROM audit_log WHERE operation_id = :op ORDER BY ts, id"),
            {"op": operation_id},
        )
        return [dict(row._mapping) for row in result]


async def test_an_admin_downloads_the_settings_with_no_secret_name(
    client: httpx.AsyncClient,
    container: Container,
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    before = await _rows(migrated_engine, "exportSettingsXml")

    response = await client.get("/api/v1/admin/settings/export", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/xml")
    assert "settings.xml" in response.headers["content-disposition"]
    body = response.text
    assert body.startswith('<settings version="1">')

    secret_field_names = {
        name for name, info in Settings.model_fields.items() if info.repr is False
    }
    assert secret_field_names, "the derivation itself must find at least one secret field"
    for field_name in secret_field_names:
        env_name = f"SIM_{field_name.upper()}"
        assert f'name="{env_name}"' not in body, f"{env_name} leaked into exportSettingsXml"
    assert str(container.settings.jwt_secret) not in body
    assert str(container.settings.database_url) not in body

    after = await _rows(migrated_engine, "exportSettingsXml")
    (row,) = [item for item in after if item not in before]
    assert row["user_id"] == users["admin1"]
    assert row["role"] == "ADMIN"
    assert (row["action"], row["outcome"], row["status"]) == ("HTTP_REQUEST", "OK", 200)


@pytest.mark.parametrize("account", ["instructor1", "trainee1"])
async def test_a_non_admin_is_refused(
    client: httpx.AsyncClient, tokens: dict[str, str], account: str
) -> None:
    response = await client.get("/api/v1/admin/settings/export", headers=auth(tokens[account]))
    assert response.status_code == 403


async def test_without_a_token_it_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/admin/settings/export")
    assert response.status_code == 401
