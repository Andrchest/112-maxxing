"""`users` router — `listUsers` (`openapi.yaml`, additive E7, D8).

One operation, tagged `auth` in the contract because it is part of D8's account surface, but on
its own path (`/api/v1/users`) and therefore in its own module: `app.api.routers.auth` carries the
`/api/v1/auth` prefix and a router's prefix is fixed at construction.

`AdminOrInstructorDep` is the whole authorisation story: `openapi.yaml` gives this operation a
`403` and says "INSTRUCTOR / ADMIN only", so a `TRAINEE` token is refused with
`403 FORBIDDEN_FOR_ROLE` before the use case is reached. A trainee has no business enumerating the
other trainees, and the endpoint exists only so that an instructor can pick participants for
`createSession`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.api.schemas.auth import UserAccountSchema, user_account_schema
from app.api.schemas.common import PageSchema
from app.api.security import AdminOrInstructorDep
from app.application.ports.user_repository import UserRole

router = APIRouter(prefix="/api/v1/users", tags=["auth"])

UserPage = PageSchema[UserAccountSchema]


@router.get(
    "",
    operation_id="listUsers",
    summary="List user accounts (additive, E7) — INSTRUCTOR / ADMIN only.",
    response_model=UserPage,
    status_code=200,
)
async def list_users(
    container: ContainerDep,
    _user: AdminOrInstructorDep,
    role: Annotated[UserRole | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserPage:
    """One page of active accounts, `username` order. Never the digest (SPEC §41)."""
    users, total = await container.list_users()(role=role, limit=limit, offset=offset)
    return UserPage(items=[user_account_schema(user) for user in users], total=total)
