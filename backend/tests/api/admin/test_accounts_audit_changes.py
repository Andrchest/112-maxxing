"""«было → стало» on the accounts' audit rows (I7 E43, Q-E15-3; ТЗ ¶246, ¶296).

`createUser`, `updateUser` (role / name / block / unblock) and `resetUserPassword` each leave their
one `audit_log` row carrying `changes`; a password is only ever «изменён» (both values `null`) and
neither the password nor its digest appears anywhere in the row. `listAuditLog` returns the list
and filters on it (`with_changes`).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.domain.common.ids import UserId
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api._audit_changes import audit_ids, changes_by_field, new_row
from tests.api.conftest import auth

pytestmark = pytest.mark.integration

USERS_URL = "/api/v1/admin/users"
#: Passwords no fixture uses, so finding one in a row can only mean it was stored.
_CREATE_PASSWORD = "e43-create-password-never-stored"
_RESET_PASSWORD = "e43-reset-password-never-stored"


async def _create(client: httpx.AsyncClient, token: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "username": f"e43-{uuid4().hex[:12]}",
        "display_name_ru": "Стажёр E43",
        "user_role": "TRAINEE",
        "password": _CREATE_PASSWORD,
    }
    body.update(overrides)
    response = await client.post(USERS_URL, headers=auth(token), json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def test_create_user_records_the_new_account_and_a_password_without_value(
    client: httpx.AsyncClient, tokens: dict[str, str], migrated_engine: AsyncEngine
) -> None:
    before = await audit_ids(migrated_engine)
    created = await _create(client, tokens["admin1"], user_role="INSTRUCTOR")

    row = await new_row(migrated_engine, before, "createUser")
    assert changes_by_field(row) == {
        "user.username": (None, created["username"]),
        "user.display_name_ru": (None, "Стажёр E43"),
        "user.user_role": (None, "INSTRUCTOR"),
        "user.is_active": (None, True),
        "user.password": (None, None),
    }


async def test_update_user_records_role_and_name_before_and_after(
    client: httpx.AsyncClient, tokens: dict[str, str], migrated_engine: AsyncEngine
) -> None:
    created = await _create(client, tokens["admin1"])
    before = await audit_ids(migrated_engine)
    response = await client.patch(
        f"{USERS_URL}/{created['id']}",
        headers=auth(tokens["admin1"]),
        json={"user_role": "INSTRUCTOR", "display_name_ru": "Инструктор E43"},
    )
    assert response.status_code == 200, response.text

    row = await new_row(migrated_engine, before, "updateUser")
    assert changes_by_field(row) == {
        "user.display_name_ru": ("Стажёр E43", "Инструктор E43"),
        "user.user_role": ("TRAINEE", "INSTRUCTOR"),
    }


@pytest.mark.parametrize(("is_active", "expected"), [(False, (True, False)), (True, None)])
async def test_block_and_unblock_record_is_active(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    migrated_engine: AsyncEngine,
    is_active: bool,
    expected: tuple[bool, bool] | None,
) -> None:
    created = await _create(client, tokens["admin1"])
    url = f"{USERS_URL}/{created['id']}"
    if is_active:  # unblock: block first, then look at the unblock's own row
        blocked = await client.patch(url, headers=auth(tokens["admin1"]), json={"is_active": False})
        assert blocked.status_code == 200
        expected = (False, True)
    before = await audit_ids(migrated_engine)
    response = await client.patch(
        url, headers=auth(tokens["admin1"]), json={"is_active": is_active}
    )
    assert response.status_code == 200, response.text

    row = await new_row(migrated_engine, before, "updateUser")
    assert changes_by_field(row) == {"user.is_active": expected}


async def test_an_unchanged_update_records_no_changes(
    client: httpx.AsyncClient, tokens: dict[str, str], migrated_engine: AsyncEngine
) -> None:
    created = await _create(client, tokens["admin1"])
    before = await audit_ids(migrated_engine)
    response = await client.patch(
        f"{USERS_URL}/{created['id']}",
        headers=auth(tokens["admin1"]),
        json={"user_role": "TRAINEE"},
    )
    assert response.status_code == 200
    row = await new_row(migrated_engine, before, "updateUser")
    assert row["changes"] is None


async def test_reset_password_records_password_changed_without_any_value(
    client: httpx.AsyncClient, tokens: dict[str, str], migrated_engine: AsyncEngine
) -> None:
    created = await _create(client, tokens["admin1"])
    before = await audit_ids(migrated_engine)
    response = await client.post(
        f"{USERS_URL}/{created['id']}/password",
        headers=auth(tokens["admin1"]),
        json={"password": _RESET_PASSWORD},
    )
    assert response.status_code == 204

    row = await new_row(migrated_engine, before, "resetUserPassword")
    assert row["changes"] == [{"field": "user.password", "before": None, "after": None}]


async def test_no_secret_ever_reaches_an_audit_row(
    client: httpx.AsyncClient, tokens: dict[str, str], migrated_engine: AsyncEngine
) -> None:
    """Neither a password nor its digest (`fake$<password>`) is in any row the flows wrote."""
    before = await audit_ids(migrated_engine)
    created = await _create(client, tokens["admin1"])
    await client.post(
        f"{USERS_URL}/{created['id']}/password",
        headers=auth(tokens["admin1"]),
        json={"password": _RESET_PASSWORD},
    )
    rows = [
        await new_row(migrated_engine, before, "createUser"),
        await new_row(migrated_engine, before, "resetUserPassword"),
    ]
    dumped = json.dumps([row["changes"] for row in rows], ensure_ascii=False)
    for secret in (_CREATE_PASSWORD, _RESET_PASSWORD, "fake$"):
        assert secret not in dumped
    for row in rows:
        for change in row["changes"]:
            if "password" in change["field"]:
                assert change["before"] is None and change["after"] is None


async def test_list_audit_log_returns_changes_and_filters_on_them(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    await _create(client, tokens["admin1"])
    response = await client.get(
        "/api/v1/admin/audit-log",
        headers=auth(tokens["admin1"]),
        params={"with_changes": "true", "user_id": str(users["admin1"]), "limit": 500},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items, "the createUser row carries changes"
    assert all(item["changes"] for item in items)
    create_row = next(item for item in items if item["operation_id"] == "createUser")
    assert {"field": "user.user_role", "before": None, "after": "TRAINEE"} in create_row["changes"]

    everything = await client.get(
        "/api/v1/admin/audit-log",
        headers=auth(tokens["admin1"]),
        params={"user_id": str(users["admin1"]), "limit": 500},
    )
    assert any(item["changes"] == [] for item in everything.json()["items"])
