"""`endCall` — hang up (`openapi.yaml`, §10.8, SPEC §7).

**Not a transition.** `openapi.yaml` says so ("Not a stage transition of its own") and §10.9
agrees: `end_call` is an `ActionDescriptor` with `trigger = None`. Ending the call is the
*precondition* of `complete_stage` (guard `guard_call_ended`), so this command appends
`CALL_ENDED` — its whole `x-emits` — and leaves the stage exactly where it was. The stage moves
later, when the trainee completes the stage (E9).

Ending an already-ended call is refused with `409 ACTION_NOT_AVAILABLE`: `end_call` stays in
`available_actions` for every state from `CONNECTED` to `HANDED_OFF` (§10.9 lists it there), so
the "no call to end" case cannot be expressed by that table and is decided here, against the
authoritative fold of the log. That keeps a double hang-up from writing a second `CALL_ENDED`,
which would otherwise show up in the report as two calls.

TODO(E11): `openapi.yaml` also says the backend publishes `voice:cancel:{session_id}` so an
in-flight caller response is cancelled across processes (D9). That channel belongs to the voice
transport slice; the event this command appends is what the fold and the guards read, and it is
complete without it.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import (
    ActionNotAvailableError,
    OperatorCommandGate,
)
from app.application.operator.views import CallPhase, OperatorStageView, project_call_state
from app.application.ports.id_generator import IdGenerator
from app.domain.common.ids import SessionId
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "END_CALL_REASONS", "EndCall"]

ACTION_ID = "end_call"
"""`openapi.yaml`'s `x-action` for `endCall`."""

END_CALL_REASONS: tuple[str, ...] = ("OPERATOR_HANGUP", "CALLER_HANGUP", "TRANSPORT_LOST")
"""`openapi.yaml`'s `EndCallRequest.reason` enum, exact."""


class EndCall:
    """`endCall` (`openapi.yaml`): end the call without moving the stage."""

    def __init__(self, gate: OperatorCommandGate, ids: IdGenerator) -> None:
        self._gate = gate
        self._ids = ids

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, reason: str
    ) -> OperatorStageView:
        """Append `CALL_ENDED`; refuse when there is no live call to end."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            call = project_call_state(ctx.full_log)
            if call.phase in (CallPhase.NO_CALL, CallPhase.ENDED):
                raise ActionNotAvailableError(ACTION_ID, ctx.stage_state)
            call_id = call.call_id if call.call_id is not None else self._ids.new()
            started = (
                call.answered_at_offset_ms
                if call.answered_at_offset_ms is not None
                else call.started_at_offset_ms
            )
            ended = DomainEvent(
                event_type=EventType.CALL_ENDED,
                actor=ctx.actor,
                monotonic_offset_ms=ctx.now_ms,
                payload={
                    "call_id": UUID(str(call_id)),
                    "at_offset_ms": ctx.now_ms,
                    "duration_ms": max(0, ctx.now_ms - (started if started is not None else 0)),
                    "ended_by": ctx.actor.actor_type.value,
                    "reason": reason,
                },
            )
            await ctx.append([ended])
            return ctx.stage_view(await ctx.card())
