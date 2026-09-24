"""The FastAPI application factory (D8, D12, SPEC §34).

`create_app(container=None)` is the only way an application is built. It takes a `Container`
because that is what makes the whole API testable without patching: a test builds a container with
`FakeClock`, an `InMemoryEventPublisher` or a not-ready `FakeInferenceReadiness`, calls
`create_app(container)` and drives it through `httpx.ASGITransport` — binding no port at all.

The lifespan owns exactly four things, in this order on the way up and the reverse on the way
down:

1. the container goes on `app.state`, where `app.api.deps.get_container` finds it;
2. `runner.start()` — D7's "on backend start it re-adopts all ACTIVE sessions from PostgreSQL",
   which is what makes a backend restart resume every running session (SPEC §39). Skipped when
   `SIM_RUNNER_ENABLED=false`, which is how the API tests guarantee no background task outlives
   them;
3. `inference_health.start()` — the `voice:health` subscriber that turns a voice-agent readiness
   transition into an `INFERENCE_HEALTH_CHANGED` on every ACTIVE session (E18-B, HLD 60 §4.3).
   Gated on the same `SIM_RUNNER_ENABLED` flag, for the same reason;
4. on shutdown: `inference_health.stop()`, then `runner.stop()` (every task cancelled *and
   awaited*, every held lock released),
   then `container.aclose()` (the engine disposed, the Redis client closed).

`uvicorn app.api.main:create_app --factory` is what `make run-api` runs, on
`SIM_API_HOST` / `SIM_API_PORT` (default `127.0.0.1:8100` — loopback per SPEC §41).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.container import Container, build_container
from app.api.errors import install_exception_handlers
from app.api.routers import (
    admin,
    auth,
    dds,
    groups,
    health,
    incidents,
    instructor,
    lessons,
    operator,
    realtime,
    reference,
    reports,
    scenarios,
    sessions,
    snapshot,
    users,
)

__all__ = ["create_app"]

logger = logging.getLogger(__name__)

API_TITLE = "System-112 / DDS training simulator — backend API"
"""`openapi.yaml`'s `info.title`, literally."""

API_VERSION = "1.0.0"
"""`openapi.yaml`'s `info.version`, literally."""


def create_app(container: Container | None = None) -> FastAPI:
    """Build the application. `container` defaults to the production wiring (`build_container`).

    A container passed in is **not** closed by this function on failure to start — the lifespan
    owns it from the moment the application starts, and a caller that built one keeps the right to
    close it if the application is never started at all.
    """
    resolved = container if container is not None else build_container()

    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        summary="Commands and resources for the local emergency-response training simulator.",
        lifespan=_lifespan,
    )
    app.state.container = resolved

    if resolved.settings.cors_allow_origins:
        # D12: the Vite dev server runs on another origin. The compose deployment serves the
        # frontend from the same origin, so this is a development affordance — and it is an
        # allow-list of exact origins, never `*`, because the API is credentialed (SPEC §41).
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.settings.cors_allow_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    install_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(admin.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(scenarios.router)
    app.include_router(sessions.router)
    app.include_router(operator.router)
    app.include_router(dds.router)
    app.include_router(snapshot.router)
    app.include_router(realtime.router)
    app.include_router(reports.router)
    app.include_router(reports.audio_router)
    app.include_router(instructor.router)
    app.include_router(reference.router)
    app.include_router(lessons.router)
    app.include_router(lessons.instructor_router)
    app.include_router(incidents.router)
    app.include_router(groups.router)

    return app


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the `SimulationRunner`; stop it and release every resource on shutdown (D7)."""
    container: Container = app.state.container
    runner_enabled = container.settings.runner_enabled
    if runner_enabled:
        adopted = await container.runner.start()
        logger.info("simulation runner started; adopted %d active session(s)", len(adopted))
        # I3 E4a: the LessonRunner re-adopts every ACTIVE lesson (HLD 70 §70.3.3), same flag.
        lessons_adopted = await container.lesson_runner.start()
        logger.info("lesson runner started; adopted %d active lesson(s)", len(lessons_adopted))
        # E18-B: the `voice:health` tail, started next to the runner and gated on the same flag.
        # Both are long-lived background tasks over the same sessions, and an API test that wants
        # neither turns off one switch (`app.infrastructure.health.voice_health_subscriber`).
        await container.inference_health.start()
        logger.info("voice:health subscriber started")
    else:
        logger.info("simulation runner disabled (SIM_RUNNER_ENABLED=false)")
    try:
        yield
    finally:
        # `stop()` cancels *and awaits* every task and releases every lock this instance holds, so
        # `asyncio.all_tasks()` is back where it started by the time this returns.
        if runner_enabled:
            await container.inference_health.stop()
            await container.lesson_runner.stop()
            await container.runner.stop()
        await container.aclose()
