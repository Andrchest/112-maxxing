"""`GET /api/v1/users` — `listUsers` (`openapi.yaml`, additive E7, D8, SPEC §41; CHANGED I4 E28).

The operation exists so that an instructor building a session can pick its participants, and
everything asserted here follows from that one sentence:

* it is INSTRUCTOR / ADMIN only — a trainee enumerating the other trainees is not part of the
  product, and `openapi.yaml` gives the operation a `403`;
* it never carries the digest. `UserAccountI4` (I4 E28) has no `password_hash`, and the assertion
  below is on the **exact property set** of every item, not on the absence of one name, so a field
  added to `StoredUser` later cannot leak through this endpoint unnoticed;
* by default, a deactivated account is not offered as a participant, because it cannot be one — it
  is refused on its very next request (`authenticate_token`). I4 E28's `include_inactive` (ADMIN
  only) is the one way to see it anyway — see `tests/api/admin/test_users.py` for that half.

`retired1` in `tests/api/conftest.py`'s five seeded accounts is the deactivated one; it is a
`TRAINEE`, so it also proves the `is_active` predicate is applied to the role filter and to the
unpaged `total`, not only to the page.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.domain.common.ids import UserId
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
async def _clean_roster_for_the_exact_counts_below(migrated_engine: AsyncEngine) -> None:
    """I7 E49: this module's assertions are exact (`total == 4`, an exact username list) and hold
    only for the five accounts `tests.api.conftest.users` seeds — but `users`/`scenarios` are this
    whole `tests.api` package's reference data, upserted (never truncated) per test (E9-0), so a
    module that ran earlier in the same process and created its OWN real, ACTIVE accounts (e.g.
    `tests/api/admin/test_users.py`'s `createUser`, one per call, on purpose unique per the E28
    isolation note in its own `_create_body`) leaves them for every module that runs after it to
    count and list. `TRUNCATE ... CASCADE` also clears `audit_log` (each `createUser` leaves one
    entry, `ON DELETE RESTRICT`) and every per-session table (already empty here either way,
    `clean_database` truncates those per test). Once, before this module's first test: the `users`
    fixture's `ON CONFLICT DO UPDATE` upsert (its own docstring) re-creates the five canonical
    accounts on that very first test and every one after, so nothing is missing once this runs.

    Proof this was the actual failure (not a coincidence of run order): `pytest
    backend/tests/api/admin backend/tests/api/test_users.py -p no:randomly -n 0` — 9 failed before
    this fixture, all pass with it.
    """
    async with migrated_engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


USERS_URL = "/api/v1/users"

#: `openapi.yaml`'s `UserAccountI4.required` (I4 E28) — `additionalProperties: false`, so this is
#: the whole object. Never `password_hash`.
USER_ACCOUNT_PROPERTIES = {
    "id",
    "username",
    "display_name_ru",
    "user_role",
    "created_at",
    "is_active",
}

#: The four active accounts of `tests/api/conftest.py`, in `username` order. `retired1` is absent.
ACTIVE_USERNAMES = ["admin1", "instructor1", "trainee1", "trainee2"]


async def list_users(
    client: httpx.AsyncClient, token: str, **params: Any
) -> tuple[int, dict[str, Any]]:
    """`listUsers` over HTTP; the status and the parsed body."""
    response = await client.get(USERS_URL, headers=auth(token), params=params)
    body: dict[str, Any] = response.json()
    return response.status_code, body


# ---------------------------------------------------------------------------------------------
# Who may call it
# ---------------------------------------------------------------------------------------------


async def test_a_trainee_is_refused_with_forbidden_for_role(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """`openapi.yaml`: "INSTRUCTOR / ADMIN only" — D8's account gate, `403 FORBIDDEN_FOR_ROLE`."""
    status, body = await list_users(client, tokens["trainee1"])
    assert status == 403
    assert body["code"] == "FORBIDDEN_FOR_ROLE"
    assert "items" not in body, "a refused caller learns nothing about the accounts"


async def test_an_instructor_and_an_admin_are_both_admitted(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    for username in ("instructor1", "admin1"):
        status, body = await list_users(client, tokens[username])
        assert status == 200, (username, body)
        assert [item["username"] for item in body["items"]] == ACTIVE_USERNAMES


async def test_no_token_is_401(client: httpx.AsyncClient, users: dict[str, UserId]) -> None:
    response = await client.get(USERS_URL)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


# ---------------------------------------------------------------------------------------------
# What it answers
# ---------------------------------------------------------------------------------------------


async def test_the_page_is_the_active_accounts_in_username_order(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    status, body = await list_users(client, tokens["instructor1"])
    assert status == 200
    assert [item["username"] for item in body["items"]] == ACTIVE_USERNAMES
    assert body["total"] == len(ACTIVE_USERNAMES)


async def test_a_deactivated_account_is_not_listed_at_all(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """`retired1` is `is_active = false`; `UserAccount` cannot say so, so it is excluded."""
    _, body = await list_users(client, tokens["instructor1"])
    assert "retired1" not in [item["username"] for item in body["items"]]
    assert body["total"] == 4, "the unpaged total counts only what may be returned"


async def test_no_item_carries_a_credential_or_any_other_property(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """SPEC §41: the digest never leaves the application layer (an exact property-set check)."""
    _, body = await list_users(client, tokens["instructor1"])
    assert body["items"]
    for item in body["items"]:
        assert set(item) == USER_ACCOUNT_PROPERTIES, item


async def test_it_returns_getcurrentuser_s_shape_plus_is_active(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """`UserAccountI4` (I4 E28) is `UserAccount` plus `is_active` — asserted against `/auth/me`."""
    me = await client.get("/api/v1/auth/me", headers=auth(tokens["instructor1"]))
    assert me.status_code == 200
    _, body = await list_users(client, tokens["instructor1"])
    listed = next(item for item in body["items"] if item["username"] == "instructor1")
    assert listed == {**me.json(), "is_active": True}


# ---------------------------------------------------------------------------------------------
# The `role` filter
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("TRAINEE", ["trainee1", "trainee2"]),
        ("INSTRUCTOR", ["instructor1"]),
        ("ADMIN", ["admin1"]),
    ],
)
async def test_the_role_filter_selects_that_account_role_only(
    client: httpx.AsyncClient, tokens: dict[str, str], role: str, expected: list[str]
) -> None:
    """`retired1` is a `TRAINEE`, so the `TRAINEE` row also proves the filter stays active-only."""
    status, body = await list_users(client, tokens["instructor1"], role=role)
    assert status == 200
    assert [item["username"] for item in body["items"]] == expected
    assert body["total"] == len(expected)
    assert {item["user_role"] for item in body["items"]} == {role}


async def test_an_unknown_role_is_a_validation_error(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """`role` is `openapi.yaml`'s `UserRole` enum, not a free string."""
    status, body = await list_users(client, tokens["instructor1"], role="OPERATOR_112")
    assert status == 422
    assert body["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------------------------


async def test_limit_and_offset_page_over_a_stable_order(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """`total` is the unpaged count — what a paginating client needs to know how far to go."""
    seen: list[str] = []
    for offset in (0, 2):
        status, body = await list_users(client, tokens["instructor1"], limit=2, offset=offset)
        assert status == 200
        assert body["total"] == 4, "the total is not len(items)"
        assert len(body["items"]) == 2
        seen.extend(item["username"] for item in body["items"])
    assert seen == ACTIVE_USERNAMES


async def test_an_offset_past_the_end_is_an_empty_page_not_an_error(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    status, body = await list_users(client, tokens["instructor1"], offset=100)
    assert status == 200
    assert body["items"] == []
    assert body["total"] == 4


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_out_of_range_pagination_is_422(
    client: httpx.AsyncClient, tokens: dict[str, str], params: dict[str, int]
) -> None:
    """The bounds are `openapi.yaml`'s: `limit` 1-200, `offset` >= 0."""
    status, _body = await list_users(client, tokens["instructor1"], **params)
    assert status == 422


# ---------------------------------------------------------------------------------------------
# `include_inactive` (I4 E28, ADMIN only, §71.5)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "false"])
async def test_an_instructor_passing_include_inactive_at_all_is_refused(
    client: httpx.AsyncClient, tokens: dict[str, str], value: str
) -> None:
    """ "An INSTRUCTOR passing it gets `403`" — any value, not only `true` (§71.5)."""
    status, body = await list_users(client, tokens["instructor1"], include_inactive=value)
    assert status == 403
    assert body["code"] == "FORBIDDEN_FOR_ROLE"


async def test_an_admin_without_include_inactive_still_sees_only_active_accounts(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    status, body = await list_users(client, tokens["admin1"])
    assert status == 200
    assert "retired1" not in [item["username"] for item in body["items"]]
    assert body["total"] == 4


async def test_an_admin_with_include_inactive_sees_the_whole_roster(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    status, body = await list_users(client, tokens["admin1"], include_inactive="true")
    assert status == 200
    by_username = {item["username"]: item for item in body["items"]}
    assert set(by_username) == {"admin1", "instructor1", "trainee1", "trainee2", "retired1"}
    assert body["total"] == 5
    assert by_username["retired1"]["is_active"] is False
    assert by_username["admin1"]["is_active"] is True
