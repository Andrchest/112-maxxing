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

`continueToNextStage` (E9) is on this tag rather than on `operator` because the stage it starts is
not a 112 one — it is whatever `role_chain` names next, which today is DDS. Its own authorisation
is the next stage's participant, or an instructor/admin; the use case owns that rule
(`app.application.handoff.continue_to_next_stage`), because it is the one place that knows which
stage "next" means.
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
from app.api.schemas.voice import (
    VoiceTokenRequestSchema,
    VoiceTokenResponseSchema,
    voice_token_response_schema,
)
from app.api.security import AdminOrInstructorDep, CurrentUserDep, actor_of
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.sessions.create_session import CreateSessionCommand
from app.application.sessions.queries import assemble_session_detail
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.enums import ServiceId, SessionState
from app.domain.session.session import SimulationSession
from app.domain.session.variants import PartialVariants

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

    `variants` (every switch optional) is resolved request → scenario default by the use case
    (HLD 70 §70.2.2): an unimplemented value is `409 VARIANT_NOT_AVAILABLE`, one outside the
    scenario's `supported` is `409 VARIANT_NOT_SUPPORTED`. Under `card_source: GENERATED_CARD`
    the stages are the chain suffix starting at DDS.
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
            variants=(
                body.variants.to_domain() if body.variants is not None else PartialVariants()
            ),
            assigned_services={
                UserId(assignment.user_id): ServiceId(assignment.assigned_service_id)
                for assignment in body.participants
                if assignment.assigned_service_id is not None
            },
            timers=None if body.timers is None else body.timers.to_domain(),
            pass_criteria=(None if body.pass_criteria is None else body.pass_criteria.to_domain()),
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
    started = await container.start_session()(SessionId(session_id), actor_of(user), caller=user)
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
    aborted = await container.abort_session()(
        SessionId(session_id), actor_of(user), body.reason, caller=user
    )
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


@router.post(
    "/{session_id}/voice-token",
    operation_id="createVoiceToken",
    summary="Mint a LiveKit access token for the calling participant.",
    response_model=VoiceTokenResponseSchema,
    status_code=200,
)
async def create_voice_token(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    body: VoiceTokenRequestSchema | None = None,
) -> VoiceTokenResponseSchema:
    """One room-scoped LiveKit token for this session's live call (D9).

    `x-action` is `'-'` and `x-emits` is `[]`: nothing is appended and nothing moves. The use case
    refuses a non-`ACTIVE` session with `409 SESSION_NOT_ACTIVE`, a caller who is not the active
    `OPERATOR_112` participant with `403`, and a session whose call is neither `RINGING` nor
    `CONNECTED` with `409 ACTION_NOT_AVAILABLE`.

    The minted token is never logged (SPEC §41): it goes into this response body and nowhere else.

    (Additive, I3 E6b) With `{call_id}` the token is for that ДДС call's room — the caller's own,
    non-`ENDED` `DdsCall` (re-join after a refresh, INV 13).
    """
    call_id = None if body is None else body.call_id
    minted = await container.create_voice_token()(SessionId(session_id), user, call_id)
    return voice_token_response_schema(minted)


@router.post(
    "/{session_id}/stage/continue",
    operation_id="continueToNextStage",
    summary="Continue to the next role stage after the configurable pause.",
    response_model=SessionDetailSchema,
    status_code=200,
)
async def continue_to_next_stage(
    session_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> SessionDetailSchema:
    """`ROLE_TRANSITION --finish_role_transition--> ACTIVE`; the same `Incident` carries over.

    Refused with `409 INVALID_TRANSITION` until `policy.transition_pause_seconds` has elapsed
    since `ROLE_TRANSITION_STARTED` — the pause is the policy's, not a frontend timer (§10.10).
    """
    view = await container.continue_to_next_stage()(SessionId(session_id), user)
    return session_detail_schema(view)
