"""`users` router — `listUsers` (`openapi.yaml`, additive E7, D8; CHANGED I4 E28, §71.5).

One operation, tagged `auth` in the contract because it is part of D8's account surface, but on
its own path (`/api/v1/users`) and therefore in its own module: `app.api.routers.auth` carries the
`/api/v1/auth` prefix and a router's prefix is fixed at construction.

`AdminOrInstructorDep` is the whole authorisation story: `openapi.yaml` gives this operation a
`403` and says "INSTRUCTOR / ADMIN only", so a `TRAINEE` token is refused with
`403 FORBIDDEN_FOR_ROLE` before the use case is reached. A trainee has no business enumerating the
other trainees, and the endpoint exists only so that an instructor can pick participants for
`createSession`.

I4 E28 adds `include_inactive` (ADMIN only — an INSTRUCTOR *passing* it, of any value, is
`403 FORBIDDEN_FOR_ROLE`, not just one that turns it on) and `is_active` on every item
(`UserAccountI4`), so an ADMIN can see the whole roster to block/unblock it.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import ContainerDep
from app.api.schemas.auth import UserAccountI4Schema, user_account_i4_schema
from app.api.schemas.common import PageSchema
from app.api.schemas.user_profile import user_profile_export_schema
from app.api.security import AdminOrInstructorDep, CurrentUserDep
from app.application.ports.user_repository import UserRole
from app.application.sessions.queries import ForbiddenForRoleError
from app.domain.common.ids import UserId

router = APIRouter(prefix="/api/v1/users", tags=["auth"])

UserPage = PageSchema[UserAccountI4Schema]


@router.get(
    "",
    operation_id="listUsers",
    summary="List user accounts (additive, E7; CHANGED I4 E28) — INSTRUCTOR / ADMIN only.",
    response_model=UserPage,
    status_code=200,
)
async def list_users(
    container: ContainerDep,
    user: AdminOrInstructorDep,
    role: Annotated[UserRole | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_inactive: Annotated[bool | None, Query()] = None,
) -> UserPage:
    """One page of accounts, `username` order. Never the digest (SPEC §41).

    `include_inactive` is ADMIN only (§71.5): an INSTRUCTOR who passes it at all — `true` or
    `false` — is refused, so a client never learns whether the deployment even has retired
    accounts unless it holds the role that may ask.
    """
    if include_inactive is not None and user.user_role is not UserRole.ADMIN:
        raise ForbiddenForRoleError("include_inactive is permitted for ADMIN only")
    users, total = await container.list_users()(
        role=role, limit=limit, offset=offset, include_inactive=bool(include_inactive)
    )
    return UserPage(items=[user_account_i4_schema(user) for user in users], total=total)


# --- I5 E37: profile JSON export (Q-E16-4, ТЗ ¶363) ----------------------------------------------


@router.get(
    "/{user_id}/profile-export",
    operation_id="exportUserProfile",
    summary="Download one account's profile as JSON (self or ADMIN) — Q-E16-4, ТЗ ¶363.",
    status_code=200,
    response_class=Response,
)
async def export_user_profile(
    user_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> Response:
    """Account fields plus the E33 history summary for a TRAINEE; never the password hash or the
    SIP HA1 (SPEC §41). `403 FORBIDDEN_FOR_ROLE` for anyone but the account itself or ADMIN,
    `404` for an unknown account."""
    view = await container.export_user_profile()(UserId(user_id), user)
    body = user_profile_export_schema(view).model_dump_json()
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="profile-{view.username}.json"'},
    )


# --- end I5 E37 -----------------------------------------------------------------------------
