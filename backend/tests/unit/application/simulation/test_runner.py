"""`SimulationRunner` — adoption, the single-runner lock and failure isolation (D7, §40.6).

Nothing here touches PostgreSQL or Redis: the runner's job is task and lock choreography, and the
tick itself is covered by `tests/integration/simulation`. The fakes make every assertion exact and
the tests wait on `asyncio.Event`s rather than sleeping for a tick interval, so the whole file runs
in milliseconds.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from app.application.simulation.runner import SimulationRunner
from app.application.simulation.tick_session import TickResult
from app.application.testing.fakes import InMemoryRunnerLock
from app.domain.common.ids import SessionId

SESSION_A = SessionId(UUID("00000000-0000-4000-8000-00000000000a"))
SESSION_B = SessionId(UUID("00000000-0000-4000-8000-00000000000b"))

TIMEOUT = 2.0
"""Generous, because it is only ever reached when something is genuinely broken."""

YIELD_BUDGET = 20_000
"""How many event-loop yields `wait_for` gives a condition before declaring the runner stuck."""


class FakeTick:
    """A stand-in for `TickSession`: counts calls, can raise, and signals the first tick."""

    def __init__(self, fail_for: set[SessionId] | None = None) -> None:
        self.counts: dict[SessionId, int] = {}
        self.fail_for = fail_for or set()
        self.ticked: dict[SessionId, asyncio.Event] = {}

    def event(self, session_id: SessionId) -> asyncio.Event:
        return self.ticked.setdefault(session_id, asyncio.Event())

    async def __call__(self, session_id: SessionId) -> TickResult:
        self.counts[session_id] = self.counts.get(session_id, 0) + 1
        self.event(session_id).set()
        if session_id in self.fail_for:
            raise RuntimeError(f"tick of {session_id} exploded")
        return TickResult(ticked=True)


class FakeUnitOfWork:
    """Only `sessions.list_active_session_ids` and `commit` are reachable from the runner."""

    def __init__(self, active: list[SessionId]) -> None:
        self.sessions = _FakeSessions(active)

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def commit(self) -> None:
        return None


class _FakeSessions:
    def __init__(self, active: list[SessionId]) -> None:
        self.active = active

    async def list_active_session_ids(self) -> list[SessionId]:
        return list(self.active)


def build(
    tick: FakeTick,
    lock: InMemoryRunnerLock,
    *,
    instance_id: str = "instance-a",
    active: list[SessionId] | None = None,
    tick_ms: int = 1,
    lock_refresh_s: int = 3600,
) -> SimulationRunner:
    return SimulationRunner(
        lambda: FakeUnitOfWork(active or []),  # type: ignore[arg-type, return-value]
        tick,  # type: ignore[arg-type]
        lock,
        instance_id=instance_id,
        tick_ms=tick_ms,
        lock_ttl_s=30,
        lock_refresh_s=lock_refresh_s,
    )


async def wait_for(condition: Any) -> None:
    """Yield to the event loop until `condition()` holds.

    `asyncio.sleep(0)` here is a *yield*, not a wait: it hands control to the runner's tasks and
    comes straight back, so the poll costs no real time. An `asyncio.Event` cannot express these
    conditions — they are about the runner's own observable state (`held_locks`, the lock's call
    log), not about something the test itself signals — and the bounded loop turns a runner that
    never gets there into a named failure rather than a hang.
    """
    for _ in range(YIELD_BUDGET):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"the condition never held within {YIELD_BUDGET} event-loop yields")


# ---------------------------------------------------------------------------------------------
# Adoption
# ---------------------------------------------------------------------------------------------


async def test_start_re_adopts_every_active_session() -> None:
    """`40-realtime-protocol.md` "Backend restart": every ACTIVE session is re-adopted."""
    tick, lock = FakeTick(), InMemoryRunnerLock()
    runner = build(tick, lock, active=[SESSION_A, SESSION_B])
    try:
        adopted = await runner.start()
        assert adopted == [SESSION_A, SESSION_B]
        assert runner.adopted == frozenset({SESSION_A, SESSION_B})
        await asyncio.wait_for(tick.event(SESSION_A).wait(), TIMEOUT)
        await asyncio.wait_for(tick.event(SESSION_B).wait(), TIMEOUT)
        assert runner.held_locks == frozenset({SESSION_A, SESSION_B})
    finally:
        await runner.stop()


async def test_adopting_the_same_session_twice_starts_one_task() -> None:
    tick, lock = FakeTick(), InMemoryRunnerLock()
    runner = build(tick, lock)
    try:
        runner.adopt(SESSION_A)
        runner.adopt(SESSION_A)
        assert runner.adopted == frozenset({SESSION_A})
        await asyncio.wait_for(tick.event(SESSION_A).wait(), TIMEOUT)
        assert len([call for call in lock.calls if call[0] == "acquire"]) == 1
    finally:
        await runner.stop()


async def test_stop_cancels_every_task_and_releases_every_lock() -> None:
    """ "Leave no asyncio task behind": `stop` cancels *and awaits*, then gives the locks back."""
    tick, lock = FakeTick(), InMemoryRunnerLock()
    runner = build(tick, lock, active=[SESSION_A, SESSION_B])
    await runner.start()
    await asyncio.wait_for(tick.event(SESSION_A).wait(), TIMEOUT)
    await runner.stop()

    assert runner.adopted == frozenset()
    assert runner.held_locks == frozenset()
    assert lock.owners == {}
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("sim-runner:")]


# ---------------------------------------------------------------------------------------------
# The single-runner lock (D7)
# ---------------------------------------------------------------------------------------------


async def test_only_one_of_two_runners_sharing_a_lock_ticks_a_session() -> None:
    tick_a, tick_b = FakeTick(), FakeTick()
    lock = InMemoryRunnerLock()
    first = build(tick_a, lock, instance_id="instance-a")
    second = build(tick_b, lock, instance_id="instance-b")
    try:
        first.adopt(SESSION_A)
        await asyncio.wait_for(tick_a.event(SESSION_A).wait(), TIMEOUT)

        second.adopt(SESSION_A)
        await wait_for(lambda: ("acquire", SESSION_A, "instance-b") in lock.calls)
        await asyncio.sleep(0.01)

        assert tick_b.counts == {}
        assert first.held_locks == frozenset({SESSION_A})
        assert second.held_locks == frozenset()
        assert lock.owners == {SESSION_A: "instance-a"}
    finally:
        await first.stop()
        await second.stop()


async def test_after_a_release_the_other_instance_adopts_the_session() -> None:
    tick_a, tick_b = FakeTick(), FakeTick()
    lock = InMemoryRunnerLock()
    first = build(tick_a, lock, instance_id="instance-a")
    second = build(tick_b, lock, instance_id="instance-b")
    try:
        first.adopt(SESSION_A)
        await asyncio.wait_for(tick_a.event(SESSION_A).wait(), TIMEOUT)

        await first.release(SESSION_A)
        assert lock.owners == {}
        assert first.adopted == frozenset()

        second.adopt(SESSION_A)
        await asyncio.wait_for(tick_b.event(SESSION_A).wait(), TIMEOUT)
        assert lock.owners == {SESSION_A: "instance-b"}
    finally:
        await first.stop()
        await second.stop()


async def test_after_the_ttl_expires_the_other_instance_adopts_the_session() -> None:
    """A lapsed TTL is what §40.6 says makes a dead instance's session adoptable again."""
    tick_a, tick_b = FakeTick(), FakeTick()
    lock = InMemoryRunnerLock()
    first = build(tick_a, lock, instance_id="instance-a")
    second = build(tick_b, lock, instance_id="instance-b")
    try:
        first.adopt(SESSION_A)
        await asyncio.wait_for(tick_a.event(SESSION_A).wait(), TIMEOUT)

        lock.expire(SESSION_A)  # the TTL ran out; instance-a has not noticed yet
        second.adopt(SESSION_A)
        await asyncio.wait_for(tick_b.event(SESSION_A).wait(), TIMEOUT)
        assert lock.owners == {SESSION_A: "instance-b"}
    finally:
        await first.stop()
        await second.stop()


async def test_a_runner_that_loses_the_lock_stops_ticking_that_session() -> None:
    """A refresh returning `False` means another instance owns the session now (D7)."""
    tick, lock = FakeTick(), InMemoryRunnerLock()
    runner = build(tick, lock, instance_id="instance-a", lock_refresh_s=0)
    try:
        runner.adopt(SESSION_A)
        await asyncio.wait_for(tick.event(SESSION_A).wait(), TIMEOUT)

        lock.owners[SESSION_A] = "instance-b"  # taken over after a lapsed TTL
        await wait_for(lambda: runner.held_locks == frozenset())

        stopped_at = tick.counts[SESSION_A]
        await asyncio.sleep(0.02)
        assert tick.counts[SESSION_A] == stopped_at
        # It stopped ticking, and it did not steal the lock back from instance-b.
        assert lock.owners == {SESSION_A: "instance-b"}
    finally:
        await runner.stop()
        assert lock.owners == {SESSION_A: "instance-b"}


# ---------------------------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------------------------


async def test_an_exception_in_one_session_tick_does_not_stop_another() -> None:
    tick = FakeTick(fail_for={SESSION_A})
    lock = InMemoryRunnerLock()
    runner = build(tick, lock, active=[SESSION_A, SESSION_B])
    try:
        await runner.start()
        await wait_for(lambda: tick.counts.get(SESSION_B, 0) >= 3)
        assert tick.counts.get(SESSION_A, 0) >= 3, "the failing loop must keep retrying"
        assert runner.adopted == frozenset({SESSION_A, SESSION_B})
    finally:
        await runner.stop()


async def test_tick_now_runs_one_tick_without_requiring_the_lock() -> None:
    """D7's "and immediately after each command" — the caller is E7 (`TODO(E7)`)."""
    tick, lock = FakeTick(), InMemoryRunnerLock()
    runner = build(tick, lock)
    result = await runner.tick_now(SESSION_A)
    assert result.ticked is True
    assert tick.counts == {SESSION_A: 1}
    assert lock.calls == []


async def test_adopting_after_stop_is_refused() -> None:
    """`stop()` is final for this runner: a late `adopt` must not resurrect a task."""
    tick, lock = FakeTick(), InMemoryRunnerLock()
    runner = build(tick, lock)
    await runner.stop()
    runner.adopt(SESSION_A)
    assert runner.adopted == frozenset()


@pytest.mark.parametrize("ttl_s", [30])
async def test_the_lock_is_taken_with_the_configured_ttl(ttl_s: int) -> None:
    """`SIM_RUNNER_LOCK_TTL_S` reaches the port; `Settings` defaults it to 30 (§40.6)."""
    from app.config.settings import Settings

    assert Settings.model_fields["sim_runner_lock_ttl_s"].default == ttl_s
    assert Settings.model_fields["sim_runner_lock_refresh_s"].default == 10
