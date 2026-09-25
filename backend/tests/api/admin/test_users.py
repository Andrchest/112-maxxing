"""`createUser` / `updateUser` / `resetUserPassword` (ADMIN, ТЗ ¶195-¶197, I4 E28, §71.5).

Everything the epic's acceptance list names:

* the role gate — INSTRUCTOR and TRAINEE get `403` on all three operations;
* the self and last-admin guards hold;
* a blocked user's live token is refused on the next request (already true at `get_current_user`;
  asserted here for the new write path);
* each operation leaves one audit entry (`app.api.audit.AuditMiddleware`, I4 E25) — proved through
  `AuditReader` the same way `tests/api/test_audit_log.py` proves it for the rest of the contract.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.api.container import Container
from app.application.ports.audit_log import AuditAction, AuditFilter
from app.domain.common.ids import UserId

from tests.api.conftest import auth

pytestmark = pytest.mark.integration

USERS_URL = "/api/v1/admin/users"


def _create_body(**overrides: Any) -> dict[str, Any]:
    """`createUser`'s body. `username` defaults to a fresh one every call: `users`/`scenarios`
    rows are package-scoped, not truncated per test (`tests.api.conftest`), so a fixed literal
    would collide with whatever an earlier test in this module already created."""
    body: dict[str, Any] = {
        "username": f"e28-{uuid4().hex[:12]}",
        "display_name_ru": "Новый стажёр",
        "user_role": "TRAINEE",
        "password": "a-long-enough-password",
    }
    body.update(overrides)
    return body


async def create_user(
    client: httpx.AsyncClient, token: str, **overrides: Any
) -> tuple[int, dict[str, Any]]:
    response = await client.post(USERS_URL, headers=auth(token), json=_create_body(**overrides))
    return response.status_code, response.json()


async def update_user(
    client: httpx.AsyncClient, token: str, user_id: UserId, **body: Any
) -> tuple[int, dict[str, Any]]:
    response = await client.patch(f"{USERS_URL}/{user_id}", headers=auth(token), json=body)
    return response.status_code, response.json()


async def reset_password(
    client: httpx.AsyncClient, token: str, user_id: UserId, password: str
) -> httpx.Response:
    return await client.post(
        f"{USERS_URL}/{user_id}/password", headers=auth(token), json={"password": password}
    )


async def login_with(client: httpx.AsyncClient, username: str, password: str) -> httpx.Response:
    """Log in with an explicit password — for an account `tests.api.conftest.login` does not
    know (a freshly created one, or one whose password this suite just reset)."""
    return await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


# ---------------------------------------------------------------------------------------------
# Role gate
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("username", ["instructor1", "trainee1"])
async def test_a_non_admin_is_refused_creating_an_account(
    client: httpx.AsyncClient, tokens: dict[str, str], username: str
) -> None:
    status, body = await create_user(client, tokens[username])
    assert status == 403
    assert body["code"] == "FORBIDDEN_FOR_ROLE"


@pytest.mark.parametrize("username", ["instructor1", "trainee1"])
async def test_a_non_admin_is_refused_updating_an_account(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId], username: str
) -> None:
    status, body = await update_user(
        client, tokens[username], users["trainee2"], display_name_ru="Кто-то другой"
    )
    assert status == 403
    assert body["code"] == "FORBIDDEN_FOR_ROLE"


@pytest.mark.parametrize("username", ["instructor1", "trainee1"])
async def test_a_non_admin_is_refused_resetting_a_password(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId], username: str
) -> None:
    response = await reset_password(
        client, tokens[username], users["trainee2"], "another-long-password"
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_no_token_is_401_on_every_operation(
    client: httpx.AsyncClient, users: dict[str, UserId]
) -> None:
    create_response = await client.post(USERS_URL, json=_create_body())
    assert create_response.status_code == 401
    update_response = await client.patch(
        f"{USERS_URL}/{users['trainee1']}", json={"is_active": False}
    )
    assert update_response.status_code == 401


# ---------------------------------------------------------------------------------------------
# `createUser`
# ---------------------------------------------------------------------------------------------


async def test_an_admin_creates_an_account_of_any_role(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    status, body = await create_user(client, tokens["admin1"], user_role="INSTRUCTOR")
    assert status == 201, body
    assert body["user_role"] == "INSTRUCTOR"
    assert body["is_active"] is True
    assert "password" not in body and "password_hash" not in body

    # the account can log in with the password it was created with
    logged_in = await login_with(client, body["username"], "a-long-enough-password")
    assert logged_in.status_code == 200


async def test_an_existing_username_is_409_username_taken(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    status, body = await create_user(client, tokens["admin1"], username="trainee1")
    assert status == 409
    assert body["code"] == "USERNAME_TAKEN"


async def test_a_short_password_is_422_validation_error(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    status, body = await create_user(client, tokens["admin1"], password="short")
    assert status == 422
    assert body["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------------------------
# `updateUser`
# ---------------------------------------------------------------------------------------------


async def test_an_admin_renames_an_account(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    status, body = await update_user(
        client, tokens["admin1"], users["trainee1"], display_name_ru="Переименованный"
    )
    assert status == 200, body
    assert body["display_name_ru"] == "Переименованный"
    assert body["username"] == "trainee1"


async def test_an_unknown_account_is_404(client: httpx.AsyncClient, tokens: dict[str, str]) -> None:
    status, body = await update_user(
        client, tokens["admin1"], UserId("00000000-0000-0000-0000-000000000000"), is_active=False
    )
    assert status == 404
    assert body["code"] == "NOT_FOUND"


async def test_an_empty_body_is_422_validation_error(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    status, body = await update_user(client, tokens["admin1"], users["trainee1"])
    assert status == 422
    assert body["code"] == "VALIDATION_ERROR"


async def test_blocking_a_trainee_refuses_its_live_token_on_the_next_request(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    trainee_token = tokens["trainee1"]
    still_valid = await client.get("/api/v1/auth/me", headers=auth(trainee_token))
    assert still_valid.status_code == 200

    status, body = await update_user(client, tokens["admin1"], users["trainee1"], is_active=False)
    assert status == 200, body
    assert body["is_active"] is False

    refused = await client.get("/api/v1/auth/me", headers=auth(trainee_token))
    assert refused.status_code == 401
    assert refused.json()["code"] == "UNAUTHENTICATED"


async def test_an_admin_cannot_block_its_own_account(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    status, body = await update_user(client, tokens["admin1"], users["admin1"], is_active=False)
    assert status == 409
    assert body["code"] == "SELF_MODIFICATION_FORBIDDEN"


async def test_an_admin_cannot_demote_its_own_account(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    status, body = await update_user(client, tokens["admin1"], users["admin1"], user_role="TRAINEE")
    assert status == 409
    assert body["code"] == "SELF_MODIFICATION_FORBIDDEN"


async def test_blocking_a_second_admin_is_not_a_self_or_last_admin_violation(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    """Two active ADMINs: blocking the *other* one leaves one active — neither guard fires."""
    created_status, created = await create_user(client, tokens["admin1"], user_role="ADMIN")
    assert created_status == 201, created

    status, body = await update_user(
        client, tokens["admin1"], UserId(created["id"]), is_active=False
    )
    assert status == 200, body
    assert body["is_active"] is False


# ---------------------------------------------------------------------------------------------
# `resetUserPassword`
# ---------------------------------------------------------------------------------------------


async def test_an_admin_resets_a_password_and_the_new_one_logs_in(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    response = await reset_password(
        client, tokens["admin1"], users["trainee1"], "a-brand-new-password"
    )
    assert response.status_code == 204
    assert response.content == b""

    logged_in = await login_with(client, "trainee1", "a-brand-new-password")
    assert logged_in.status_code == 200

    old_password_attempt = await login_with(client, "trainee1", "trainee-one-pw")
    assert old_password_attempt.status_code == 401


async def test_a_short_new_password_is_422(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    response = await reset_password(client, tokens["admin1"], users["trainee1"], "short")
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_resetting_an_unknown_account_s_password_is_404(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await reset_password(
        client,
        tokens["admin1"],
        UserId("00000000-0000-0000-0000-000000000000"),
        "a-brand-new-password",
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------------------------
# Audit — one entry per operation (I4 E25)
# ---------------------------------------------------------------------------------------------


async def test_each_write_leaves_exactly_one_audit_entry(
    client: httpx.AsyncClient,
    container: Container,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    before = await container.audit_reader.page(
        AuditFilter(user_id=users["admin1"], action=AuditAction.HTTP_REQUEST, limit=1)
    )
    baseline_total = before.total

    create_status, created = await create_user(client, tokens["admin1"])
    assert create_status == 201, created
    update_status, _ = await update_user(
        client, tokens["admin1"], users["trainee2"], display_name_ru="Аудит"
    )
    assert update_status == 200
    reset_response = await reset_password(
        client, tokens["admin1"], users["trainee2"], "yet-another-long-password"
    )
    assert reset_response.status_code == 204

    after = await container.audit_reader.page(
        AuditFilter(
            user_id=users["admin1"], action=AuditAction.HTTP_REQUEST, limit=baseline_total + 10
        )
    )
    operation_ids = [item.entry.operation_id for item in after.items]
    assert operation_ids.count("createUser") >= 1
    assert operation_ids.count("updateUser") >= 1
    assert operation_ids.count("resetUserPassword") >= 1
    assert after.total == baseline_total + 3
