"""`backToDdsAcknowledged` — leave resource selection without selecting (additive, E9).

The mirror of `openDdsResourceSelection`, and the DDS counterpart of the operator's
`backToInterview`: `RESOURCE_SELECTION --back_to_acknowledged--> ACKNOWLEDGED`, guard
`guard_no_resource_selected`. Stepping back may lose no work, so while a unit is `SELECTED` the
transition is refused with `409 INVALID_TRANSITION` and the trainee deselects it first.

`x-emits: [STAGE_STATE_CHANGED]`. The guard sees only the units attached to this stage's legs,
which is what "selected" means here — a unit selected under this work item, not any unit somewhere
on the board in that status.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import DdsCommandGate
from app.application.dds.views import DdsStageView
from app.domain.common.ids import SessionId

__all__ = ["ACTION_ID", "BackToDdsAcknowledged"]

ACTION_ID = "back_to_acknowledged"
"""`openapi.yaml`'s `x-action` for `backToDdsAcknowledged`."""


class BackToDdsAcknowledged:
    """`backToDdsAcknowledged` (`openapi.yaml`, additive E9)."""

    def __init__(self, gate: DdsCommandGate) -> None:
        self._gate = gate

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> DdsStageView:
        """Fire `back_to_acknowledged` and mirror the new state onto every leg."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            session, stage_events = ctx.session.fire_stage_trigger(
                ctx.stage.role_stage_id,
                ACTION_ID,
                actor=ctx.actor,
                now_ms=ctx.now_ms,
                runtime=ctx.guard_runtime(),
                assignment=ctx.primary,
                resources=ctx.attached_units(),
            )
            await ctx.save_session(session)
            await ctx.mirror_legs()
            await ctx.append(stage_events)
            return await ctx.stage_view()
