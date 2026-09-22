"""`AbortSession` — `CREATED | READY | ACTIVE | ROLE_TRANSITION --abort--> ABORTED` (§10.8, D5).

One Unit of Work transaction: `get_for_update`, fire `abort` on the aggregate, write it back,
append the events (one `STAGE_STATE_CHANGED` per stage the abort closed, then `SESSION_ABORTED`).

The incident is deliberately left open (SPEC §13): closing it belongs to the closing use case, and
SPEC §42 invariant 5 wants exactly one `incidents` row per session no matter how the session ends.

Aborting a `COMPLETED` or already-`ABORTED` session raises `InvalidTransitionError` before
anything is written, so nothing is saved and no event is appended.

The events are stamped with `app.application.simulation.sim_time.running_ms(session, now)` — ms
since the session's persisted `started_at` less the hand-over pauses it has banked, never a
process-monotonic counter — so an abort that follows a backend restart still lands at the right
point on the session's timeline (SPEC §39, D7, E17 R1), and aborting a session parked in
`ROLE_TRANSITION` lands on the frozen offset rather than after the pause. A session aborted before
it ever started has `started_at is None` and therefore offset `0`.

§40.6 lists `abortSession` as a publisher of `voice:cancel:{session_id}` with
`reason: "ABORT"` (D9): an instructor who aborts a running session must not leave the voice-agent
talking into it. The signal is published **after** the commit, like every other §40.6 publish, and
its loss is harmless by that section's own account — "the caller finishes one utterance into a
closed call; no state is corrupted" — so an unreachable Redis never fails an abort. A session with
no call in its log publishes nothing: there is no `call_id` to cancel.
"""

from __future__ import annotations

from app.application.operator.views import CallPhase, project_call_state
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.voice_signal_publisher import VoiceSignalPublisher
from app.application.sessions.guard_context import build_guard_runtime
from app.application.sessions.start_session import SessionNotFoundError
from app.application.simulation.sim_time import running_ms
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.session.session import SimulationSession

__all__ = ["AbortSession"]


class AbortSession:
    """Abort a running or not-yet-running session."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        voice_signals: VoiceSignalPublisher | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._voice_signals = voice_signals

    async def __call__(
        self, session_id: SessionId, actor: ActorRef, reason: str
    ) -> SimulationSession:
        """Fire `abort`; returns the `ABORTED` aggregate or raises `InvalidTransitionError`."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)

            log = await uow.events.read(session_id)
            runtime = build_guard_runtime(log, scenario_valid=True, inference_ready=False)
            now_ms = running_ms(session, self._clock.now())
            aborted, events = session.abort(reason, actor=actor, now_ms=now_ms, runtime=runtime)

            await uow.sessions.save(aborted)
            await uow.events.append(session_id, events)
            await uow.commit()
            call = project_call_state(log)

        # After the commit, never inside it (§40.6).
        if self._voice_signals is not None and call.call_id is not None and call.phase in _LIVE:
            await self._voice_signals.publish_cancel(
                session_id, call_id=call.call_id, reason="ABORT", at_offset_ms=now_ms
            )
        return aborted


_LIVE = frozenset({CallPhase.RINGING, CallPhase.CONNECTED})
"""The phases in which a caller can still be talking, and so the only ones worth cancelling."""
