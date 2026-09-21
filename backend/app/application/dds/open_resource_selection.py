"""`openDdsResourceSelection` — open the resource-selection screen (additive, E9).

§10.9 lists `open_resource_selection` as an available action of both `ACKNOWLEDGED` ("Подбор сил и
средств") and `DISPATCHED` ("Добавить силы"), but `openapi.yaml` gave it no endpoint: the console
had a button that could not be pressed. This is that endpoint, added additively on the shape of
the operator's `beginHandoffPreparation` — no request body, the new `DdsStageView` in reply,
`x-emits: [STAGE_STATE_CHANGED]`.

The trigger is unguarded from `ACKNOWLEDGED` and guarded by `guard_additional_dispatch_allowed`
from `DISPATCHED` ("no dispatched resource has reached `EN_ROUTE` yet"), so going back to pick
more units once the first ones are rolling is refused here and is done through
`select_resource` + `dispatch_additional` in `EN_ROUTE` / `ARRIVED` / `WORKING` instead (the E9
repair, `domain/roles/dds.py`).
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import DdsCommandGate
from app.application.dds.views import DdsStageView
from app.domain.common.ids import SessionId

__all__ = ["ACTION_ID", "OpenDdsResourceSelection"]

ACTION_ID = "open_resource_selection"
"""`openapi.yaml`'s `x-action` for `openDdsResourceSelection`."""


class OpenDdsResourceSelection:
    """`openDdsResourceSelection` (`openapi.yaml`, additive E9)."""

    def __init__(self, gate: DdsCommandGate) -> None:
        self._gate = gate

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> DdsStageView:
        """Fire `open_resource_selection` and mirror the new state onto every leg."""
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
