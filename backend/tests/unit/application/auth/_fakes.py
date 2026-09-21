"""In-memory `UserRepository` and `UnitOfWork` for the auth use-case unit tests.

These tests are about the *decisions* `Login` and `authenticate_token` make — which rejections
look alike, whose role wins, when an inactive account stops being usable — and none of those
decisions involve PostgreSQL. The Unit of Work here is therefore the smallest object that satisfies
the port: it hands out the user repository and records whether it was committed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import uuid4

from app.application.ports.user_repository import StoredUser, UserRole
from app.domain.common.ids import UserId


class InMemoryUserRepository:
    """A `UserRepository` over a dict keyed by username."""

    def __init__(self, users: Sequence[StoredUser] = ()) -> None:
        self.by_username: dict[str, StoredUser] = {user.username: user for user in users}

    def add(self, user: StoredUser) -> StoredUser:
        """Store one account and return it."""
        self.by_username[user.username] = user
        return user

    async def get(self, user_id: UserId) -> StoredUser | None:
        for user in self.by_username.values():
            if user.user_id == user_id:
                return user
        return None

    async def get_by_username(self, username: str) -> StoredUser | None:
        return self.by_username.get(username)

    async def get_many(self, user_ids: Sequence[UserId]) -> list[StoredUser]:
        wanted = set(user_ids)
        return sorted(
            (user for user in self.by_username.values() if user.user_id in wanted),
            key=lambda user: user.username,
        )

    async def upsert(
        self,
        *,
        user_id: UserId,
        username: str,
        display_name_ru: str,
        user_role: UserRole,
        password_hash: str,
        is_active: bool = True,
    ) -> StoredUser:
        existing = self.by_username.get(username)
        return self.add(
            make_user(
                username=username,
                display_name_ru=display_name_ru,
                user_role=user_role,
                password_hash=password_hash,
                is_active=is_active,
                user_id=existing.user_id if existing is not None else user_id,
            )
        )


class FakeUnitOfWork:
    """The smallest object satisfying the `UnitOfWork` port for an auth test."""

    def __init__(self, users: InMemoryUserRepository) -> None:
        self._users = users
        self.commits = 0

    @property
    def users(self) -> InMemoryUserRepository:
        return self._users

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - no other repository is touched
        raise AttributeError(f"an auth test must not reach uow.{name}")


def unit_of_work_factory(users: InMemoryUserRepository) -> Any:
    """A `UnitOfWorkFactory` handing out fresh `FakeUnitOfWork`s over one repository."""

    def factory() -> FakeUnitOfWork:
        return FakeUnitOfWork(users)

    return factory


def make_user(
    *,
    username: str = "trainee1",
    display_name_ru: str = "Стажёр",
    user_role: UserRole = UserRole.TRAINEE,
    password_hash: str = "fake$pw",
    is_active: bool = True,
    user_id: UserId | None = None,
) -> StoredUser:
    """One `StoredUser` with test-only values."""
    return StoredUser(
        user_id=user_id if user_id is not None else UserId(uuid4()),
        username=username,
        display_name_ru=display_name_ru,
        user_role=user_role,
        is_active=is_active,
        password_hash=password_hash,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
