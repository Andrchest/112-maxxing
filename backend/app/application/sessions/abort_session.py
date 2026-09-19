"""`AbortSession` — `CREATED | READY | ACTIVE | ROLE_TRANSITION --abort--> ABORTED` (§10.8, D5).

One Unit of Work transaction: `get_for_update`, fire `abort` on the aggregate, write it back,
append the events (one `STAGE_STATE_CHANGED` per stage the abort closed, then `SESSION_ABORTED`).

The incident is deliberately left open (SPEC §13): closing it belongs to the closing use case, and
SPEC §42 invariant 5 wants exactly one `incidents` row per session no matter how the session ends.

Aborting a `COMPLETED` or already-`ABORTED` session raises `InvalidTransitionError` before
anything is written, so nothing is saved and no event is appended.

The events are stamped with `session_offset_ms(clock.now(), session.started_at)` — ms since the
session's persisted `started_at`, never a process-monotonic counter — so an abort that follows a
backend restart still lands at the right point on the session's timeline (SPEC §39, D7). A session
aborted before it ever started has `started_at is None` and therefore offset `0`.
"""

from __future__ import annotations

from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.guard_context import build_guard_runtime
from app.application.sessions.start_session import SessionNotFoundError
from app.application.timebase import session_offset_ms
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.session.session import SimulationSession

__all__ = ["AbortSession"]


class AbortSession:
    """Abort a running or not-yet-running session."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, session_id: SessionId, actor: ActorRef, reason: str
    ) -> SimulationSession:
        """Fire `abort`; returns the `ABORTED` aggregate or raises `InvalidTransitionError`."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)

            runtime = build_guard_runtime(
                await uow.events.read(session_id), scenario_valid=True, inference_ready=False
            )
            now_ms = session_offset_ms(self._clock.now(), session.started_at)
            aborted, events = session.abort(reason, actor=actor, now_ms=now_ms, runtime=runtime)

            await uow.sessions.save(aborted)
            await uow.events.append(session_id, events)
            await uow.commit()
        return aborted
