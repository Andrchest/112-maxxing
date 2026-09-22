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

from fastapi import APIRouter, Depends

from app.api.deps import ContainerDep
from app.api.routers.health import readiness_snapshot
from app.api.schemas.admin import (
    PurgeRecordingsRequestSchema,
    PurgeRecordingsResultSchema,
    purge_recordings_request,
    purge_recordings_result_schema,
)
from app.api.schemas.health import HealthReadyResponseSchema
from app.api.security import require_roles
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole

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
