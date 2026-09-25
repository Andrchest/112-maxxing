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
    _USERS.c.sip_ha1,
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
        self,
        *,
        role: UserRole | None = None,
        limit: int,
        offset: int,
        include_inactive: bool = False,
    ) -> tuple[list[StoredUser], int]:
        """`listUsers` — active-only by default, `username` order, plus the unpaged total.

        The `is_active` predicate (when applied) covers the count as well as the page, so a client
        paginating never walks past the end of a total that includes rows it will never be sent.
        """
        criteria = [] if include_inactive else [_USERS.c.is_active.is_(True)]
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

    async def set_sip_ha1(self, username: str, sip_ha1: str | None) -> bool:
        """`UPDATE users SET sip_ha1 = …` for one username (I3 E6e); `False` if there is none."""
        result = await self._session.execute(
            sa.update(_USERS)
            .where(_USERS.c.username == username)
            .values(sip_ha1=sip_ha1)
            .returning(_USERS.c.id)
        )
        return result.first() is not None

    # --- I4 E28 accounts (`71-i4-wave4.md` §71.5) ----------------------------------------------

    async def create(
        self,
        *,
        user_id: UserId,
        username: str,
        display_name_ru: str,
        user_role: UserRole,
        password_hash: str,
    ) -> StoredUser:
        """A plain `INSERT` (not `upsert`'s `ON CONFLICT`) — a duplicate username is the
        database's own `uq_users_username` violation, not a silent overwrite."""
        statement = (
            sa.insert(_USERS)
            .values(
                id=UUID(str(user_id)),
                username=username,
                display_name_ru=display_name_ru,
                role=user_role.value,
                password_hash=password_hash,
            )
            .returning(*_COLUMNS)
        )
        result = await self._session.execute(statement)
        return _stored_user(result.one())

    async def update(
        self,
        user_id: UserId,
        *,
        display_name_ru: str | None = None,
        user_role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> StoredUser | None:
        """Patch only the columns given; no field given is a plain re-read, not a no-op UPDATE."""
        values: dict[str, object] = {}
        if display_name_ru is not None:
            values["display_name_ru"] = display_name_ru
        if user_role is not None:
            values["role"] = user_role.value
        if is_active is not None:
            values["is_active"] = is_active
        if not values:
            return await self.get(user_id)
        result = await self._session.execute(
            sa.update(_USERS)
            .where(_USERS.c.id == UUID(str(user_id)))
            .values(**values)
            .returning(*_COLUMNS)
        )
        row = result.one_or_none()
        return None if row is None else _stored_user(row)

    async def set_password_hash(self, user_id: UserId, password_hash: str) -> bool:
        result = await self._session.execute(
            sa.update(_USERS)
            .where(_USERS.c.id == UUID(str(user_id)))
            .values(password_hash=password_hash)
            .returning(_USERS.c.id)
        )
        return result.first() is not None

    async def count_active(self, user_role: UserRole) -> int:
        result = await self._session.execute(
            sa.select(sa.func.count())
            .select_from(_USERS)
            .where(_USERS.c.role == user_role.value, _USERS.c.is_active.is_(True))
        )
        return int(result.scalar_one())

    # --- end I4 E28 -----------------------------------------------------------------------------


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
        sip_ha1=None if row.sip_ha1 is None else str(row.sip_ha1),
    )
