"""In-memory `UserRepository` and `UnitOfWork` for the accounts use-case unit tests (I4 E28).

Same pattern as `tests.unit.application.auth._fakes`, extended with the four I4 E28 primitives
(`create`, `update`, `set_password_hash`, `count_active`) so `CreateUser`/`UpdateUser`/
`SetActive`/`ResetPassword` can be tested without PostgreSQL.
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
    """A `UserRepository` over a dict keyed by user id."""

    def __init__(self, users: Sequence[StoredUser] = ()) -> None:
        self.by_id: dict[UserId, StoredUser] = {user.user_id: user for user in users}

    async def get(self, user_id: UserId) -> StoredUser | None:
        return self.by_id.get(user_id)

    async def get_by_username(self, username: str) -> StoredUser | None:
        for user in self.by_id.values():
            if user.username == username:
                return user
        return None

    async def get_many(self, user_ids: Sequence[UserId]) -> list[StoredUser]:
        wanted = set(user_ids)
        return sorted(
            (user for user in self.by_id.values() if user.user_id in wanted),
            key=lambda user: user.username,
        )

    async def list_users(
        self,
        *,
        role: UserRole | None = None,
        limit: int,
        offset: int,
        include_inactive: bool = False,
    ) -> tuple[list[StoredUser], int]:
        matching = [
            user
            for user in self.by_id.values()
            if (include_inactive or user.is_active) and (role is None or user.user_role is role)
        ]
        matching.sort(key=lambda user: user.username)
        return matching[offset : offset + limit], len(matching)

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
        existing = await self.get_by_username(username)
        resolved_id = existing.user_id if existing is not None else user_id
        return self._put(
            make_user(
                user_id=resolved_id,
                username=username,
                display_name_ru=display_name_ru,
                user_role=user_role,
                password_hash=password_hash,
                is_active=is_active,
            )
        )

    async def set_sip_ha1(self, username: str, sip_ha1: str | None) -> bool:
        existing = await self.get_by_username(username)
        if existing is None:
            return False
        self._put(existing.model_copy(update={"sip_ha1": sip_ha1}))
        return True

    # --- I4 E28 ---------------------------------------------------------------------------------

    async def create(
        self,
        *,
        user_id: UserId,
        username: str,
        display_name_ru: str,
        user_role: UserRole,
        password_hash: str,
    ) -> StoredUser:
        return self._put(
            make_user(
                user_id=user_id,
                username=username,
                display_name_ru=display_name_ru,
                user_role=user_role,
                password_hash=password_hash,
            )
        )

    async def update(
        self,
        user_id: UserId,
        *,
        display_name_ru: str | None = None,
        user_role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> StoredUser | None:
        existing = self.by_id.get(user_id)
        if existing is None:
            return None
        updates: dict[str, Any] = {}
        if display_name_ru is not None:
            updates["display_name_ru"] = display_name_ru
        if user_role is not None:
            updates["user_role"] = user_role
        if is_active is not None:
            updates["is_active"] = is_active
        return self._put(existing.model_copy(update=updates))

    async def set_password_hash(self, user_id: UserId, password_hash: str) -> bool:
        existing = self.by_id.get(user_id)
        if existing is None:
            return False
        self._put(existing.model_copy(update={"password_hash": password_hash}))
        return True

    async def count_active(self, user_role: UserRole) -> int:
        return sum(
            1 for user in self.by_id.values() if user.is_active and user.user_role is user_role
        )

    def _put(self, user: StoredUser) -> StoredUser:
        self.by_id[user.user_id] = user
        return user


class FakeUnitOfWork:
    """The smallest object satisfying the `UnitOfWork` port for an accounts test."""

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
        raise AttributeError(f"an accounts test must not reach uow.{name}")


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
