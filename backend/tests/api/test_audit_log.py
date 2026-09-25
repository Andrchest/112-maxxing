"""The audit of user actions (I4 E25, `71-i4-wave4.md` §71.2, HLD 20 §20.6 `audit_log`, D31).

Driven against the real application, PostgreSQL and the production audit adapter:

* every operation of `docs/hld/openapi.yaml` except health leaves **exactly one** `audit_log`
  entry, with the contract's operationId and path template — parametrised over the contract the
  same way `test_contract.py` walks it, so an operation added later is covered with no change here;
* a failed login is recorded as `LOGIN_FAILED` with the attempted username and without the
  password; a successful one names the account;
* `401`/`403` are `ACCESS_DENIED` security events; health polls are never recorded;
* the reader pages what the writer wrote (E29's side of the port).

Entries are told apart by id (the rows present before a request are subtracted), because the
database is shared by every test of the worker and the table is append-only by design.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.api.container import Container
from app.application.ports.audit_log import AuditAction, AuditFilter
from app.domain.common.ids import UserId
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api._openapi import load_openapi
from tests.api.conftest import PASSWORDS, auth

pytestmark = pytest.mark.integration

_HEALTH_PREFIX = "/api/v1/health"
_METHODS = ("get", "post", "put", "patch", "delete")
_BODY_METHODS = frozenset({"post", "put", "patch"})
#: A password no fixture uses anywhere, so finding it in a row can only mean it was stored.
_PROBE_PASSWORD = "e25-probe-password-never-stored"


def _contract_operations() -> list[tuple[str, str, str, list[Any]]]:
    """`(path, method, operationId, effective security)` for every non-health operation."""
    document = load_openapi()
    default_security = document.get("security", [])
    operations: list[tuple[str, str, str, list[Any]]] = []
    for path, item in document["paths"].items():
        if path == _HEALTH_PREFIX or path.startswith(_HEALTH_PREFIX + "/"):
            continue
        for method in _METHODS:
            operation = item.get(method)
            if isinstance(operation, Mapping):
                security = operation.get("security", default_security)
                operations.append((path, method, operation["operationId"], security))
    return operations


_OPERATIONS = _contract_operations()


def _concrete(path: str) -> tuple[str, dict[str, str]]:
    """The path with every `{param}` filled — a fresh uuid for an id, a word otherwise."""
    values: dict[str, str] = {}

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        value = str(uuid4()) if name.endswith("_id") else "e25probe"
        values[name] = value
        return value

    return re.sub(r"{(\w+)}", fill, path), values


async def _audit_ids(engine: AsyncEngine) -> set[UUID]:
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT id FROM audit_log"))
        return {row[0] for row in result}


async def _rows_since(engine: AsyncEngine, before: set[UUID]) -> list[dict[str, Any]]:
    """Every entry not in `before`, oldest first, with the whole row as JSON text in `raw`."""
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT a.*, row_to_json(a)::text AS raw FROM audit_log a ORDER BY ts, id")
        )
        return [dict(row._mapping) for row in result if row._mapping["id"] not in before]


def _uses_bearer(security: list[Any]) -> bool:
    return any("bearerAuth" in requirement for requirement in security)


@pytest.mark.parametrize(
    ("path", "method", "operation_id", "security"),
    _OPERATIONS,
    ids=[f"{op_id}" for _, _, op_id, _ in _OPERATIONS],
)
async def test_every_contract_operation_leaves_exactly_one_entry(
    client: httpx.AsyncClient,
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
    path: str,
    method: str,
    operation_id: str,
    security: list[Any],
) -> None:
    """One request per contract operation (as `trainee1`, so nothing privileged runs) → one row.

    The status is whatever the operation answers a probe with (`200`, `403`, `404`, `422`, …); the
    point is that each of them is audited once, under its own operationId and path template.
    """
    url, params = _concrete(path)
    before = await _audit_ids(migrated_engine)

    if operation_id == "loginUser":
        body: Any = {"username": "e25-nobody", "password": _PROBE_PASSWORD}
        response = await client.post(url, json=body)
    else:
        response = await client.request(
            method.upper(),
            url,
            headers=auth(tokens["trainee1"]),
            json={} if method in _BODY_METHODS else None,
        )

    rows = await _rows_since(migrated_engine, before)
    assert len(rows) == 1, (response.status_code, rows)
    row = rows[0]
    assert row["operation_id"] == operation_id
    assert row["path_template"] == path
    assert row["method"] == method.upper()
    assert row["status"] == response.status_code
    assert row["target_ids"] == (
        {"username": "e25-nobody"} if operation_id == "loginUser" else params
    )
    if operation_id != "loginUser" and _uses_bearer(security):
        assert row["user_id"] == users["trainee1"]
        assert row["role"] == "TRAINEE"
    else:
        assert row["user_id"] is None
    expected_action = (
        "LOGIN_FAILED"
        if operation_id == "loginUser"
        else "ACCESS_DENIED"
        if response.status_code in (401, 403)
        else "HTTP_REQUEST"
    )
    assert row["action"] == expected_action
    assert row["client_ip"] == "127.0.0.1"
    assert _PROBE_PASSWORD not in row["raw"]


def test_the_parametrisation_covers_the_whole_contract_but_health() -> None:
    """Guard the generator: nothing is silently dropped, health is the only exclusion."""
    document = load_openapi()
    every = {
        operation["operationId"]
        for item in document["paths"].values()
        for method, operation in item.items()
        if method in _METHODS
    }
    assert {operation_id for _, _, operation_id, _ in _OPERATIONS} == every - {
        "getHealthLive",
        "getHealthReady",
    }


async def test_a_failed_login_is_recorded_without_the_password(
    client: httpx.AsyncClient, migrated_engine: AsyncEngine, users: dict[str, UserId]
) -> None:
    before = await _audit_ids(migrated_engine)
    response = await client.post(
        "/api/v1/auth/login", json={"username": "instructor1", "password": _PROBE_PASSWORD}
    )
    assert response.status_code == 401

    (row,) = await _rows_since(migrated_engine, before)
    assert row["action"] == "LOGIN_FAILED"
    assert row["outcome"] == "DENIED"
    assert row["status"] == 401
    assert row["operation_id"] == "loginUser"
    assert row["user_id"] is None
    assert row["role"] is None
    assert row["target_ids"] == {"username": "instructor1"}
    assert _PROBE_PASSWORD not in row["raw"]
    assert "password" not in json.loads(row["raw"])["target_ids"]


async def test_a_successful_login_names_the_account_and_not_the_password(
    client: httpx.AsyncClient, migrated_engine: AsyncEngine, users: dict[str, UserId]
) -> None:
    before = await _audit_ids(migrated_engine)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "instructor1", "password": PASSWORDS["instructor1"]},
    )
    assert response.status_code == 200

    (row,) = await _rows_since(migrated_engine, before)
    assert row["action"] == "LOGIN_SUCCEEDED"
    assert row["outcome"] == "OK"
    assert row["status"] == 200
    assert row["user_id"] == users["instructor1"]
    assert row["role"] == "INSTRUCTOR"
    assert row["target_ids"] == {"username": "instructor1"}
    assert PASSWORDS["instructor1"] not in row["raw"]
    assert response.json()["access_token"] not in row["raw"]


async def test_an_inactive_account_s_login_is_a_failure_with_no_user(
    client: httpx.AsyncClient, migrated_engine: AsyncEngine, users: dict[str, UserId]
) -> None:
    before = await _audit_ids(migrated_engine)
    response = await client.post(
        "/api/v1/auth/login", json={"username": "retired1", "password": PASSWORDS["retired1"]}
    )
    assert response.status_code == 401
    (row,) = await _rows_since(migrated_engine, before)
    assert (row["action"], row["user_id"]) == ("LOGIN_FAILED", None)
    assert PASSWORDS["retired1"] not in row["raw"]


async def test_no_token_is_an_access_denied_with_no_user(
    client: httpx.AsyncClient, migrated_engine: AsyncEngine
) -> None:
    before = await _audit_ids(migrated_engine)
    response = await client.get("/api/v1/sessions")
    assert response.status_code == 401
    (row,) = await _rows_since(migrated_engine, before)
    assert (row["action"], row["outcome"], row["status"]) == ("ACCESS_DENIED", "DENIED", 401)
    assert row["user_id"] is None
    assert row["operation_id"] == "listSessions"


async def test_a_role_refusal_is_an_access_denied_that_names_the_caller(
    client: httpx.AsyncClient,
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    before = await _audit_ids(migrated_engine)
    response = await client.post(
        "/api/v1/admin/recordings/purge",
        headers=auth(tokens["trainee1"]),
        json={"dry_run": True},
    )
    assert response.status_code == 403
    (row,) = await _rows_since(migrated_engine, before)
    assert (row["action"], row["outcome"], row["status"]) == ("ACCESS_DENIED", "DENIED", 403)
    assert (row["user_id"], row["role"]) == (users["trainee1"], "TRAINEE")
    assert row["operation_id"] == "purgeRecordings"


async def test_a_successful_request_is_ok_and_names_the_caller(
    client: httpx.AsyncClient,
    migrated_engine: AsyncEngine,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    before = await _audit_ids(migrated_engine)
    response = await client.get("/api/v1/auth/me", headers=auth(tokens["admin1"]))
    assert response.status_code == 200
    (row,) = await _rows_since(migrated_engine, before)
    assert (row["action"], row["outcome"], row["status"]) == ("HTTP_REQUEST", "OK", 200)
    assert (row["user_id"], row["role"]) == (users["admin1"], "ADMIN")
    assert (row["operation_id"], row["path_template"]) == ("getCurrentUser", "/api/v1/auth/me")
    assert row["target_ids"] == {}


async def test_a_client_error_is_an_error_outcome(
    client: httpx.AsyncClient, migrated_engine: AsyncEngine, tokens: dict[str, str]
) -> None:
    before = await _audit_ids(migrated_engine)
    unknown = uuid4()
    response = await client.get(f"/api/v1/sessions/{unknown}", headers=auth(tokens["admin1"]))
    assert response.status_code == 404
    (row,) = await _rows_since(migrated_engine, before)
    assert (row["action"], row["outcome"], row["status"]) == ("HTTP_REQUEST", "ERROR", 404)
    assert row["path_template"] == "/api/v1/sessions/{session_id}"
    assert row["target_ids"] == {"session_id": str(unknown)}


@pytest.mark.parametrize("path", ["/api/v1/health/live", "/api/v1/health/ready"])
async def test_health_polls_are_never_recorded(
    client: httpx.AsyncClient, migrated_engine: AsyncEngine, path: str
) -> None:
    before = await _audit_ids(migrated_engine)
    for _ in range(3):
        await client.get(path)
    assert await _rows_since(migrated_engine, before) == []


async def test_a_path_outside_the_contract_is_recorded_as_sent(
    client: httpx.AsyncClient, migrated_engine: AsyncEngine
) -> None:
    before = await _audit_ids(migrated_engine)
    response = await client.get("/api/v1/no-such-thing?token=abc")
    assert response.status_code == 404
    (row,) = await _rows_since(migrated_engine, before)
    assert row["path_template"] == "/api/v1/no-such-thing"  # never the query string
    assert row["operation_id"] is None
    assert "abc" not in row["raw"]


async def test_the_reader_pages_what_the_writer_wrote(
    client: httpx.AsyncClient,
    container: Container,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    """`AuditReader.page` (E29's read side): newest first, filtered by user and action."""
    for _ in range(3):
        await client.get("/api/v1/auth/me", headers=auth(tokens["trainee2"]))
    page = await container.audit_reader.page(
        AuditFilter(user_id=users["trainee2"], action=AuditAction.HTTP_REQUEST, limit=2)
    )
    assert page.total >= 3
    assert len(page.items) == 2
    assert all(item.entry.user_id == users["trainee2"] for item in page.items)
    assert page.items[0].entry.ts >= page.items[1].entry.ts
    assert page.items[0].entry.operation_id == "getCurrentUser"
