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

`openapi.yaml` also says the backend publishes `voice:cancel:{session_id}` so an in-flight caller
response is cancelled across processes (D9). That signal is published **after** the Unit of Work
commits: a cancel that escaped before its transaction could stop a caller utterance for a
`CALL_ENDED` a rollback then erased. §40.6 makes its loss harmless in the other direction too —
"the caller finishes one utterance into a closed call; no state is corrupted" — so a Redis that is
down never fails a hang-up. The event this command appends remains what the fold and the guards
read; the signal only saves the caller from talking to nobody.

§40.6's `reason` enum for that channel is `HANGUP | ABORT | TRANSPORT_LOST`, which is *not*
`EndCallRequest.reason` (`OPERATOR_HANGUP | CALLER_HANGUP | TRANSPORT_LOST`).
`_CANCEL_REASON_BY_END_REASON` below is the mapping, written once: both hang-up reasons are a
`HANGUP` to the agent, which only needs to know that the call is over, and `ABORT` belongs to
`abortSession`, not here.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import (
    ActionNotAvailableError,
    OperatorCommandGate,
)
from app.application.operator.views import (
    CallPhase,
    OperatorStageView,
    project_call_state,
    write_call_state_cache,
)
from app.application.ports.call_state_cache import CallStateCache
from app.application.ports.clock import Clock
from app.application.ports.id_generator import IdGenerator
from app.application.ports.voice_signal_publisher import VoiceSignalPublisher
from app.domain.common.ids import SessionId
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "END_CALL_REASONS", "EndCall"]

ACTION_ID = "end_call"
"""`openapi.yaml`'s `x-action` for `endCall`."""

END_CALL_REASONS: tuple[str, ...] = ("OPERATOR_HANGUP", "CALLER_HANGUP", "TRANSPORT_LOST")
"""`openapi.yaml`'s `EndCallRequest.reason` enum, exact."""

_CANCEL_REASON_BY_END_REASON: dict[str, str] = {
    "OPERATOR_HANGUP": "HANGUP",
    "CALLER_HANGUP": "HANGUP",
    "TRANSPORT_LOST": "TRANSPORT_LOST",
}
"""`EndCallRequest.reason` -> §40.6's `voice:cancel` `reason`; see this module's docstring."""


class EndCall:
    """`endCall` (`openapi.yaml`): end the call without moving the stage."""

    def __init__(
        self,
        gate: OperatorCommandGate,
        ids: IdGenerator,
        clock: Clock | None = None,
        voice_signals: VoiceSignalPublisher | None = None,
        call_state_cache: CallStateCache | None = None,
    ) -> None:
        self._gate = gate
        self._ids = ids
        self._clock = clock
        self._voice_signals = voice_signals
        self._call_state_cache = call_state_cache

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
            view = ctx.stage_view(await ctx.card())
            cancelled_call_id = UUID(str(call_id))
            cancelled_at_ms = ctx.now_ms
        # The gate committed when the block above closed. Both side effects happen only now.
        if self._voice_signals is not None:
            await self._voice_signals.publish_cancel(
                session_id,
                call_id=cancelled_call_id,
                reason=_CANCEL_REASON_BY_END_REASON.get(reason, "HANGUP"),
                at_offset_ms=cancelled_at_ms,
            )
        if self._clock is not None:
            await write_call_state_cache(
                self._call_state_cache, session_id, view.call_state, self._clock.now()
            )
        return view
