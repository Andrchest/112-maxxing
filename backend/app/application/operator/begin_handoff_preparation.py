"""`beginHandoffPreparation` — `INTERVIEW --open_handoff_preparation--> HANDOFF_PREPARATION`.

Deliberately unguarded (`openapi.yaml`, SPEC §10): *"an incomplete card must remain possible,
because an omission must propagate to DDS as a real mistake"*. The `open_handoff_preparation` row
of `OPERATOR_112_TRANSITIONS` therefore has no `guard_name`, and this use case adds none —
checking the card here would quietly repair the very mistake the simulation exists to show.

Its `x-emits` is `[STAGE_STATE_CHANGED]` alone, which is exactly what `fire_stage_trigger`
returns for a transition whose `Transition.emits` is `None`.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import OperatorCommandGate
from app.application.operator.views import OperatorStageView
from app.domain.common.ids import SessionId

__all__ = ["ACTION_ID", "BeginHandoffPreparation"]

ACTION_ID = "open_handoff_preparation"
"""`openapi.yaml`'s `x-action` for `beginHandoffPreparation`."""


class BeginHandoffPreparation:
    """`beginHandoffPreparation` (`openapi.yaml`): open the handoff preparation screen."""

    def __init__(self, gate: OperatorCommandGate) -> None:
        self._gate = gate

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> OperatorStageView:
        """Fire `open_handoff_preparation` and return the new stage view."""
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
