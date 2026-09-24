"""`TraineeGroupRepository` port — `trainee_groups` and `trainee_group_members` (HLD 70 §70.3.7,
HLD 20 §20.2, I3 E9a).

A trainee group is an account-side list, like `users`: a name and the trainees in it. It is not a
simulation concept — a lesson created "for a group" copies the members into its own
`participants` and keeps only `lessons.group_id` for the record — so the stored value lives here,
in the application layer, next to the port that reads it (the reading `UserRole` follows).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import TraineeGroupId, UserId

__all__ = ["StoredTraineeGroup", "TraineeGroupRepository"]


class StoredTraineeGroup(BaseModel):
    """One `trainee_groups` row with its members, in `username` order."""

    model_config = ConfigDict(frozen=True)

    group_id: TraineeGroupId
    name_ru: str
    created_by_user_id: UserId
    created_at: datetime
    member_user_ids: tuple[UserId, ...]


@runtime_checkable
class TraineeGroupRepository(Protocol):
    """Read and write trainee groups (§20.2)."""

    async def add(self, group: StoredTraineeGroup) -> None:
        """Insert a new group and its members."""
        ...

    async def get(self, group_id: TraineeGroupId) -> StoredTraineeGroup | None:
        """The group with its members, or `None`."""
        ...

    async def list_groups(self, *, limit: int, offset: int) -> tuple[list[StoredTraineeGroup], int]:
        """One page of groups in `name_ru` order, plus the unpaged total."""
        ...

    async def replace(
        self, group_id: TraineeGroupId, *, name_ru: str, member_user_ids: Sequence[UserId]
    ) -> None:
        """Rename the group and replace its member list whole."""
        ...

    async def delete(self, group_id: TraineeGroupId) -> None:
        """Delete the group and its members; a lesson created for it keeps `group_id = NULL`."""
        ...
