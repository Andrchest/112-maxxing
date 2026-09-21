"""`answerCall` — `RINGING --answer--> CONNECTED` (`openapi.yaml`, §10.8, D8).

A *transition* command: it goes through `SimulationSession.fire_stage_trigger`, so the
`answer` row of `OPERATOR_112_TRANSITIONS` decides — actor `TRAINEE`, role `OPERATOR_112`, guard
`guard_participant_assigned_to_stage`. A guard denial is `InvalidTransitionError`, which
`app.api.errors` renders as `409 INVALID_TRANSITION` (D8).

`fire_stage_trigger` emits `STAGE_STATE_CHANGED` and leaves the transition's own
`Transition.emits` event to the owning use case (its deferral note), because the payload needs the
call id and the ring duration, which the aggregate does not hold. This module is that use case:
it appends `CALL_ANSWERED` before `STAGE_STATE_CHANGED`, which is the order `openapi.yaml`'s
`x-emits` lists for this operation.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import OperatorCommandGate
from app.application.operator.views import OperatorStageView, project_call_state
from app.application.ports.id_generator import IdGenerator
from app.domain.common.ids import SessionId
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "AnswerCall"]

ACTION_ID = "answer"
"""`openapi.yaml`'s `x-action` for `answerCall`."""


class AnswerCall:
    """`answerCall` (`openapi.yaml`): answer the ringing call."""

    def __init__(self, gate: OperatorCommandGate, ids: IdGenerator) -> None:
        self._gate = gate
        self._ids = ids

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> OperatorStageView:
        """Fire `answer`, emit `CALL_ANSWERED` then `STAGE_STATE_CHANGED`, return the new view."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            call = project_call_state(ctx.full_log)
            # `RINGING` is only ever reached through `ring`, which emits `CALL_RINGING` with a
            # `call_id`; a fresh id is the honest fallback for a log that somehow lacks it, since
            # `CALL_ANSWERED.call_id` is a required payload key of the §10.13 catalog.
            call_id = call.call_id if call.call_id is not None else self._ids.new()
            ring_started = (
                call.started_at_offset_ms if call.started_at_offset_ms is not None else ctx.now_ms
            )
            session, stage_events = ctx.session.fire_stage_trigger(
                ctx.stage.role_stage_id,
                ACTION_ID,
                actor=ctx.actor,
                now_ms=ctx.now_ms,
                runtime=ctx.guard_runtime(),
            )
            await ctx.save_session(session)
            answered = DomainEvent(
                event_type=EventType.CALL_ANSWERED,
                actor=ctx.actor,
                monotonic_offset_ms=ctx.now_ms,
                payload={
                    "call_id": UUID(str(call_id)),
                    "at_offset_ms": ctx.now_ms,
                    "ring_duration_ms": max(0, ctx.now_ms - ring_started),
                    "answered_by_user_id": UUID(str(user.user_id)),
                },
            )
            await ctx.append([answered, *stage_events])
            return ctx.stage_view(await ctx.card())
