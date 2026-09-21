"""`acknowledgeDdsAssignment` — take the work item (`openapi.yaml`, §10.8, SPEC §11).

`RECEIVED --acknowledge--> ACKNOWLEDGED`, guard `guard_participant_assigned_to_stage`: only the
trainee the DDS `RoleStage` is bound to can accept the work item, which is the same fact D8's
first gate checks and is checked twice on purpose (§10.8 states the guard, D8 states the gate).

`x-emits` is `[DDS_ACKNOWLEDGED, STAGE_STATE_CHANGED]`, and that is the order the events are
appended in. Exactly **one** `DDS_ACKNOWLEDGED` is appended however many recipient services the
operator chose (E9 analyst R5): one trainee action, one trainee event, carrying the primary leg's
`assignment_id`. Every leg then mirrors the new stage state and the acknowledgement offset (R1),
because the trainee acknowledged the one work item, not N of them.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import DdsCommandContext, DdsCommandGate
from app.application.dds.views import DdsStageView
from app.domain.common.ids import SessionId
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "AcknowledgeDdsAssignment"]

ACTION_ID = "acknowledge"
"""`openapi.yaml`'s `x-action` for `acknowledgeDdsAssignment`."""


class AcknowledgeDdsAssignment:
    """`acknowledgeDdsAssignment` (`openapi.yaml`): `RECEIVED -> ACKNOWLEDGED`."""

    def __init__(self, gate: DdsCommandGate) -> None:
        self._gate = gate

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> DdsStageView:
        """Fire `acknowledge`, mirror it onto every leg, answer with the new stage view."""
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
            await ctx.mirror_legs(acknowledged_at_offset_ms=ctx.now_ms)
            await ctx.append([_acknowledged(ctx), *stage_events])
            return await ctx.stage_view()


def _acknowledged(ctx: DdsCommandContext) -> DomainEvent:
    """`DDS_ACKNOWLEDGED` (TRAINEE) — one per trainee action, whatever N is (R5).

    `latency_from_handoff_ms` is measured from the leg's `received_at_offset_ms`, i.e. from the
    moment `createHandoff` fanned the work item out; every leg carries the same value, so the
    primary one is the whole stage's answer.
    """
    primary = ctx.primary
    return DomainEvent(
        event_type=EventType.DDS_ACKNOWLEDGED,
        actor=ctx.actor,
        monotonic_offset_ms=ctx.now_ms,
        payload={
            "assignment_id": UUID(str(primary.assignment_id)),
            "at_offset_ms": ctx.now_ms,
            "latency_from_handoff_ms": max(0, ctx.now_ms - primary.received_at_offset_ms),
            "actor_user_id": UUID(str(ctx.actor.actor_id)),
        },
    )
