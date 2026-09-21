"""`authenticate_token` — the function E7-C's WebSocket will call with `?token=…` (D8).

It is deliberately not a FastAPI dependency, so these tests exercise it directly, exactly as the
socket handler will.
"""

from __future__ import annotations

import pytest
from app.application.auth.get_current_user import authenticate_token
from app.application.ports.token_service import InvalidTokenError
from app.application.ports.user_repository import UserRole
from app.infrastructure.auth.jwt_token_service import JwtTokenService

from tests.unit.application.auth._fakes import (
    InMemoryUserRepository,
    make_user,
    unit_of_work_factory,
)

SECRET = "unit-test-secret"


def tokens(ttl_minutes: int = 60, secret: str = SECRET) -> JwtTokenService:
    return JwtTokenService(secret, ttl_minutes=ttl_minutes)


async def test_a_valid_token_resolves_to_the_account() -> None:
    user = make_user(username="instructor1", user_role=UserRole.INSTRUCTOR)
    users = InMemoryUserRepository([user])
    service = tokens()
    issued = service.issue(user.user_id, user.user_role)

    resolved = await authenticate_token(
        issued.access_token, tokens=service, unit_of_work=unit_of_work_factory(users)
    )

    assert resolved.user_id == user.user_id
    assert resolved.username == "instructor1"
    assert resolved.user_role is UserRole.INSTRUCTOR
    assert resolved.is_instructor_or_admin


async def test_the_persisted_role_wins_over_the_claim() -> None:
    """A token minted before a demotion must not outlive it (D8).

    The token is issued while the account is an `INSTRUCTOR`; the account is then demoted. The
    resolved user is a `TRAINEE`, because the persisted role is the authoritative one.
    """
    user = make_user(username="demoted", user_role=UserRole.INSTRUCTOR)
    users = InMemoryUserRepository([user])
    service = tokens()
    issued = service.issue(user.user_id, UserRole.INSTRUCTOR)

    users.add(user.model_copy(update={"user_role": UserRole.TRAINEE}))
    resolved = await authenticate_token(
        issued.access_token, tokens=service, unit_of_work=unit_of_work_factory(users)
    )

    assert resolved.user_role is UserRole.TRAINEE
    assert not resolved.is_instructor_or_admin


async def test_a_deactivated_account_is_refused_immediately() -> None:
    """Deactivation takes effect on the next request, not at the token's next expiry."""
    user = make_user(username="retired")
    users = InMemoryUserRepository([user])
    service = tokens()
    issued = service.issue(user.user_id, user.user_role)

    users.add(user.model_copy(update={"is_active": False}))

    with pytest.raises(InvalidTokenError):
        await authenticate_token(
            issued.access_token, tokens=service, unit_of_work=unit_of_work_factory(users)
        )


async def test_a_token_for_an_unknown_account_is_refused() -> None:
    user = make_user()
    service = tokens()
    issued = service.issue(user.user_id, user.user_role)

    with pytest.raises(InvalidTokenError):
        await authenticate_token(
            issued.access_token,
            tokens=service,
            unit_of_work=unit_of_work_factory(InMemoryUserRepository()),
        )


async def test_expired_malformed_and_foreign_tokens_are_the_same_error() -> None:
    """One `InvalidTokenError` for every unusable token — `openapi.yaml` has one `401`."""
    user = make_user()
    users = InMemoryUserRepository([user])
    service = tokens()

    expired = tokens(ttl_minutes=-1).issue(user.user_id, user.user_role).access_token
    foreign = tokens(secret="another-secret").issue(user.user_id, user.user_role).access_token

    for token in (expired, foreign, "not-a-jwt", "", "a.b.c"):
        with pytest.raises(InvalidTokenError):
            await authenticate_token(
                token, tokens=service, unit_of_work=unit_of_work_factory(users)
            )


def test_an_empty_secret_is_refused_at_construction() -> None:
    """A token signed with no secret is not a token (SPEC §41)."""
    with pytest.raises(ValueError, match="SIM_JWT_SECRET"):
        JwtTokenService("", ttl_minutes=60)


def test_the_issued_token_is_not_in_its_repr() -> None:
    """`repr()` of an `IssuedToken` must not print the credential (SPEC §41)."""
    user = make_user()
    issued = tokens().issue(user.user_id, user.user_role)

    assert issued.access_token not in repr(issued)
    assert "expires_in" in repr(issued)
