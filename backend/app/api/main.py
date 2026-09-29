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

I4 E25 (`71-i4-wave4.md` §71.2, D31) adds two things here: `AuditMiddleware`, which writes one
`audit_log` entry per request after its response, and the process logging — `create_app()` for
production (no container passed) re-points uvicorn's loggers and the app's own at the JSON
formatter (`SIM_LOG_FORMAT`, `SIM_LOG_DIR`) once uvicorn has applied its default `log_config`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.audit import (
    AUDIT_RECORDED_KEY,
    AUDIT_USER_KEY,
    AUDIT_WS_REFUSED_KEY,
    scope_state,
)
from app.api.container import Container, build_container, configure_process_logging
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
    materials,
    operator,
    realtime,
    reference,
    reports,
    scenarios,
    sessions,
    snapshot,
    statistics,
    telephony,
    users,
)
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.audit_changes import AuditChange, AuditChangeScope
from app.application.ports.audit_log import AuditAction, AuditEntry, AuditOutcome

__all__ = ["AuditMiddleware", "create_app"]

logger = logging.getLogger(__name__)

API_TITLE = "System-112 / DDS training simulator — backend API"
"""`openapi.yaml`'s `info.title`, literally."""

API_VERSION = "1.0.0"
"""`openapi.yaml`'s `info.version`, literally."""


def create_app(
    container: Container | None = None, *, configure_logging: bool | None = None
) -> FastAPI:
    """Build the application. `container` defaults to the production wiring (`build_container`).

    A container passed in is **not** closed by this function on failure to start — the lifespan
    owns it from the moment the application starts, and a caller that built one keeps the right to
    close it if the application is never started at all.

    `configure_logging` (I4 E25) defaults to "only for the production wiring": a test that hands in
    its own container keeps pytest's log capture untouched.
    """
    resolved = container if container is not None else build_container()
    if configure_logging if configure_logging is not None else container is None:
        configure_process_logging(resolved.settings)

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

    # I4 E25: one audit entry per request, written after the response (`AuditMiddleware`).
    app.add_middleware(AuditMiddleware)

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
    app.include_router(telephony.router)
    app.include_router(materials.router)
    # I4 E33: per-trainee statistics, own history and their CSV (`71-i4-wave4.md` §71.10).
    app.include_router(statistics.router)

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
    ml_worker = None
    if container.settings.ml_audit_auto_enabled and container.ml_audit_available:
        ml_worker = container.ml_audit_worker()
        await ml_worker.start()
    try:
        yield
    finally:
        if ml_worker is not None:
            await ml_worker.stop()
        # `stop()` cancels *and awaits* every task and releases every lock this instance holds, so
        # `asyncio.all_tasks()` is back where it started by the time this returns.
        if runner_enabled:
            await container.inference_health.stop()
            await container.lesson_runner.stop()
            await container.runner.stop()
        await container.aclose()


# ---------------------------------------------------------------------------------------------
# I4 E25 — the audit middleware (`71-i4-wave4.md` §71.2, HLD 20 §20.6 `audit_log`, D31)
# ---------------------------------------------------------------------------------------------

#: Only the API is audited, and not its readiness poll: the instructor page polls `/health/ready`
#: every `HEALTH_POLL_INTERVAL_MS` (§71.2), which would drown every real entry.
_AUDITED_PREFIX = "/api/"
_UNAUDITED_PREFIX = "/api/v1/health"
#: An unmatched path is stored as sent (there is no template); this bounds a hostile one.
_MAX_RAW_PATH_CHARS = 512
_DENIED_STATUSES = frozenset({401, 403})
#: §40.1's close codes that mean "not authenticated" / "not permitted" — a refused connect.
_WS_DENIED_CLOSE_CODES = frozenset({4401, 4403})
#: `status` of an accepted WebSocket (the handshake's `101 Switching Protocols`).
_WS_ACCEPTED_STATUS = 101
#: A socket closed before its accept reaches the client as an HTTP `403` (ASGI spec).
_WS_REFUSED_STATUS = 403
_SERVER_ERROR_STATUS = 500


class AuditMiddleware:
    """One `audit_log` entry per API request or WebSocket connect, written after the response.

    Pure ASGI (not `BaseHTTPMiddleware`), so it wraps WebSockets too and never buffers a body. It
    reads the scope only — path template, operationId, path parameters, method, status, client ip
    — and never a body, a header or a query string (§71.2, SPEC §41). What only the endpoint knows
    arrives through `app.api.audit` on the scope's `state`: the authenticated caller, "I recorded
    my own entry" (`loginUser`) and "this socket is a §40.1 refusal".

    * HTTP: `401`/`403` → `ACCESS_DENIED`/`DENIED`; anything else → `HTTP_REQUEST`, `OK` below 400
      and `ERROR` from 400 up. An exception that escapes is recorded as `500`/`ERROR` and re-raised.
    * WebSocket: recorded at the accept — `WS_CONNECTED`/`101`/`OK`, or, for a socket accepted only
      to deliver a close code, `ACCESS_DENIED` (`4401`, `4403`) or `WS_CONNECTED`/`ERROR` (`4404`)
      with the close code as `status`. A socket closed before any accept is `ACCESS_DENIED`/`403`.

    The recorder is read from the application's container per request (as `get_container` does),
    and its failures are the adapter's to log and swallow.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not _is_audited(scope):
            await self.app(scope, receive, send)
            return
        # The endpoint's `connection.state` wraps this very dict, so what it leaves there is
        # readable here after the call.
        scope.setdefault("state", {})
        if scope["type"] == "http":
            await self._http(scope, receive, send)
        else:
            await self._websocket(scope, receive, send)

    async def _http(self, scope: Scope, receive: Receive, send: Send) -> None:
        status: int | None = None

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        # I7 E43: the use cases this request runs report «было → стало» into a list of its own;
        # it is read back here and written into this request's one row (never an UPDATE later).
        change_scope = _change_scope(scope)
        token = change_scope.open() if change_scope is not None else None
        try:
            await self.app(scope, receive, capture)
        except Exception:
            if change_scope is not None:
                change_scope.close(token)
            await _record_http(scope, status if status is not None else _SERVER_ERROR_STATUS)
            raise
        changes = change_scope.close(token) if change_scope is not None else ()
        await _record_http(
            scope, status if status is not None else _SERVER_ERROR_STATUS, changes=changes
        )

    async def _websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        recorded = False

        async def capture(message: Message) -> None:
            nonlocal recorded
            await send(message)
            if recorded:
                return
            if message["type"] == "websocket.accept":
                recorded = True
                await _record_ws_accept(scope)
            elif message["type"] == "websocket.close":
                recorded = True
                await _record(
                    scope, AuditAction.ACCESS_DENIED, _WS_REFUSED_STATUS, AuditOutcome.DENIED
                )

        try:
            await self.app(scope, receive, capture)
        except Exception:
            if not recorded:
                await _record(
                    scope, AuditAction.ACCESS_DENIED, _SERVER_ERROR_STATUS, AuditOutcome.ERROR
                )
            raise
        if not recorded:
            await _record(scope, AuditAction.ACCESS_DENIED, _WS_REFUSED_STATUS, AuditOutcome.DENIED)


def _is_audited(scope: Scope) -> bool:
    path = str(scope.get("path", ""))
    if scope["type"] == "http" and scope.get("method") == "OPTIONS":
        return False  # a CORS preflight is the browser's, not the user's
    if not path.startswith(_AUDITED_PREFIX):
        return False
    return not (path == _UNAUDITED_PREFIX or path.startswith(_UNAUDITED_PREFIX + "/"))


async def _record_http(scope: Scope, status: int, *, changes: tuple[AuditChange, ...] = ()) -> None:
    if scope_state(scope).get(AUDIT_RECORDED_KEY):
        return
    if status in _DENIED_STATUSES:
        await _record(scope, AuditAction.ACCESS_DENIED, status, AuditOutcome.DENIED)
        return
    outcome = AuditOutcome.OK if status < 400 else AuditOutcome.ERROR
    # A request that failed changed nothing it committed: its reported changes are dropped.
    await _record(
        scope,
        AuditAction.HTTP_REQUEST,
        status,
        outcome,
        changes=changes if outcome is AuditOutcome.OK else (),
    )


async def _record_ws_accept(scope: Scope) -> None:
    refused = scope_state(scope).get(AUDIT_WS_REFUSED_KEY)
    if refused is None:
        await _record(scope, AuditAction.WS_CONNECTED, _WS_ACCEPTED_STATUS, AuditOutcome.OK)
    elif refused in _WS_DENIED_CLOSE_CODES:
        await _record(scope, AuditAction.ACCESS_DENIED, int(refused), AuditOutcome.DENIED)
    else:
        await _record(scope, AuditAction.WS_CONNECTED, int(refused), AuditOutcome.ERROR)


def _container_of(scope: Scope) -> Container | None:
    container = getattr(getattr(scope.get("app"), "state", None), "container", None)
    return container if isinstance(container, Container) else None


def _change_scope(scope: Scope) -> AuditChangeScope | None:
    container = _container_of(scope)
    return container.audit_change_scope if container is not None else None


async def _record(
    scope: Scope,
    action: AuditAction,
    status: int,
    outcome: AuditOutcome,
    *,
    changes: tuple[AuditChange, ...] = (),
) -> None:
    container = _container_of(scope)
    if container is None:
        return
    user = scope_state(scope).get(AUDIT_USER_KEY)
    route = scope.get("route")
    route_path = getattr(route, "path", None)
    client = scope.get("client")
    entry = AuditEntry(
        ts=container.clock.now(),
        action=action,
        method=str(scope.get("method", "GET")),
        path_template=(
            route_path
            if isinstance(route_path, str)
            else str(scope.get("path", ""))[:_MAX_RAW_PATH_CHARS]
        ),
        status=status,
        outcome=outcome,
        user_id=user.user_id if isinstance(user, AuthenticatedUser) else None,
        role=user.user_role if isinstance(user, AuthenticatedUser) else None,
        operation_id=route.operation_id if isinstance(route, APIRoute) else None,
        target_ids=_target_ids(scope.get("path_params")),
        client_ip=str(client[0]) if client else None,
        changes=changes,
    )
    await container.audit_recorder.record(entry)


def _target_ids(path_params: Any) -> dict[str, str]:
    if not isinstance(path_params, Mapping):
        return {}
    return {str(key): str(value) for key, value in path_params.items()}
