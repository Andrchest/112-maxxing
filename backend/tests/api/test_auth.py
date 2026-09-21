"""`loginUser` / `getCurrentUser` and the role gate, through HTTP (D8, SPEC §41)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.api.container import Container
from app.api.main import create_app
from app.application.ports.user_repository import UserRole
from app.domain.common.ids import UserId
from app.infrastructure.auth.argon2_hasher import Argon2PasswordHasher
from app.infrastructure.auth.jwt_token_service import JwtTokenService

from tests.api.conftest import PASSWORDS, auth

pytestmark = pytest.mark.integration


async def test_login_returns_a_token_and_the_account(
    client: httpx.AsyncClient, users: dict[str, UserId]
) -> None:
    """A correct password answers `200 TokenResponse` — and never echoes the digest."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "instructor1", "password": PASSWORDS["instructor1"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["access_token"]
    assert body["user"]["username"] == "instructor1"
    assert body["user"]["user_role"] == "INSTRUCTOR"
    assert "password_hash" not in body["user"]
    assert "is_active" not in body["user"]


async def test_wrong_password_is_401_problem_json(
    client: httpx.AsyncClient, users: dict[str, UserId]
) -> None:
    """A wrong password is `401 UNAUTHENTICATED` as `application/problem+json`."""
    response = await client.post(
        "/api/v1/auth/login", json={"username": "trainee1", "password": "not-the-password"}
    )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "UNAUTHENTICATED"
    assert body["status"] == 401
    assert set(body) >= {"type", "title", "status", "detail", "instance", "code"}


async def test_unknown_user_is_indistinguishable_from_a_wrong_password(
    client: httpx.AsyncClient, users: dict[str, UserId]
) -> None:
    """An unknown username must not be an account-enumeration oracle (SPEC §41)."""
    unknown = await client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "whatever"}
    )
    wrong = await client.post(
        "/api/v1/auth/login", json={"username": "trainee1", "password": "whatever"}
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


async def test_inactive_account_cannot_log_in(
    client: httpx.AsyncClient, users: dict[str, UserId]
) -> None:
    """`is_active = false` refuses the login even with the right password."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "retired1", "password": PASSWORDS["retired1"]},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_missing_authorization_header_is_401(client: httpx.AsyncClient) -> None:
    """No bearer token is our problem+json, not Starlette's plain JSON."""
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_malformed_token_is_401(client: httpx.AsyncClient, users: dict[str, UserId]) -> None:
    """A token that is not a JWT at all is the same single `401`."""
    response = await client.get("/api/v1/auth/me", headers=auth("not-a-jwt"))

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_expired_token_is_401(container: Container, users: dict[str, UserId]) -> None:
    """A token whose `exp` has passed is refused.

    The token is minted by a `JwtTokenService` with a **negative** TTL — the same secret and the
    same algorithm as the app's, so what is tested is expiry and nothing else.
    """
    expired_service = JwtTokenService(container.settings.jwt_secret, ttl_minutes=-1)
    token = expired_service.issue(users["trainee1"], UserRole.TRAINEE)
    assert token.access_token

    transport = httpx.ASGITransport(app=create_app(container))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        response = await client.get("/api/v1/auth/me", headers=auth(token.access_token))

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_token_signed_with_another_secret_is_401(
    container: Container, users: dict[str, UserId]
) -> None:
    """A valid-looking token signed with a different secret is refused."""
    foreign = JwtTokenService("a-completely-different-secret", ttl_minutes=60)
    token = foreign.issue(users["trainee1"], UserRole.TRAINEE)

    transport = httpx.ASGITransport(app=create_app(container))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        response = await client.get("/api/v1/auth/me", headers=auth(token.access_token))

    assert response.status_code == 401


async def test_me_returns_the_account(client: httpx.AsyncClient, tokens: dict[str, str]) -> None:
    """`getCurrentUser` answers the `UserAccount` of the token's subject."""
    response = await client.get("/api/v1/auth/me", headers=auth(tokens["trainee1"]))

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "trainee1"
    assert body["user_role"] == "TRAINEE"
    assert datetime.fromisoformat(body["created_at"]) <= datetime.now(UTC) + timedelta(minutes=1)


async def test_role_gate_refuses_a_trainee_with_403(
    client: httpx.AsyncClient, tokens: dict[str, str], demo_yaml: str
) -> None:
    """`importScenarioVersion` is INSTRUCTOR/ADMIN: a trainee gets `403 FORBIDDEN_FOR_ROLE`."""
    response = await client.post(
        "/api/v1/scenarios/import",
        headers=auth(tokens["trainee1"]),
        json={"format": "YAML", "content": demo_yaml},
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_role_gate_admits_an_admin(
    client: httpx.AsyncClient, tokens: dict[str, str], demo_yaml: str
) -> None:
    """The same gate admits an `ADMIN` — the gate is a role set, not an instructor check."""
    response = await client.post(
        "/api/v1/scenarios/validate",
        headers=auth(tokens["admin1"]),
        json={"format": "YAML", "content": demo_yaml},
    )

    assert response.status_code == 200


def test_argon2_hasher_round_trips() -> None:
    """The real `PasswordHasher` adapter: a match verifies, everything else is `False`.

    The API tests use `FakePasswordHasher` for speed, so this is where argon2 itself is exercised.
    """
    hasher = Argon2PasswordHasher()
    digest = hasher.hash("correct horse battery staple")

    assert digest != "correct horse battery staple"
    assert hasher.verify(digest, "correct horse battery staple")
    assert not hasher.verify(digest, "wrong")
    assert not hasher.verify("not-a-digest", "correct horse battery staple")
