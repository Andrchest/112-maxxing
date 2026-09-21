"""`SqlAlchemyUserRepository` — the `users` table (HLD §20.2, D8).

Reads and one upsert; there is deliberately no `delete`. An account referenced by a session is
protected by `ON DELETE RESTRICT` on `simulation_sessions.created_by_user_id`,
`session_participants.user_id` and `role_stages.participant_user_id` (§20.3), and the way to
retire an account is `is_active = false`, which `authenticate_token` rejects on the very next
request.

`upsert` keys on `username` (`uq_users_username`), so re-running `app.tools.seed_users` rotates a
password without changing the account's `id` and therefore without orphaning anything that
references it.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.user_repository import StoredUser, UserRole
from app.db.models.reference import User as UserRow
from app.domain.common.ids import UserId

__all__ = ["SqlAlchemyUserRepository"]

_USERS = UserRow.__table__

_COLUMNS = (
    _USERS.c.id,
    _USERS.c.username,
    _USERS.c.display_name_ru,
    _USERS.c.role,
    _USERS.c.is_active,
    _USERS.c.password_hash,
    _USERS.c.created_at,
)


class SqlAlchemyUserRepository:
    """`UserRepository` over PostgreSQL, bound to one `AsyncSession` (one transaction)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId) -> StoredUser | None:
        result = await self._session.execute(
            sa.select(*_COLUMNS).where(_USERS.c.id == UUID(str(user_id)))
        )
        row = result.one_or_none()
        return None if row is None else _stored_user(row)

    async def get_by_username(self, username: str) -> StoredUser | None:
        result = await self._session.execute(
            sa.select(*_COLUMNS).where(_USERS.c.username == username)
        )
        row = result.one_or_none()
        return None if row is None else _stored_user(row)

    async def get_many(self, user_ids: Sequence[UserId]) -> list[StoredUser]:
        ids = [UUID(str(user_id)) for user_id in user_ids]
        if not ids:
            return []
        result = await self._session.execute(
            sa.select(*_COLUMNS).where(_USERS.c.id.in_(ids)).order_by(_USERS.c.username)
        )
        return [_stored_user(row) for row in result.all()]

    async def list_users(
        self, *, role: UserRole | None = None, limit: int, offset: int
    ) -> tuple[list[StoredUser], int]:
        """`listUsers` — active accounts only, `username` order, plus the unpaged total.

        The `is_active` predicate is applied to the count as well as to the page, so a client
        paginating never walks past the end of a total that includes rows it will never be sent.
        """
        criteria = [_USERS.c.is_active.is_(True)]
        if role is not None:
            criteria.append(_USERS.c.role == role.value)

        total_result = await self._session.execute(
            sa.select(sa.func.count()).select_from(_USERS).where(*criteria)
        )
        total = int(total_result.scalar_one())

        result = await self._session.execute(
            sa.select(*_COLUMNS)
            .where(*criteria)
            .order_by(_USERS.c.username)
            .limit(limit)
            .offset(offset)
        )
        return [_stored_user(row) for row in result.all()], total

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
        """`INSERT … ON CONFLICT (username) DO UPDATE` — idempotent, id-preserving."""
        statement = (
            pg_insert(_USERS)
            .values(
                id=UUID(str(user_id)),
                username=username,
                display_name_ru=display_name_ru,
                role=user_role.value,
                password_hash=password_hash,
                is_active=is_active,
            )
            .on_conflict_do_update(
                index_elements=[_USERS.c.username],
                # `id` and `created_at` are deliberately absent: an existing account keeps both.
                set_={
                    "display_name_ru": display_name_ru,
                    "role": user_role.value,
                    "password_hash": password_hash,
                    "is_active": is_active,
                },
            )
            .returning(*_COLUMNS)
        )
        result = await self._session.execute(statement)
        return _stored_user(result.one())


def _stored_user(row: sa.Row[tuple[object, ...]]) -> StoredUser:
    """One `users` row as the application's `StoredUser`."""
    return StoredUser(
        user_id=UserId(UUID(str(row.id))),
        username=str(row.username),
        display_name_ru=str(row.display_name_ru),
        user_role=UserRole(str(row.role)),
        is_active=bool(row.is_active),
        password_hash=str(row.password_hash),
        created_at=row.created_at,
    )
