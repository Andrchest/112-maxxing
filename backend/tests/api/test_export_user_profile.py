"""`GET /api/v1/users/{user_id}/profile-export` — `exportUserProfile` (I5 E37, Q-E16-4, ТЗ ¶363).

* allowed for the account itself and for ADMIN only — an INSTRUCTOR or another TRAINEE reading
  someone else's profile is `403 FORBIDDEN_FOR_ROLE`, deliberately narrower than the read access
  Q-E14-1 gives ADMIN/INSTRUCTOR elsewhere;
* the JSON never carries the password hash or the SIP HA1 — proved on the **exact property set**,
  the same discipline `tests/api/test_users.py` uses for `listUsers`;
* `history` is the E33 summary for a TRAINEE account, `null` for INSTRUCTOR/ADMIN;
* downloads as `profile-<username>.json` (`Content-Disposition`);
* audited like every operation (E25), naming the caller and the target user id.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.domain.common.ids import UserId
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth

pytestmark = pytest.mark.integration

#: `UserProfileExport`'s `required` (`additionalProperties: false`) — the whole object. Never
#: `password_hash`, never `sip_ha1`.
PROFILE_PROPERTIES = {
    "id",
    "username",
    "display_name_ru",
    "user_role",
    "created_at",
    "is_active",
    "history",
}

#: `TraineeStatisticsRow`'s own property set (`app.api.schemas.statistics`) — asserted the same way
#: so a `history` object cannot smuggle anything extra either.
HISTORY_PROPERTIES = {
    "trainee_user_id",
    "display_name_ru",
    "session_count",
    "lesson_count",
    "average_percent",
    "failed_rules_by_category",
    "accept_deviation_ms_avg",
    "fill_deviation_ms_avg",
    "reaction_to_open_ms_avg",
    "reaction_to_status_ms_avg",
    # I5 E38: pass verdict aggregates on the history summary.
    "pass_count",
    "pass_rate",
}


def _url(user_id: object) -> str:
    return f"/api/v1/users/{user_id}/profile-export"


async def _rows(engine: AsyncEngine, user_id: object) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT * FROM audit_log WHERE operation_id = 'exportUserProfile'"
                " AND target_ids ->> 'user_id' = :user_id ORDER BY ts, id"
            ),
            {"user_id": str(user_id)},
        )
        return [dict(row._mapping) for row in result]


async def test_a_trainee_downloads_their_own_profile_with_no_secret_field(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    response = await client.get(_url(users["trainee1"]), headers=auth(tokens["trainee1"]))

    assert response.status_code == 200, response.text
    assert "profile-trainee1.json" in response.headers["content-disposition"]
    body = response.json()
    assert set(body.keys()) == PROFILE_PROPERTIES
    assert body["id"] == str(users["trainee1"])
    assert body["username"] == "trainee1"
    assert body["user_role"] == "TRAINEE"
    assert body["history"] is not None
    assert set(body["history"].keys()) == HISTORY_PROPERTIES
    assert "password_hash" not in body
    assert "sip_ha1" not in body


async def test_an_admin_downloads_an_instructor_s_profile_with_a_null_history(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    response = await client.get(_url(users["instructor1"]), headers=auth(tokens["admin1"]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body.keys()) == PROFILE_PROPERTIES
    assert body["user_role"] == "INSTRUCTOR"
    assert body["history"] is None


async def test_an_admin_downloads_a_trainee_s_profile(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    response = await client.get(_url(users["trainee2"]), headers=auth(tokens["admin1"]))
    assert response.status_code == 200, response.text
    assert response.json()["history"] is not None


@pytest.mark.parametrize("account", ["instructor1", "trainee2"])
async def test_someone_else_is_refused_even_an_instructor(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId], account: str
) -> None:
    response = await client.get(_url(users["trainee1"]), headers=auth(tokens[account]))
    assert response.status_code == 403


async def test_an_unknown_account_is_404(client: httpx.AsyncClient, tokens: dict[str, str]) -> None:
    response = await client.get(_url(uuid4()), headers=auth(tokens["admin1"]))
    assert response.status_code == 404


async def test_without_a_token_it_is_401(
    client: httpx.AsyncClient, users: dict[str, UserId]
) -> None:
    response = await client.get(_url(users["trainee1"]))
    assert response.status_code == 401


async def test_the_read_is_audited_by_name_and_target(
    client: httpx.AsyncClient,
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    response = await client.get(_url(users["trainee1"]), headers=auth(tokens["admin1"]))
    assert response.status_code == 200, response.text

    rows = await _rows(migrated_engine, users["trainee1"])
    (row,) = [r for r in rows if r["user_id"] == users["admin1"]]
    assert row["role"] == "ADMIN"
    assert (row["action"], row["outcome"], row["status"]) == ("HTTP_REQUEST", "OK", 200)
    assert row["target_ids"] == {"user_id": str(users["trainee1"])}
