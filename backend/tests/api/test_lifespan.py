"""The lifespan starts and stops the `SimulationRunner`, leaving no task behind (D7, SPEC §39).

This is the one test in the suite that runs with `SIM_RUNNER_ENABLED=true`. It asserts the two
things that make the wiring trustworthy:

* on startup the runner **adopts every ACTIVE session from PostgreSQL** — D7's re-adoption, which
  is what makes a backend restart resume a running session rather than freeze it;
* on shutdown `asyncio.all_tasks()` is back to exactly the set it held before startup. A runner
  that leaked a task would leak one per session per test run, and the leak would surface as a
  flake in some unrelated test hours later.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from app.api.container import Container
from app.api.main import create_app
from app.application.testing.fakes import InMemoryRunnerLock
from app.domain.common.ids import ScenarioVersionId, UserId

from tests.api.conftest import auth, create_demo_session, participant

pytestmark = pytest.mark.integration


@pytest.fixture
def running_container(container: Container) -> Container:
    """The same container with the runner enabled and an in-memory lock.

    The lock is in memory because this test is about task lifecycle, not about Redis: a real
    `RedisRunnerLock` would make a leaked key from a previous run able to fail it.
    """
    return Container(
        container.settings.model_copy(update={"runner_enabled": True, "sim_tick_ms": 50}),
        engine=container.engine,
        session_factory=container.session_factory,
        redis=container.redis,
        unit_of_work=container.unit_of_work,
        hasher=container.hasher,
        tokens=container.tokens,
        inference=container.inference,
        runner_lock=InMemoryRunnerLock(),
        owns_engine=False,
        owns_redis=False,
    )


async def test_lifespan_starts_and_stops_the_runner_with_no_task_left(
    running_container: Container,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """Startup adopts the ACTIVE session; shutdown leaves the task set exactly as it was."""
    created = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee1"], "OPERATOR_112"), participant(users["trainee2"], "DDS")],
    )
    session_id = created["id"]
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "ACTIVE"

    before = asyncio.all_tasks()

    app = create_app(running_container)
    transport = httpx.ASGITransport(app=app)
    # `httpx.ASGITransport` does not send lifespan events, so the lifespan is entered explicitly
    # through Starlette's own context manager — the same one uvicorn drives in production.
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://api") as running,
    ):
        live = await running.get("/api/v1/health/live")
        assert live.status_code == 200
        # D7's re-adoption: the ACTIVE session was picked up from PostgreSQL at startup.
        assert running_container.runner.adopted, "startup adopted no ACTIVE session"
        assert str(next(iter(running_container.runner.adopted))) == session_id

    # Give any still-cancelling task the one loop iteration it needs to disappear.
    await asyncio.sleep(0)
    after = asyncio.all_tasks()

    assert running_container.runner.adopted == frozenset()
    assert running_container.runner.held_locks == frozenset()
    leaked = {task for task in after - before if not task.done()}
    assert leaked == set(), f"the runner left {len(leaked)} task(s) behind: {leaked}"


async def test_lifespan_with_the_runner_disabled_starts_nothing(
    container: Container,
) -> None:
    """`SIM_RUNNER_ENABLED=false` adopts nothing — the API-test default (no task outlives)."""
    before = asyncio.all_tasks()

    app = create_app(container)
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://api") as client,
    ):
        assert (await client.get("/api/v1/health/live")).status_code == 200
        assert container.runner.adopted == frozenset()

    await asyncio.sleep(0)
    leaked = {task for task in asyncio.all_tasks() - before if not task.done()}
    assert leaked == set()
