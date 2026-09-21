"""`Login` — the four readings, and the one thing they must have in common (D8, SPEC §41)."""

from __future__ import annotations

import pytest
from app.application.auth.login import InvalidCredentialsError, Login, LoginCommand
from app.application.ports.user_repository import UserRole
from app.application.testing.fakes import FakePasswordHasher
from app.infrastructure.auth.jwt_token_service import JwtTokenService

from tests.unit.application.auth._fakes import (
    InMemoryUserRepository,
    make_user,
    unit_of_work_factory,
)

SECRET = "unit-test-secret"
PASSWORD = "correct-password"


def build(*, is_active: bool = True, role: UserRole = UserRole.TRAINEE) -> tuple[Login, object]:
    hasher = FakePasswordHasher()
    users = InMemoryUserRepository(
        [
            make_user(
                username="trainee1",
                user_role=role,
                is_active=is_active,
                password_hash=hasher.hash(PASSWORD),
            )
        ]
    )
    login = Login(
        unit_of_work_factory(users),
        hasher,
        JwtTokenService(SECRET, ttl_minutes=60),
    )
    return login, users


async def test_correct_password_mints_a_token_for_the_account() -> None:
    """The token's lifetime is the configured TTL and the result carries the account."""
    login, _ = build(role=UserRole.INSTRUCTOR)

    result = await login(LoginCommand(username="trainee1", password=PASSWORD))

    assert result.user.username == "trainee1"
    assert result.user.user_role is UserRole.INSTRUCTOR
    assert result.token.expires_in == 3600
    assert result.token.access_token.count(".") == 2, "a compact JWS has three segments"


async def test_wrong_password_is_refused() -> None:
    login, _ = build()

    with pytest.raises(InvalidCredentialsError):
        await login(LoginCommand(username="trainee1", password="wrong"))


async def test_unknown_username_is_refused_identically() -> None:
    """The same error type and the same message: no account-enumeration oracle (SPEC §41)."""
    login, _ = build()

    with pytest.raises(InvalidCredentialsError) as unknown:
        await login(LoginCommand(username="nobody", password=PASSWORD))
    with pytest.raises(InvalidCredentialsError) as wrong:
        await login(LoginCommand(username="trainee1", password="wrong"))

    assert str(unknown.value) == str(wrong.value)


async def test_inactive_account_is_refused_even_with_the_right_password() -> None:
    login, _ = build(is_active=False)

    with pytest.raises(InvalidCredentialsError):
        await login(LoginCommand(username="trainee1", password=PASSWORD))


async def test_the_digest_is_verified_even_for_an_unknown_username() -> None:
    """The unknown-username path does the same KDF work, so timing is not an oracle either."""
    hasher = _CountingHasher()
    users = InMemoryUserRepository([make_user(password_hash=hasher.hash(PASSWORD))])
    login = Login(unit_of_work_factory(users), hasher, JwtTokenService(SECRET, ttl_minutes=60))
    hasher.verifications = 0

    with pytest.raises(InvalidCredentialsError):
        await login(LoginCommand(username="nobody", password=PASSWORD))

    assert hasher.verifications == 1


def test_the_command_never_reprs_the_password() -> None:
    """`repr()` of a `LoginCommand` must not print the credential (SPEC §41)."""
    command = LoginCommand(username="trainee1", password="s3cret-do-not-print")

    assert "s3cret-do-not-print" not in repr(command)
    assert "trainee1" in repr(command)


class _CountingHasher(FakePasswordHasher):
    """A `FakePasswordHasher` that counts `verify` calls."""

    def __init__(self) -> None:
        self.verifications = 0

    def verify(self, password_hash: str, password: str) -> bool:
        self.verifications += 1
        return super().verify(password_hash, password)
