"""`SqlAlchemyTraineeGroupRepository` — `trainee_groups` and `trainee_group_members` (HLD 20 §20.2,
HLD 70 §70.3.7, I3 E9a, migration `0013_trainee_groups`).

A group and its member list are read and written whole. Members come back in `username` order
(joined with `users`), the order every picker shows them in. Deleting a group cascades to its
member rows and sets `lessons.group_id` to `NULL` (`ON DELETE SET NULL`): a lesson keeps its own
`participants`, so nothing it scheduled changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.trainee_group_repository import StoredTraineeGroup
from app.db.models.reference import TraineeGroup as GroupRow
from app.db.models.reference import TraineeGroupMember as MemberRow
from app.db.models.reference import User as UserRow
from app.domain.common.ids import TraineeGroupId, UserId

__all__ = ["SqlAlchemyTraineeGroupRepository"]

_GROUPS = GroupRow.__table__
_MEMBERS = MemberRow.__table__
_USERS = UserRow.__table__


class SqlAlchemyTraineeGroupRepository:
    """`TraineeGroupRepository` over PostgreSQL, bound to one `AsyncSession` (one transaction)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, group: StoredTraineeGroup) -> None:
        await self._session.execute(
            sa.insert(_GROUPS).values(
                id=UUID(str(group.group_id)),
                name_ru=group.name_ru,
                created_by_user_id=UUID(str(group.created_by_user_id)),
                created_at=group.created_at,
            )
        )
        await self._insert_members(group.group_id, group.member_user_ids)

    async def get(self, group_id: TraineeGroupId) -> StoredTraineeGroup | None:
        result = await self._session.execute(
            sa.select(_GROUPS).where(_GROUPS.c.id == UUID(str(group_id)))
        )
        row = result.one_or_none()
        if row is None:
            return None
        members = await self._members([row.id])
        return _stored(row, members.get(row.id, ()))

    async def list_groups(self, *, limit: int, offset: int) -> tuple[list[StoredTraineeGroup], int]:
        total = int(
            (
                await self._session.execute(sa.select(sa.func.count()).select_from(_GROUPS))
            ).scalar_one()
        )
        result = await self._session.execute(
            sa.select(_GROUPS).order_by(_GROUPS.c.name_ru, _GROUPS.c.id).limit(limit).offset(offset)
        )
        rows = result.all()
        members = await self._members([row.id for row in rows])
        return [_stored(row, members.get(row.id, ())) for row in rows], total

    async def replace(
        self, group_id: TraineeGroupId, *, name_ru: str, member_user_ids: Sequence[UserId]
    ) -> None:
        group = UUID(str(group_id))
        await self._session.execute(
            sa.update(_GROUPS).where(_GROUPS.c.id == group).values(name_ru=name_ru)
        )
        await self._session.execute(sa.delete(_MEMBERS).where(_MEMBERS.c.group_id == group))
        await self._insert_members(group_id, member_user_ids)

    async def delete(self, group_id: TraineeGroupId) -> None:
        await self._session.execute(sa.delete(_GROUPS).where(_GROUPS.c.id == UUID(str(group_id))))

    async def _insert_members(
        self, group_id: TraineeGroupId, member_user_ids: Sequence[UserId]
    ) -> None:
        unique = list(dict.fromkeys(UUID(str(user_id)) for user_id in member_user_ids))
        if not unique:
            return
        await self._session.execute(
            sa.insert(_MEMBERS),
            [{"group_id": UUID(str(group_id)), "user_id": user_id} for user_id in unique],
        )

    async def _members(self, group_ids: Sequence[UUID]) -> dict[UUID, tuple[UserId, ...]]:
        if not group_ids:
            return {}
        result = await self._session.execute(
            sa.select(_MEMBERS.c.group_id, _MEMBERS.c.user_id)
            .select_from(_MEMBERS.join(_USERS, _USERS.c.id == _MEMBERS.c.user_id))
            .where(_MEMBERS.c.group_id.in_(list(group_ids)))
            .order_by(_MEMBERS.c.group_id, _USERS.c.username)
        )
        members: dict[UUID, list[UserId]] = {}
        for row in result.all():
            members.setdefault(row.group_id, []).append(UserId(UUID(str(row.user_id))))
        return {group_id: tuple(user_ids) for group_id, user_ids in members.items()}


def _stored(row: sa.Row[tuple[object, ...]], members: Sequence[UserId]) -> StoredTraineeGroup:
    mapping = row._mapping
    return StoredTraineeGroup(
        group_id=TraineeGroupId(UUID(str(mapping["id"]))),
        name_ru=str(mapping["name_ru"]),
        created_by_user_id=UserId(UUID(str(mapping["created_by_user_id"]))),
        created_at=mapping["created_at"],
        member_user_ids=tuple(members),
    )
