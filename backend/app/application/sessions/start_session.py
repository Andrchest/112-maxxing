"""`StartSession` — `READY --start--> ACTIVE` (E5, §10.8, D5, D8).

One Unit of Work transaction: take the `SELECT … FOR UPDATE` row lock through `get_for_update`,
project the `GuardRuntime` from the session's event log, fire `start` on the aggregate, write the
new aggregate back and append the events the transition produced (`SESSION_STARTED`, then
`ROLE_STAGE_STARTED` for the first stage).

`require_inference_ready` (D8) reaches this use case as a **constructor argument**: the
application layer never imports `app.config`, so the composition root reads `Settings` and passes
the flag in. When it is false the readiness port is not even consulted — that is what D8's "the
application collapses both into the flag" means, and it is why a dev box without an inference
stack can still run a session.

An illegal `start` (wrong state, wrong actor, inference not ready) raises `InvalidTransitionError`
*before* anything is written, and the transaction is never committed: no state change, no event.
"""

from __future__ import annotations

from app.application.ports.clock import Clock
from app.application.ports.inference_readiness import InferenceReadiness
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.guard_context import build_guard_runtime
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId
from app.domain.session.session import SimulationSession

__all__ = ["SessionNotFoundError", "StartSession"]


class SessionNotFoundError(DomainError):
    """No `simulation_sessions` row with the requested id (`openapi.yaml`, `404 NOT_FOUND`)."""

    code = "NOT_FOUND"

    def __init__(self, session_id: SessionId) -> None:
        self.session_id = session_id
        super().__init__(f"no session {session_id}")


class StartSession:
    """Start a session that is `READY`."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        inference: InferenceReadiness,
        *,
        require_inference_ready: bool,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._inference = inference
        #: D8's `REQUIRE_INFERENCE_READY`, injected — never read from `app.config` here.
        self._require_inference_ready = require_inference_ready

    async def __call__(self, session_id: SessionId, actor: ActorRef) -> SimulationSession:
        """Fire `start`; returns the `ACTIVE` aggregate or raises `InvalidTransitionError`."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)

            runtime = build_guard_runtime(
                await uow.events.read(session_id),
                scenario_valid=True,
                inference_ready=await self._inference_ready(),
            )
            # `now_ms=0`: the start *is* the origin every later offset is measured from
            # (`session_offset_ms(now, started_at)` with `now == started_at`), so it is written
            # literally here rather than read from a counter — SPEC §39, D7.
            started, events = session.start(
                self._clock.now(), actor=actor, now_ms=0, runtime=runtime
            )

            await uow.sessions.save(started)
            await uow.events.append(session_id, events)
            await uow.commit()
        return started

    # -- internals ----------------------------------------------------------------------------

    async def _inference_ready(self) -> bool:
        """`REQUIRE_INFERENCE_READY is false` **or** every component reports `READY` (D8)."""
        if not self._require_inference_ready:
            return True
        return await self._inference.is_ready()
