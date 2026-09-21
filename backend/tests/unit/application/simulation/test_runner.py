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
    """D7's "and immediately after each command": `app.api.deps.tick_after_command` calls it."""
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


# ---------------------------------------------------------------------------------------------
# `after_tick` — the seam the call flow is injected through (E7-B DESIGN 5, D7)
# ---------------------------------------------------------------------------------------------


class FakeHook:
    """An `after_tick` hook: counts calls, can raise, and signals the first call."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[SessionId] = []
        self.fail = fail
        self.called = asyncio.Event()

    async def __call__(self, session_id: SessionId) -> bool:
        self.calls.append(session_id)
        self.called.set()
        if self.fail:
            raise RuntimeError("the hook exploded")
        return True


def build_with_hooks(
    tick: FakeTick, lock: InMemoryRunnerLock, *hooks: FakeHook
) -> SimulationRunner:
    return SimulationRunner(
        lambda: FakeUnitOfWork([]),  # type: ignore[arg-type, return-value]
        tick,  # type: ignore[arg-type]
        lock,
        instance_id="instance-a",
        tick_ms=1,
        lock_ttl_s=30,
        lock_refresh_s=3600,
        after_tick=hooks,
    )


async def test_an_after_tick_hook_runs_after_every_tick() -> None:
    """D7's simulation-driven triggers reach the session through this seam, not through imports."""
    tick, lock, hook = FakeTick(), InMemoryRunnerLock(), FakeHook()
    runner = build_with_hooks(tick, lock, hook)
    try:
        runner.adopt(SESSION_A)
        await asyncio.wait_for(hook.called.wait(), TIMEOUT)
        assert hook.calls[0] == SESSION_A
    finally:
        await runner.stop()


async def test_tick_now_runs_the_hooks_too() -> None:
    """ "Immediately after each command" must advance the call flow immediately too."""
    tick, lock, hook = FakeTick(), InMemoryRunnerLock(), FakeHook()
    runner = build_with_hooks(tick, lock, hook)
    await runner.tick_now(SESSION_B)
    assert hook.calls == [SESSION_B]
    assert tick.counts[SESSION_B] == 1


async def test_a_failing_hook_neither_kills_the_loop_nor_skips_the_others() -> None:
    """Each hook is isolated: a raise is logged, the next hook still runs, the loop continues."""
    tick, lock = FakeTick(), InMemoryRunnerLock()
    failing, healthy = FakeHook(fail=True), FakeHook()
    runner = build_with_hooks(tick, lock, failing, healthy)
    try:
        runner.adopt(SESSION_A)
        await asyncio.wait_for(healthy.called.wait(), TIMEOUT)
        await wait_for(lambda: tick.counts.get(SESSION_A, 0) >= 2)
        assert failing.calls, "the failing hook was still called"
        assert healthy.calls, "the hook after it was not skipped"
    finally:
        await runner.stop()


async def test_a_failing_tick_still_runs_the_hooks() -> None:
    """The call flow reads persisted state, so a tick that blew up must not silence it."""
    tick, lock, hook = FakeTick(fail_for={SESSION_A}), InMemoryRunnerLock(), FakeHook()
    runner = build_with_hooks(tick, lock, hook)
    try:
        runner.adopt(SESSION_A)
        await asyncio.wait_for(hook.called.wait(), TIMEOUT)
    finally:
        await runner.stop()


async def test_no_hooks_is_the_default() -> None:
    """A runner built without the seam behaves exactly as it did before it existed."""
    tick, lock = FakeTick(), InMemoryRunnerLock()
    runner = build(tick, lock)
    await runner.tick_now(SESSION_A)
    assert tick.counts[SESSION_A] == 1


def test_the_runner_module_does_not_import_the_operator_package() -> None:
    """The seam exists so this import never appears (E7-B DESIGN 5).

    An `import` scan, not a convention: the moment `runner.py` reaches into
    `app.application.operator`, the simulation loop and the Operator 112 use cases are knotted
    together and the hook has stopped being a seam.
    """
    import ast
    from pathlib import Path

    source = Path(SimulationRunner.__module__.replace(".", "/") + ".py")
    root = Path(__file__).resolve().parents[4]
    tree = ast.parse((root / source).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    offenders = sorted(
        module for module in imported if module.startswith("app.application.operator")
    )
    assert not offenders, f"runner.py must not import {offenders}; the hook is injected"
