"""`trainee-groups` schemas (`openapi.yaml`, HLD 70 §70.3.7, I3 E9a).

The wire models of `createTraineeGroup`, `listTraineeGroups`, `getTraineeGroup`,
`updateTraineeGroup`; property names copied literally from the contract. A member is named
(`username`, `display_name_ru`) so a picker never needs a second read.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.groups.trainee_groups import TraineeGroupView
from app.domain.common.ids import UserId

__all__ = [
    "TraineeGroupMemberSchema",
    "TraineeGroupRequestSchema",
    "TraineeGroupSchema",
    "trainee_group_schema",
]


class TraineeGroupRequestSchema(ApiModel):
    """`TraineeGroupRequest` — create, or replace name and members whole."""

    name_ru: str = Field(min_length=1, max_length=200)
    member_user_ids: list[UUID] = Field(default_factory=list)

    def domain_members(self) -> tuple[UserId, ...]:
        return tuple(UserId(user_id) for user_id in self.member_user_ids)


class TraineeGroupMemberSchema(ApiModel):
    """One member of `TraineeGroup.members`."""

    user_id: UUID
    username: str
    display_name_ru: str


class TraineeGroupSchema(ApiModel):
    """`TraineeGroup`."""

    group_id: UUID
    name_ru: str
    created_by_user_id: UUID
    created_at: datetime
    members: list[TraineeGroupMemberSchema]


def trainee_group_schema(view: TraineeGroupView) -> TraineeGroupSchema:
    group = view.group
    return TraineeGroupSchema(
        group_id=UUID(str(group.group_id)),
        name_ru=group.name_ru,
        created_by_user_id=UUID(str(group.created_by_user_id)),
        created_at=group.created_at,
        members=[
            TraineeGroupMemberSchema(
                user_id=UUID(str(member.user_id)),
                username=member.username,
                display_name_ru=member.display_name_ru,
            )
            for member in view.members
        ],
    )
