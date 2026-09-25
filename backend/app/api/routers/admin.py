"""`admin` router — the operator-only maintenance surface of `openapi.yaml`'s `admin` tag.

Two operations live under `/api/v1/admin`, and they have nothing in common except who may call
them: `clearInferenceFatal` (E18-B, below) and `purgeRecordings` (E18-D, its own marked section at
the end of this module). They share one `APIRouter` because they share one path prefix, not
because they share a concern.

`clearInferenceFatal` deletes the un-expiring `voice:health:fatal` latch of
`60-inference-ops.md` §4.3 — the key that exists so "a restart loop cannot make a fatal condition
look transient". Three properties make it safe to expose:

* it **touches no session state** (`openapi.yaml`: "Touches no session state"). It deletes one
  Redis key and publishes one transition; `simulation_sessions.state` is not written, no use case
  of `app.application.sessions` is called, and SPEC §39's "never silently reset the simulation"
  holds by construction;
* it does not make anything `READY`. The response is the readiness snapshot **after** clearing,
  and every inference component in it still reads its own `voice:health:{service}` heartbeat: a
  service whose warm-up has not run since the fatal condition still reports `NOT_READY`;
* clearing publishes on `voice:health`, which is what the subscriber turns into the
  `INFERENCE_HEALTH_CHANGED` the contract's `x-emits` promises. The router does not append the
  event itself — the same code path serves a voice-agent transition and an admin's click.

**Roles.** Both operations are `ADMIN` only (manager ruling R4 of epic E18). `openapi.yaml`'s
*summary line* for `clearInferenceFatal` says "INSTRUCTOR / ADMIN"; its machine-readable part
defines only `401` and `403`, so the narrower gate satisfies the contract's responses while the
prose and the ruling disagree. The disagreement is reported, not worked around — see the E18-B
task report's "HLD gaps".
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import ContainerDep
from app.api.routers.health import readiness_snapshot
from app.api.schemas.admin import (
    PurgeRecordingsRequestSchema,
    PurgeRecordingsResultSchema,
    purge_recordings_request,
    purge_recordings_result_schema,
)
from app.api.schemas.auth import (
    PasswordResetRequestSchema,
    UserAccountI4Schema,
    UserCreateRequestSchema,
    UserUpdateRequestSchema,
    user_account_i4_schema,
)
from app.api.schemas.health import HealthReadyResponseSchema
from app.api.security import require_roles
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.domain.common.ids import UserId

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

AdminDep = Annotated[AuthenticatedUser, Depends(require_roles(UserRole.ADMIN))]
"""ADMIN only, for both operations of this router (manager ruling R4 of epic E18; see the
module docstring's note on `openapi.yaml`'s wider summary line)."""


@router.post(
    "/inference/clear-fatal",
    operation_id="clearInferenceFatal",
    summary="Clear a latched FATAL inference state (ADMIN).",
    response_model=HealthReadyResponseSchema,
    status_code=200,
)
async def clear_inference_fatal(
    container: ContainerDep, _user: AdminDep
) -> HealthReadyResponseSchema:
    """Delete `voice:health:fatal`, announce it, and answer with the readiness snapshot after.

    The snapshot is re-probed rather than patched: clearing the latch removes the reason every
    inference probe was reporting `FATAL`, and what they report instead is whatever their own
    heartbeat says at this instant — which is the only honest answer (SPEC §37).
    """
    await container.inference_fatal.clear()
    return await readiness_snapshot(container)


# --- recordings (E18-D) ---
#
# `purgeRecordings` (`POST /api/v1/admin/recordings/purge`, ADMIN only) belongs here, on this
# router, sharing `AdminDep`. E18-B created the module and left this section empty on purpose so
# that the two tasks never touch the same lines.


@router.post(
    "/recordings/purge",
    operation_id="purgeRecordings",
    summary="Purge recordings past the retention window (ADMIN).",
    response_model=PurgeRecordingsResultSchema,
    status_code=200,
)
async def purge_recordings(
    container: ContainerDep,
    user: AdminDep,
    body: PurgeRecordingsRequestSchema | None = None,
) -> PurgeRecordingsResultSchema:
    """`python -m app.cli purge_recordings`'s other front door — same use case, same rule
    (`app.application.recording.PurgeRecordings`, this task's ruling R8). A bare `POST` with no
    body is the default `dry_run=True` sweep over `Settings.recording_retention_days`.
    """
    request = purge_recordings_request(body or PurgeRecordingsRequestSchema())
    result = await container.purge_recordings()(request, actor=user)
    return purge_recordings_result_schema(result)


# --- accounts (I4 E28, `71-i4-wave4.md` §71.5) --------------------------------------------------
#
# `createUser`, `updateUser`, `resetUserPassword` — ТЗ ¶195-¶197, ADMIN only, sharing `AdminDep`.
# `updateUser`'s single PATCH body is split across two use cases (`UpdateUser` for role / display
# name, `SetActive` for `is_active`); both run in this one request, so it still leaves exactly one
# `audit_log` row (E25's middleware records the HTTP request, not the calls inside it). Every
# guard the use cases raise (`USERNAME_TAKEN`, `SELF_MODIFICATION_FORBIDDEN`,
# `LAST_ADMIN_REQUIRED`) is a `DomainError` with its own `code`, rendered by
# `app.api.errors.install_exception_handlers` like any other.


@router.post(
    "/users",
    operation_id="createUser",
    summary="Create an account of any role (ADMIN) — ТЗ ¶195.",
    response_model=UserAccountI4Schema,
    status_code=201,
)
async def create_user(
    body: UserCreateRequestSchema, container: ContainerDep, _user: AdminDep
) -> UserAccountI4Schema:
    created = await container.create_user()(
        username=body.username,
        display_name_ru=body.display_name_ru,
        user_role=body.user_role,
        password=body.password,
    )
    return user_account_i4_schema(created)


@router.patch(
    "/users/{user_id}",
    operation_id="updateUser",
    summary="Change role, display name or block/unblock (ADMIN) — ТЗ ¶196, ¶197.",
    response_model=UserAccountI4Schema,
    status_code=200,
)
async def update_user(
    user_id: UUID,
    body: UserUpdateRequestSchema,
    container: ContainerDep,
    user: AdminDep,
) -> UserAccountI4Schema:
    """Every field is optional (`minProperties: 1`, enforced by the request schema).

    `is_active` is applied last, after the role/display-name change, so a body that both demotes
    and blocks the same account is checked and written consistently: `UpdateUser` sees the account
    as it was before this request, `SetActive` as it is after `UpdateUser` ran.
    """
    target = UserId(user_id)
    updated = None
    if body.display_name_ru is not None or body.user_role is not None:
        updated = await container.update_user()(
            target,
            actor_id=user.user_id,
            display_name_ru=body.display_name_ru,
            user_role=body.user_role,
        )
    if body.is_active is not None:
        updated = await container.set_active()(
            target, actor_id=user.user_id, is_active=body.is_active
        )
    assert updated is not None, "the schema's own validator requires at least one field"
    return user_account_i4_schema(updated)


@router.post(
    "/users/{user_id}/password",
    operation_id="resetUserPassword",
    summary="Set a new password for an account (ADMIN).",
    status_code=204,
    response_class=Response,
)
async def reset_user_password(
    user_id: UUID, body: PasswordResetRequestSchema, container: ContainerDep, _user: AdminDep
) -> Response:
    """The password is never echoed, logged or audited in clear (E25 records the operation, not
    the body)."""
    await container.reset_password()(UserId(user_id), password=body.password)
    return Response(status_code=204)
