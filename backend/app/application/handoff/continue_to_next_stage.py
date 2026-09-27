"""`continueToNextStage` — `ROLE_TRANSITION --finish_role_transition--> ACTIVE` (§10.8, §13).

The other half of `completeOperatorStage`. `begin_role_transition` parked the session in
`ROLE_TRANSITION`; this command starts the next stage once
`guard_pause_elapsed_and_next_assigned` is satisfied: `now_ms >= transition_started_ms +
policy.transition_pause_seconds * 1000`, and the next stage has an assigned participant. Called
before the pause elapses it is `409 INVALID_TRANSITION` — **the pause is
`SessionPolicy.transition_pause_seconds`, not a frontend timer**, and the transition-started
offset is read from the session's own log (`ROLE_TRANSITION_STARTED`), never from the client.

Who may call it (`openapi.yaml` gives the operation the `sessions` tag and no `x-permission`, so
the rule is D8's first gate applied to the stage that is *about to* run):

* the participant bound to the **next** stage — under `FULL_CYCLE_SINGLE_TRAINEE` that is the
  same trainee who just finished the 112 stage, and under `MULTI_TRAINEE` it is the DDS trainee
  waiting for their console to come alive;
* an `INSTRUCTOR` or `ADMIN`, who runs the exercise and may move it along (SPEC §7).

Anyone else is `403 FORBIDDEN_FOR_ROLE`, including a trainee who is a participant of the session
but not of the stage being started.

This command does **not** go through `OperatorCommandGate`: that pipeline is the Operator 112
stage's (it demands an `OPERATOR_112` active stage and a `TRAINEE` account), and by the time this
runs the session is not `ACTIVE` at all. It opens its own Unit of Work with the same `SELECT …
FOR UPDATE` row lock, which is what serialises it against a concurrent tick.

The **same `Incident` carries over** (SPEC §13, §42 test 5): `finish_role_transition` only stamps
`started_at_offset_ms` on the next `RoleStage`; no method on the aggregate ever replaces
`SimulationSession.incident`. The DDS stage therefore opens in `RECEIVED` with the
`dds_assignments` legs `createHandoff` already wrote, pointing at the snapshot of that same
incident.

`x-emits` is `[ROLE_TRANSITION_COMPLETED, ROLE_STAGE_STARTED, STAGE_STATE_CHANGED]`; the
aggregate returns the first two, and the third is the stage-state notification the next stage's
own first command produces — `finish_role_transition` moves a stage from "not started" to its
*initial* state, which is not a transition of the stage machine and has no previous state to
report.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.auth.ownership import require_owner_or_admin
from app.application.handoff.complete_session import SYSTEM_ACTOR
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.guard_context import build_guard_runtime
from app.application.sessions.queries import (
    ForbiddenForRoleError,
    SessionDetailView,
    assemble_session_detail,
)
from app.application.sessions.start_session import SessionNotFoundError
from app.application.simulation.sim_time import transition_clock_ms
from app.domain.common.ids import SessionId
from app.domain.session.session import RoleStage, SimulationSession

__all__ = ["ACTION_ID", "ContinueToNextStage"]

ACTION_ID = "finish_role_transition"
"""`openapi.yaml`'s `x-action` for `continueToNextStage`."""


class ContinueToNextStage:
    """`continueToNextStage` (`openapi.yaml`): start the next role stage after the pause."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> SessionDetailView:
        """Fire `finish_role_transition` and answer with the session the next stage runs in."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            _authorise(session, user)

            now_ms = transition_clock_ms(session, self._clock.now())
            runtime = build_guard_runtime(
                await uow.events.read(session_id), scenario_valid=True, inference_ready=True
            )
            continued, events = session.finish_role_transition(
                actor=SYSTEM_ACTOR, now_ms=now_ms, runtime=runtime
            )

            await uow.sessions.save(continued)
            await uow.events.append(session_id, events)
            detail = await assemble_session_detail(uow, continued, viewer=user, clock=self._clock)
            await uow.commit()
        return detail


def _authorise(session: SimulationSession, user: AuthenticatedUser) -> None:
    """The next stage's participant, an instructor or an admin — nobody else (see the docstring).

    `resolve_participant` is asked first even for a trainee who turns out not to hold the next
    stage, so a caller with no participant row at all still gets `PARTICIPANT_NOT_ASSIGNED`
    rather than the vaguer role refusal: the two answers are D8's, and they are different
    questions.

    I5 E39 (Q-E9b-4 а): an instructor continues only a session they created (an ADMIN any);
    another instructor is refused with `403 NOT_RESOURCE_OWNER`.
    """
    if user.is_instructor_or_admin:
        require_owner_or_admin(session.created_by_user_id, user, resource=f"session {session.id}")
        return
    participant = resolve_participant(session, user)
    next_stage = _next_stage(session)
    if next_stage is None or next_stage.participant_user_id != participant.user_id:
        raise ForbiddenForRoleError(
            f"the caller is not the participant of the next role stage of session {session.id}"
        )


def _next_stage(session: SimulationSession) -> RoleStage | None:
    """The stage `finish_role_transition` is about to start, or `None` when there is none."""
    active = session.active_stage
    return None if active is None else session.next_stage_after(active)
