"""`sessions` router — `createSession`, `listSessions`, `getSession`, `startSession`,
`abortSession` (`openapi.yaml`, D6, D7, D8).

The three commands are where this epic's runner wiring lands (D7 —
`app.application.simulation.runner` is driven from here and nowhere else):

* `startSession` calls `runner.adopt(session_id)` **after** the use case has committed, so the
  world engine begins ticking a session that is already `ACTIVE` in PostgreSQL — never one whose
  transaction might still roll back;
* `abortSession` calls `runner.release(session_id)` after its commit, which cancels the task and
  gives up the `lock:session:{id}:runner` key so no instance keeps ticking an aborted session;
* `createSession` adopts nothing: a `READY` session has no clock running yet (D7).

`SIM_RUNNER_ENABLED=false` skips both calls. API tests set it so that no background task can
outlive a test; they drive `tick_session` explicitly instead.

Authorisation is `openapi.yaml`'s, literally: `createSession` and `abortSession` are
INSTRUCTOR/ADMIN, `startSession` is INSTRUCTOR (and ADMIN, who can do anything an instructor can),
and the two reads are open to any authenticated caller but filtered by `can_observe`.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.api.schemas.common import PageSchema
from app.api.schemas.sessions import (
    AbortSessionRequestSchema,
    SessionCreateRequestSchema,
    SessionDetailSchema,
    SessionListItemSchema,
    session_detail_schema,
    session_list_item_schema,
)
from app.api.security import AdminOrInstructorDep, CurrentUserDep, actor_of
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.sessions.create_session import CreateSessionCommand
from app.application.sessions.queries import assemble_session_detail
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.enums import SessionState
from app.domain.session.session import SimulationSession

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

SessionPage = PageSchema[SessionListItemSchema]


@router.post(
    "",
    operation_id="createSession",
    summary="Create a simulation session (INSTRUCTOR / ADMIN).",
    response_model=SessionDetailSchema,
    status_code=201,
)
async def create_session(
    body: SessionCreateRequestSchema, container: ContainerDep, user: AdminOrInstructorDep
) -> SessionDetailSchema:
    """One session, one incident, one `RoleStage` per `role_chain` entry, then `validate`.

    A `role_chain` of `[DDS]` under `SINGLE_ROLE` or `ASSESSMENT` without
    `expected_response.prefab_handoff` is refused with `409 PREFAB_HANDOFF_REQUIRED` by the domain
    factory (D6, §10.10) — this endpoint does not re-decide it.
    """
    session = await container.create_session()(
        CreateSessionCommand(
            scenario_version_id=ScenarioVersionId(body.scenario_version_id),
            session_mode=body.session_mode,
            actor=actor_of(user),
            participants=tuple(
                (UserId(assignment.user_id), assignment.assigned_role_type)
                for assignment in body.participants
            ),
            session_seed=body.session_seed,
            time_scale=body.time_scale,
        )
    )
    return await _detail(container, session, user)


@router.get(
    "",
    operation_id="listSessions",
    summary="List sessions — mine, or all for an instructor.",
    response_model=SessionPage,
    status_code=200,
)
async def list_sessions(
    container: ContainerDep,
    user: CurrentUserDep,
    scope: Annotated[str, Query(pattern="^(MINE|ALL)$")] = "MINE",
    state: SessionState | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SessionPage:
    """`scope=MINE` is the caller's own sessions; `scope=ALL` is INSTRUCTOR/ADMIN only.

    A `TRAINEE` asking for `ALL` is `403 FORBIDDEN_FOR_ROLE` and learns nothing — not even how
    many sessions exist.
    """
    listings, total = await container.list_sessions()(
        viewer=user, scope=scope, state=state, limit=limit, offset=offset
    )
    return SessionPage(
        items=[session_list_item_schema(listing) for listing in listings], total=total
    )


@router.get(
    "/{session_id}",
    operation_id="getSession",
    summary="One session's materialized header.",
    response_model=SessionDetailSchema,
    status_code=200,
)
async def get_session(
    session_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> SessionDetailSchema:
    """The session, if the caller may observe it; otherwise `403 FORBIDDEN_FOR_ROLE`."""
    view = await container.get_session()(SessionId(session_id), viewer=user)
    return session_detail_schema(view)


@router.post(
    "/{session_id}/start",
    operation_id="startSession",
    summary="Start the session (INSTRUCTOR).",
    response_model=SessionDetailSchema,
    status_code=200,
)
async def start_session(
    session_id: UUID, container: ContainerDep, user: AdminOrInstructorDep
) -> SessionDetailSchema:
    """`READY → ACTIVE`, then the `SimulationRunner` adopts the session (D7).

    Refused with `503 INFERENCE_NOT_READY` while a required inference service is not `READY` and
    `REQUIRE_INFERENCE_READY=true` (D8, SPEC §37). Adoption happens only after the use case's
    transaction has committed, so the runner never ticks a session a rollback removed.
    """
    started = await container.start_session()(SessionId(session_id), actor_of(user))
    if container.settings.runner_enabled:
        container.runner.adopt(started.id)
    return await _detail(container, started, user)


@router.post(
    "/{session_id}/abort",
    operation_id="abortSession",
    summary="Abort the session (INSTRUCTOR / ADMIN).",
    response_model=SessionDetailSchema,
    status_code=200,
)
async def abort_session(
    session_id: UUID,
    body: AbortSessionRequestSchema,
    container: ContainerDep,
    user: AdminOrInstructorDep,
) -> SessionDetailSchema:
    """Abort, then stop ticking and release the runner lock (D7).

    "Simulation data is preserved: the event log is closed, never deleted (SPEC §39, §42 test 14)."
    """
    aborted = await container.abort_session()(SessionId(session_id), actor_of(user), body.reason)
    if container.settings.runner_enabled:
        await container.runner.release(aborted.id)
    return await _detail(container, aborted, user)


async def _detail(
    container: ContainerDep, session: SimulationSession, user: AuthenticatedUser
) -> SessionDetailSchema:
    """The `SessionDetail` a command returns: the materialized view of what it just did (D8)."""
    async with container.unit_of_work() as uow:
        view = await assemble_session_detail(uow, session, viewer=user, clock=container.clock)
        await uow.commit()
    return session_detail_schema(view)
