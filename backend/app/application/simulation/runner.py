"""`SimulationRunner` — one asyncio task per ACTIVE session (D7, HLD §40.6, SPEC §12, §39).

D7: "`SimulationRunner` (application, asyncio): one task per ACTIVE session, ticks every
`SIM_TICK_MS` (default 500) and immediately after each command. On backend start it re-adopts all
ACTIVE sessions from PostgreSQL […] A Redis lock `lock:session:{id}:runner` guarantees a single
runner."

Five properties this implementation is built around:

* **Adoption is a read, not a handover.** `start()` asks the session repository for every `ACTIVE`
  session id and adopts each; that is the `40-realtime-protocol.md` "Backend restart" paragraph,
  and it is also what makes a second instance take over a session whose lock expired.
* **A runner that does not hold the lock does not tick.** The lock is taken before the first tick
  and refreshed every `lock_refresh_s`; when a refresh returns `False` the instance has lost the
  session (another instance adopted it) and its task stops ticking that session immediately,
  without touching the lock it no longer owns.
* **One session's failure never reaches another's.** Every exception inside a tick is logged and
  the loop continues; the task ends only on cancellation. Losing a tick costs liveness, never
  correctness — the next tick derives its effects from the same persisted state.
* **Ticking is idempotent.** Two instances that briefly overlap cannot corrupt anything: the
  session row lock of §20.8 serialises them and an unchanged tick writes nothing.
* **`stop()` leaves nothing behind.** Every task is cancelled *and awaited*, and every lock this
  instance still owns is released.

**`after_tick` is a seam, not a dependency.** Some stage triggers are fired by the simulation
rather than by a trainee — `ring` when the caller joins the transport, `begin_interview` when the
first `ASR_FINAL` lands (§10.8, both `allowed_actors = {SIMULATION}`). They belong to the
simulation loop, and they are injected as hooks instead of imported: this module must stay free of
`app.application.operator`, so that "the loop drives the call flow" is a wiring fact of the
composition root and not a knot between two packages. `backend/tests/unit/application/simulation/`
scans this module's imports and fails if the knot appears.

Each hook runs after `tick_session` in its own `try`/`except`: a hook that raises is logged and
the remaining hooks still run, exactly as a failing tick never stops the loop. `tick_now` runs
them too, because D7's "immediately after each command" must advance the call flow as promptly as
the interval tick does.

Starting the runner from the FastAPI lifespan, and calling `tick_now(session_id)` immediately
after each command, are E7's wiring — this module deliberately does not import `app.api`, and
`start_session` (E5-B) deliberately does not import this module.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from app.application.ports.runner_lock import RunnerLock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.simulation.tick_session import TickResult, TickSession
from app.domain.common.ids import SessionId

__all__ = ["SimulationRunner"]

logger = logging.getLogger(__name__)


class SimulationRunner:
    """One asyncio task per adopted session, each ticking `tick_session` on an interval."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        tick_session: TickSession,
        lock: RunnerLock,
        *,
        instance_id: str,
        tick_ms: int,
        lock_ttl_s: int,
        lock_refresh_s: int,
        after_tick: Sequence[Callable[[SessionId], Awaitable[object]]] = (),
    ) -> None:
        #: Ran after every tick of a session, each in its own try/except (see the docstring).
        self._after_tick = tuple(after_tick)
        self._unit_of_work = unit_of_work
        self._tick_session = tick_session
        self._lock = lock
        #: The value written into `lock:session:{id}:runner` — this backend instance (§40.6).
        self._instance_id = instance_id
        self._tick_ms = tick_ms
        self._lock_ttl_s = lock_ttl_s
        self._lock_refresh_s = lock_refresh_s
        self._tasks: dict[SessionId, asyncio.Task[None]] = {}
        self._held: set[SessionId] = set()
        self._stopping = False

    # -- lifecycle -----------------------------------------------------------------------------

    async def start(self) -> list[SessionId]:
        """Re-adopt every `ACTIVE` session from PostgreSQL; returns the ids adopted."""
        self._stopping = False
        async with self._unit_of_work() as uow:
            session_ids = await uow.sessions.list_active_session_ids()
            await uow.commit()
        for session_id in session_ids:
            self.adopt(session_id)
        return session_ids

    def adopt(self, session_id: SessionId) -> None:
        """Start this session's tick task; adopting an already-adopted session is a no-op."""
        if self._stopping or session_id in self._tasks:
            return
        self._tasks[session_id] = asyncio.create_task(
            self._run(session_id), name=f"sim-runner:{session_id}"
        )

    async def release(self, session_id: SessionId) -> None:
        """Stop ticking this session and give up its lock, so another instance may adopt it."""
        task = self._tasks.pop(session_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._release_lock(session_id)

    async def stop(self) -> None:
        """Cancel and await every task, then release every lock this instance still holds."""
        self._stopping = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        for session_id in list(self._held):
            await self._release_lock(session_id)

    @property
    def adopted(self) -> frozenset[SessionId]:
        """The sessions this instance currently has a task for."""
        return frozenset(self._tasks)

    @property
    def held_locks(self) -> frozenset[SessionId]:
        """The sessions whose runner lock this instance currently holds."""
        return frozenset(self._held)

    # -- ticking -------------------------------------------------------------------------------

    async def tick_now(self, session_id: SessionId) -> TickResult:
        """Tick once, immediately — D7's "and immediately after each command".

        It does not require the lock: a command is already serialised against the tick loop by the
        session row lock of §20.8, and making a command wait for a lock another instance holds
        would make the command's own effects invisible until that instance's next tick.

        The `after_tick` hooks run here too: a command that made a simulation trigger due — the
        `CALL_ANSWERED` that leaves the stage `CONNECTED`, say — must not wait a whole interval
        for the loop to notice.
        """
        result = await self._tick_session(session_id)
        await self._run_hooks(session_id)
        return result

    async def _run_hooks(self, session_id: SessionId) -> None:
        """Run every `after_tick` hook, each isolated: one failure never skips the others."""
        for hook in self._after_tick:
            try:
                await hook(session_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "an after-tick hook of session %s failed; the loop continues", session_id
                )

    async def _run(self, session_id: SessionId) -> None:
        """One session's loop: acquire, then tick every `tick_ms` while the lock is held."""
        interval = self._tick_ms / 1000
        if not await self._acquire(session_id):
            logger.info(
                "session %s is already ticked by another instance; not adopting", session_id
            )
            return
        refresh_after = self._lock_refresh_s
        elapsed = 0.0
        try:
            while True:
                await self._tick_once(session_id)
                await asyncio.sleep(interval)
                elapsed += interval
                if elapsed >= refresh_after:
                    elapsed = 0.0
                    if not await self._refresh(session_id):
                        logger.warning(
                            "session %s: runner lock lost; this instance stops ticking it",
                            session_id,
                        )
                        return
        except asyncio.CancelledError:
            raise

    async def _tick_once(self, session_id: SessionId) -> None:
        """One tick; an exception is logged and swallowed so the other sessions keep running."""
        try:
            await self._tick_session(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("tick of session %s failed; the loop continues", session_id)
        await self._run_hooks(session_id)

    # -- lock ----------------------------------------------------------------------------------

    async def _acquire(self, session_id: SessionId) -> bool:
        taken = await self._lock.acquire(session_id, self._instance_id, self._lock_ttl_s)
        if taken:
            self._held.add(session_id)
        return taken

    async def _refresh(self, session_id: SessionId) -> bool:
        held = await self._lock.refresh(session_id, self._instance_id, self._lock_ttl_s)
        if not held:
            self._held.discard(session_id)
        return held

    async def _release_lock(self, session_id: SessionId) -> None:
        if session_id not in self._held:
            return
        self._held.discard(session_id)
        try:
            await self._lock.release(session_id, self._instance_id)
        except Exception:  # Redis is non-authoritative (§40.6); the TTL frees the key anyway
            logger.exception("releasing the runner lock of session %s failed", session_id)
