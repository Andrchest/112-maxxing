"""Trainee groups — `createTraineeGroup`, `listTraineeGroups`, `getTraineeGroup`,
`updateTraineeGroup`, `deleteTraineeGroup` (HLD 70 §70.3.7, I3 E9a; F-15 «Назначать учащимся
конкретные задания и группы»).

A group is a named list of trainees. Every INSTRUCTOR/ADMIN sees and uses every group (the
router's account gate): groups are shared among the instructors of one training centre, like the
scenario catalog. I5 E39 (Q-E9b-4 а): only its creator (`created_by_user_id`) or an ADMIN may
rename, re-member or delete a group; another instructor gets `403 NOT_RESOURCE_OWNER`. A member
must be an active `TRAINEE` account (`422 VALIDATION_ERROR` otherwise); the member list is
written whole.

A lesson "for a group" is a lesson whose form was pre-filled from the group: the lesson copies
the members into its own `participants` and records `lessons.group_id`. Changing or deleting the
group afterwards changes no lesson (`ON DELETE SET NULL`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.auth.ownership import require_owner_or_admin
from app.application.ports.clock import Clock
from app.application.ports.id_generator import IdGenerator
from app.application.ports.trainee_group_repository import StoredTraineeGroup
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.user_repository import StoredUser, UserRole
from app.domain.common.errors import DomainError
from app.domain.common.ids import TraineeGroupId, UserId

__all__ = [
    "CreateTraineeGroup",
    "DeleteTraineeGroup",
    "GetTraineeGroup",
    "ListTraineeGroups",
    "TraineeGroupMemberInvalidError",
    "TraineeGroupNotFoundError",
    "TraineeGroupView",
    "UpdateTraineeGroup",
]


class TraineeGroupNotFoundError(DomainError):
    """No `trainee_groups` row with the requested id (`404 NOT_FOUND`)."""

    code = "NOT_FOUND"

    def __init__(self, group_id: TraineeGroupId) -> None:
        self.group_id = group_id
        super().__init__(f"no trainee group {group_id}")


class TraineeGroupMemberInvalidError(DomainError):
    """A member is not an active `TRAINEE` account, or the name is blank (`422`)."""

    code = "VALIDATION_ERROR"


@dataclass(frozen=True)
class TraineeGroupView:
    """`TraineeGroup` as application data: the group and its member accounts."""

    group: StoredTraineeGroup
    members: tuple[StoredUser, ...]


def _clean_name(name_ru: str) -> str:
    name = name_ru.strip()
    if not name:
        raise TraineeGroupMemberInvalidError("a trainee group needs a name")
    return name


async def _checked_members(uow: UnitOfWork, user_ids: Sequence[UserId]) -> tuple[UserId, ...]:
    """The distinct members in request order; every one an active `TRAINEE` account."""
    unique = tuple(dict.fromkeys(user_ids))
    accounts = {account.user_id: account for account in await uow.users.get_many(unique)}
    invalid = [
        str(user_id)
        for user_id in unique
        if user_id not in accounts
        or not accounts[user_id].is_active
        or accounts[user_id].user_role is not UserRole.TRAINEE
    ]
    if invalid:
        raise TraineeGroupMemberInvalidError(
            f"group members must be active TRAINEE accounts: {', '.join(invalid)}"
        )
    return unique


async def _view(uow: UnitOfWork, group: StoredTraineeGroup) -> TraineeGroupView:
    accounts = {
        account.user_id: account for account in await uow.users.get_many(group.member_user_ids)
    }
    return TraineeGroupView(
        group=group,
        members=tuple(
            accounts[user_id] for user_id in group.member_user_ids if user_id in accounts
        ),
    )


async def _owned_group(
    uow: UnitOfWork, group_id: TraineeGroupId, actor: AuthenticatedUser
) -> StoredTraineeGroup:
    """The group, if `actor` may change it: its creator or an ADMIN (I5 E39, Q-E9b-4 а)."""
    group = await uow.trainee_groups.get(group_id)
    if group is None:
        raise TraineeGroupNotFoundError(group_id)
    require_owner_or_admin(group.created_by_user_id, actor, resource=f"trainee group {group_id}")
    return group


class CreateTraineeGroup:
    """`createTraineeGroup`."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, ids: IdGenerator, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._ids = ids
        self._clock = clock

    async def __call__(
        self, *, name_ru: str, member_user_ids: Sequence[UserId], actor: AuthenticatedUser
    ) -> TraineeGroupView:
        name = _clean_name(name_ru)
        async with self._unit_of_work() as uow:
            members = await _checked_members(uow, member_user_ids)
            group = StoredTraineeGroup(
                group_id=TraineeGroupId(self._ids.new()),
                name_ru=name,
                created_by_user_id=actor.user_id,
                created_at=self._clock.now(),
                member_user_ids=members,
            )
            await uow.trainee_groups.add(group)
            stored = await uow.trainee_groups.get(group.group_id)
            assert stored is not None  # written in this very transaction
            view = await _view(uow, stored)
            await uow.commit()
        return view


class ListTraineeGroups:
    """`listTraineeGroups` — one page in `name_ru` order, plus the unpaged total."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, *, limit: int, offset: int) -> tuple[list[TraineeGroupView], int]:
        async with self._unit_of_work() as uow:
            groups, total = await uow.trainee_groups.list_groups(limit=limit, offset=offset)
            views = [await _view(uow, group) for group in groups]
            await uow.commit()
        return views, total


class GetTraineeGroup:
    """`getTraineeGroup`."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, group_id: TraineeGroupId) -> TraineeGroupView:
        async with self._unit_of_work() as uow:
            group = await uow.trainee_groups.get(group_id)
            if group is None:
                raise TraineeGroupNotFoundError(group_id)
            view = await _view(uow, group)
            await uow.commit()
        return view


class UpdateTraineeGroup:
    """`updateTraineeGroup` — rename and replace the member list whole."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        group_id: TraineeGroupId,
        *,
        name_ru: str,
        member_user_ids: Sequence[UserId],
        actor: AuthenticatedUser,
    ) -> TraineeGroupView:
        name = _clean_name(name_ru)
        async with self._unit_of_work() as uow:
            await _owned_group(uow, group_id, actor)
            members = await _checked_members(uow, member_user_ids)
            await uow.trainee_groups.replace(group_id, name_ru=name, member_user_ids=members)
            stored = await uow.trainee_groups.get(group_id)
            assert stored is not None
            view = await _view(uow, stored)
            await uow.commit()
        return view


class DeleteTraineeGroup:
    """`deleteTraineeGroup` — lessons created for it keep their participants."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, group_id: TraineeGroupId, *, actor: AuthenticatedUser) -> None:
        async with self._unit_of_work() as uow:
            await _owned_group(uow, group_id, actor)
            await uow.trainee_groups.delete(group_id)
            await uow.commit()
