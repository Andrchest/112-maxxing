"""`trainee-groups` router — `listTraineeGroups`, `createTraineeGroup`, `getTraineeGroup`,
`updateTraineeGroup`, `deleteTraineeGroup` (`openapi.yaml`, HLD 70 §70.3.7, I3 E9a).

INSTRUCTOR / ADMIN only (`AdminOrInstructorDep`): a group is an instructor's tool for building
lessons («Назначать учащимся конкретные задания и группы»), and a trainee has no business
enumerating the other trainees.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import ContainerDep
from app.api.schemas.common import PageSchema
from app.api.schemas.groups import (
    TraineeGroupRequestSchema,
    TraineeGroupSchema,
    trainee_group_schema,
)
from app.api.security import AdminOrInstructorDep
from app.domain.common.ids import TraineeGroupId

router = APIRouter(prefix="/api/v1/trainee-groups", tags=["lessons"])

TraineeGroupPage = PageSchema[TraineeGroupSchema]


@router.get(
    "",
    operation_id="listTraineeGroups",
    summary="List trainee groups (INSTRUCTOR / ADMIN).",
    response_model=TraineeGroupPage,
    status_code=200,
)
async def list_trainee_groups(
    container: ContainerDep,
    _user: AdminOrInstructorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TraineeGroupPage:
    views, total = await container.list_trainee_groups()(limit=limit, offset=offset)
    return TraineeGroupPage(items=[trainee_group_schema(view) for view in views], total=total)


@router.post(
    "",
    operation_id="createTraineeGroup",
    summary="Create a trainee group (INSTRUCTOR / ADMIN).",
    response_model=TraineeGroupSchema,
    status_code=201,
)
async def create_trainee_group(
    body: TraineeGroupRequestSchema, container: ContainerDep, user: AdminOrInstructorDep
) -> TraineeGroupSchema:
    view = await container.create_trainee_group()(
        name_ru=body.name_ru, member_user_ids=body.domain_members(), actor=user
    )
    return trainee_group_schema(view)


@router.get(
    "/{group_id}",
    operation_id="getTraineeGroup",
    summary="One trainee group with its members.",
    response_model=TraineeGroupSchema,
    status_code=200,
)
async def get_trainee_group(
    group_id: UUID, container: ContainerDep, _user: AdminOrInstructorDep
) -> TraineeGroupSchema:
    return trainee_group_schema(await container.get_trainee_group()(TraineeGroupId(group_id)))


@router.put(
    "/{group_id}",
    operation_id="updateTraineeGroup",
    summary="Rename a trainee group and replace its members whole.",
    response_model=TraineeGroupSchema,
    status_code=200,
)
async def update_trainee_group(
    group_id: UUID,
    body: TraineeGroupRequestSchema,
    container: ContainerDep,
    user: AdminOrInstructorDep,
) -> TraineeGroupSchema:
    view = await container.update_trainee_group()(
        TraineeGroupId(group_id),
        name_ru=body.name_ru,
        member_user_ids=body.domain_members(),
        actor=user,
    )
    return trainee_group_schema(view)


@router.delete(
    "/{group_id}",
    operation_id="deleteTraineeGroup",
    summary="Delete a trainee group; lessons created for it keep their participants.",
    status_code=204,
    response_class=Response,
)
async def delete_trainee_group(
    group_id: UUID, container: ContainerDep, user: AdminOrInstructorDep
) -> Response:
    await container.delete_trainee_group()(TraineeGroupId(group_id), actor=user)
    return Response(status_code=204)
