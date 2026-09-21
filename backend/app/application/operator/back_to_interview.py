"""`backToInterview` — `HANDOFF_PREPARATION --back_to_interview--> INTERVIEW`.

Guarded by `guard_call_still_connected` (§10.8): there is no going back to the interview once the
call is over. The guard reads `GuardRuntime.call_connected` / `call_ended`, both projected from
the event log by `build_guard_runtime`, so a trainee who hung up and then tried to reopen the
interview is refused with `409 INVALID_TRANSITION` — not by a check written here, but by the
transition table.

`x-emits` is `[STAGE_STATE_CHANGED]`.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import OperatorCommandGate
from app.application.operator.views import OperatorStageView
from app.domain.common.ids import SessionId

__all__ = ["ACTION_ID", "BackToInterview"]

ACTION_ID = "back_to_interview"
"""`openapi.yaml`'s `x-action` for `backToInterview`."""


class BackToInterview:
    """`backToInterview` (`openapi.yaml`): return from handoff preparation to the interview."""

    def __init__(self, gate: OperatorCommandGate) -> None:
        self._gate = gate

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> OperatorStageView:
        """Fire `back_to_interview` and return the new stage view."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            session, events = ctx.session.fire_stage_trigger(
                ctx.stage.role_stage_id,
                ACTION_ID,
                actor=ctx.actor,
                now_ms=ctx.now_ms,
                runtime=ctx.guard_runtime(),
            )
            await ctx.save_session(session)
            await ctx.append(events)
            return ctx.stage_view(await ctx.card())
