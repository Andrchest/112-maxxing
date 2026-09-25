"""`realtime` router — `listSessionEvents` and the WebSocket of D8 / `40-realtime-protocol.md`.

Two endpoints, one read path. `GET /api/v1/sessions/{session_id}/events` (`openapi.yaml`'s
`listSessionEvents`) and `WS /api/v1/ws/sessions/{session_id}?token=…` (§40.1) answer with the
*same* envelopes produced by the *same* redaction function
(`app.application.realtime.redaction.redact`), because §40.2 requires them to be byte-identical.

The socket handler is deliberately thin. It authenticates, decides the three §40.1 close codes,
accepts, and then does nothing but pump: `SessionEventStream.stream` owns the subscribe / replay /
drain / tail mechanism and knows nothing about WebSockets, which is why §40.3 is unit-testable
without one. What stays here is exactly what needs a socket:

* `?token=` authentication — a browser `WebSocket` constructor cannot set an `Authorization`
  header (§40.1), so the token arrives as a query parameter and is resolved through the same
  `authenticate_token` the REST dependency wraps. It is never logged, in any branch;
* the §40.1 close codes, and the §40.2 `error` frame that precedes the ones that carry a reason;
* the client frame reader: one frame type (`resume`), a rate limit of
  `SIM_WS_MAX_FRAMES_PER_S` frames per second, and `4400` for anything else. **No command ever
  travels over this socket** (§40.2, SPEC §34, D12) — there is no branch here that could execute
  one;
* a second `resume` restarting the mechanism from the new cursor, which is how a client that saw
  a heartbeat ahead of its own `last_seq_no` heals the gap;
* cancellation: when the server is going away the connection task is cancelled, and §40.1's
  `1001` is sent before the cancellation is re-raised.

Token expiry after the connect does **not** drop the socket (§40.1): nothing here re-checks the
token, because "the session outlives the token and dropping it would violate SPEC §39".
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import suppress
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.audit import mark_ws_refused, remember_user
from app.api.container import Container
from app.api.deps import ContainerDep
from app.api.schemas.realtime import SessionEventPageSchema, session_event_page_schema
from app.api.security import CurrentUserDep
from app.application.auth.get_current_user import AuthenticatedUser, authenticate_token
from app.application.ports.token_service import InvalidTokenError
from app.application.realtime.effective_role import Connection, connection_of
from app.application.realtime.event_stream import (
    ErrorFrame,
    InvalidResumeCursorError,
    ResumeRequest,
    SessionEventStream,
)
from app.application.sessions.authorisation import ParticipantNotAssignedError
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["sessions"])

# §40.1 "Close codes", by name so no endpoint writes a bare integer.
CLOSE_NORMAL = 1000
CLOSE_GOING_AWAY = 1001
CLOSE_INVALID_FRAME = 4400
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN_FOR_ROLE = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_INVALID_RESUME_CURSOR = 4409
CLOSE_RATE_LIMITED = 4429


@router.get(
    "/sessions/{session_id}/events",
    operation_id="listSessionEvents",
    summary="A page of role-filtered session events.",
    response_model=SessionEventPageSchema,
    status_code=200,
)
async def list_session_events(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    after_seq_no: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    event_type: Annotated[list[EventType] | None, Query()] = None,
) -> SessionEventPageSchema:
    """The REST twin of the WebSocket replay (`openapi.yaml`).

    `after_seq_no` is exclusive; `event_type` is an optional filter that is still intersected with
    the role's visible set, because it is applied after §40.4 has had its say.
    """
    view = await container.list_session_events()(
        SessionId(session_id),
        viewer=user,
        after_seq_no=after_seq_no,
        limit=limit,
        event_types=event_type,
    )
    return session_event_page_schema(view)


@router.websocket("/ws/sessions/{session_id}")
async def session_event_socket(websocket: WebSocket, session_id: UUID) -> None:
    """§40.1's endpoint: authenticate, authorise, accept, then pump §40.2 frames."""
    container = _container(websocket)
    resolved = SessionId(session_id)

    user = await _authenticate(websocket, container)
    if user is None:
        return
    connection = await _authorise(websocket, container, resolved, user)
    if connection is None:
        return

    await websocket.accept()
    try:
        await _serve(websocket, container, resolved, connection)
    except asyncio.CancelledError:
        # §40.1/§40.5 "Backend restart": sockets close with `1001`, the client reconnects on its
        # backoff and resumes. Nothing is lost — every event was committed before it was published.
        with suppress(Exception):
            await websocket.close(code=CLOSE_GOING_AWAY)
        raise


# ---------------------------------------------------------------------------------------------
# Connect: the three §40.1 gates, in order
# ---------------------------------------------------------------------------------------------


async def _authenticate(websocket: WebSocket, container: Container) -> AuthenticatedUser | None:
    """Gate 1: "token valid and not expired → else close `4401`".

    The token is read from the query string and never written anywhere: not to a log line, not to
    a close reason, not to an exception message this module raises (SPEC §41).
    """
    token = websocket.query_params.get("token")
    try:
        if not token:
            raise InvalidTokenError("no token query parameter")
        user = await authenticate_token(
            token, tokens=container.tokens, unit_of_work=container.unit_of_work
        )
    except InvalidTokenError:
        await _reject(websocket, CLOSE_UNAUTHENTICATED)
        return None
    remember_user(websocket, user)  # I4 E25: the audit entry of this connect names the caller
    return user


async def _authorise(
    websocket: WebSocket, container: Container, session_id: SessionId, user: AuthenticatedUser
) -> Connection | None:
    """Gates 2 and 3: the session exists (else `4404`), the caller may see it (else `4403`)."""
    async with container.unit_of_work() as uow:
        session = await uow.sessions.get(session_id)
        await uow.commit()
    if session is None:
        await _reject(websocket, CLOSE_NOT_FOUND)
        return None
    try:
        return connection_of(session, user)
    except ParticipantNotAssignedError:
        await _reject(websocket, CLOSE_FORBIDDEN_FOR_ROLE)
        return None


async def _reject(websocket: WebSocket, code: int) -> None:
    """Refuse a connection with one of §40.1's `44xx` codes.

    The authorisation decision is taken *before* this call, as §40.1 requires ("validated before
    the upgrade completes"); the handshake is then completed for the sole purpose of delivering
    the code, because a WebSocket close code cannot reach a client that never finished the
    handshake — a browser would see an opaque HTTP failure and none of §40.1's vocabulary. See
    this task's report, "HLD gaps".
    """
    mark_ws_refused(websocket, code)  # I4 E25: audited as a refusal, not a connect
    with suppress(Exception):
        await websocket.accept()
        await websocket.close(code=code)


# ---------------------------------------------------------------------------------------------
# Live: the client frame reader and the frame pump
# ---------------------------------------------------------------------------------------------


async def _serve(
    websocket: WebSocket, container: Container, session_id: SessionId, connection: Connection
) -> None:
    """§40.3 step 1: send nothing until a `resume` arrives, then pump until the client goes."""
    stream = container.session_event_stream()
    limiter = _FrameRateLimiter(container.settings.ws_max_frames_per_s)
    pump: asyncio.Task[None] | None = None
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if not limiter.allow():
                await _send(websocket, ErrorFrame(code="RATE_LIMITED", detail="too many frames"))
                await websocket.close(code=CLOSE_RATE_LIMITED)
                return
            raw = message.get("text") or message.get("bytes")
            try:
                request = ResumeRequest.model_validate_json(raw if raw is not None else b"")
            except ValidationError:
                # §40.2: "Any other `type`, any non-JSON payload […] closes the socket (`4400`)."
                await _send(websocket, ErrorFrame(code="INVALID_FRAME", detail="expected resume"))
                await websocket.close(code=CLOSE_INVALID_FRAME)
                return
            pump = await _restart(pump, websocket, stream, session_id, connection, request)
    except WebSocketDisconnect:
        return
    finally:
        await _stop(pump)


async def _restart(
    pump: asyncio.Task[None] | None,
    websocket: WebSocket,
    stream: SessionEventStream,
    session_id: SessionId,
    connection: Connection,
    request: ResumeRequest,
) -> asyncio.Task[None]:
    """Abandon the running mechanism and start a new one from `request.after_seq_no` (§40.2)."""
    await _stop(pump)
    return asyncio.create_task(
        _pump(websocket, stream, session_id, connection, request.after_seq_no),
        name=f"ws-pump:{session_id}",
    )


async def _pump(
    websocket: WebSocket,
    stream: SessionEventStream,
    session_id: SessionId,
    connection: Connection,
    after_seq_no: int,
) -> None:
    """Write every frame the mechanism yields; map its one refusal to close `4409`."""
    try:
        async for frame in stream.stream(session_id, connection, after_seq_no):
            await _send(websocket, frame)
    except InvalidResumeCursorError:
        # The `error` frame was already yielded and sent by the loop above (§40.2: an `error`
        # frame does not necessarily close the socket; this one does).
        with suppress(Exception):
            await websocket.close(code=CLOSE_INVALID_RESUME_CURSOR)
    except (WebSocketDisconnect, RuntimeError):
        return  # the client went away mid-write; the reader loop is about to notice too


async def _stop(pump: asyncio.Task[None] | None) -> None:
    """Cancel **and await** the pump: an unawaited cancelled task is exactly the leak §40.6 bans."""
    if pump is None or pump.done():
        return
    pump.cancel()
    with suppress(asyncio.CancelledError):
        await pump


async def _send(websocket: WebSocket, frame: object) -> None:
    """Write one §40.2 frame as JSON."""
    await websocket.send_json(frame.model_dump(mode="json"))  # type: ignore[attr-defined]


class _FrameRateLimiter:
    """§40.2: "more than 10 frames per second closes the socket (`4429`)" — a 1 s sliding window."""

    def __init__(self, max_frames_per_s: int) -> None:
        self._max = max_frames_per_s
        self._seen: deque[float] = deque()

    def allow(self) -> bool:
        """Record one client frame and answer whether it is within the limit."""
        now = asyncio.get_running_loop().time()
        while self._seen and now - self._seen[0] >= 1.0:
            self._seen.popleft()
        self._seen.append(now)
        return len(self._seen) <= self._max


def _container(websocket: WebSocket) -> Container:
    """The application's `Container`. A WebSocket route cannot use the `Request` dependency."""
    container = getattr(websocket.app.state, "container", None)
    if container is None:  # pragma: no cover - create_app always sets it
        raise RuntimeError("the application has no container; build it with create_app()")
    assert isinstance(container, Container)
    return container
