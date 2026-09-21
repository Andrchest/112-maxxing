"""`completeOperatorStage` — end the 112 stage and move the session on (`openapi.yaml`, §10.8).

One command, two machines, one transaction:

1. the **stage** machine fires `complete_stage` (`HANDED_OFF -> STAGE_COMPLETED`, guard
   `guard_call_ended` — a stage whose call is still up is not over, so the trainee hangs up
   first and `409 INVALID_TRANSITION` says so until they do);
2. the **session** machine then fires exactly one of two triggers, in the *same* transaction,
   because "the 112 stage is over" and "the session moved on" are one fact and must not be
   separable by a crash:
   * `begin_role_transition` when the `role_chain` has a next entry — `ROLE_TRANSITION_STARTED`,
     after which the session is `ROLE_TRANSITION` and nothing but `continueToNextStage` moves it;
   * `complete` when it does not — `SESSION_COMPLETED` through
     `app.application.handoff.complete_session`, which is the one place that knows the real
     `total_events`.

`x-emits` is `[ROLE_STAGE_COMPLETED, STAGE_STATE_CHANGED, ROLE_TRANSITION_STARTED]`; the two
stage events come out of `fire_stage_trigger` in the aggregate's order (`STAGE_STATE_CHANGED`
first, then `ROLE_STAGE_COMPLETED` because the target state is terminal), which is the order
every other stage command in this codebase already appends them in.

The runner is **not** released here. Releasing the `lock:session:{id}:runner` key belongs after
the commit, so the endpoint does it — the same shape `abortSession` already uses (D7).
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.handoff.complete_session import SYSTEM_ACTOR, complete_session
from app.application.operator.command_context import OperatorCommandGate
from app.application.ports.clock import Clock
from app.application.sessions.queries import SessionDetailView, assemble_session_detail
from app.domain.common.ids import SessionId

__all__ = ["ACTION_ID", "CompleteOperatorStage"]

ACTION_ID = "complete_stage"
"""`openapi.yaml`'s `x-action` for `completeOperatorStage`."""


class CompleteOperatorStage:
    """`completeOperatorStage` (`openapi.yaml`): complete the 112 stage, then move the session."""

    def __init__(self, gate: OperatorCommandGate, clock: Clock) -> None:
        self._gate = gate
        self._clock = clock

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> SessionDetailView:
        """Fire `complete_stage`, then `begin_role_transition` or `complete`."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            completed_stage, stage_events = ctx.session.fire_stage_trigger(
                ctx.stage.role_stage_id,
                ACTION_ID,
                actor=ctx.actor,
                now_ms=ctx.now_ms,
                runtime=ctx.guard_runtime(),
            )
            await ctx.save_session(completed_stage)
            await ctx.append(stage_events)

            if ctx.session.next_stage_after(ctx.stage) is not None:
                moved, transition_events = ctx.session.begin_role_transition(
                    actor=SYSTEM_ACTOR, now_ms=ctx.now_ms, runtime=ctx.guard_runtime()
                )
                await ctx.save_session(moved)
                await ctx.append(transition_events)
            else:
                # The last stage of the chain: the session itself is over. A `[OPERATOR_112]`-only
                # chain is scored the same way `closeDdsIncident` scores the usual 112 -> DDS chain:
                # `app.api.routers.operator.complete_operator_stage` calls
                # `score_completed_session` once this gate's commit is durable (epic E15-B; see
                # `app.application.handoff.complete_session`'s docstring for why scoring runs in a
                # second, later Unit of Work rather than here).
                ctx.session, _ = await complete_session(
                    ctx.uow,
                    ctx.session,
                    clock=self._clock,
                    now_ms=ctx.now_ms,
                    last_seq_no=ctx.last_seq_no,
                    runtime=ctx.guard_runtime(),
                )

            return await assemble_session_detail(
                ctx.uow, ctx.session, viewer=user, clock=self._clock
            )
