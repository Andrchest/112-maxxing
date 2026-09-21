"""Fixtures for the realtime API tests: a real Redis fan-out and an in-loop WebSocket client.

Two deliberate departures from `backend/tests/api/conftest.py`, both for the same reason — this
package tests the *realtime* path, so the parts `tests/api` fakes for speed are the parts under
test here:

* `publisher` is the real `RedisEventPublisher` against the compose Redis, because the whole
  point of these tests is that a committed Unit of Work reaches a subscribed socket;
* the WebSocket client is an ASGI harness that runs the application **in the test's own event
  loop**. Starlette's `TestClient` drives the application from a worker thread with its own loop,
  and the asyncpg engine and Redis client these tests share are bound to the test's loop — a
  connection must never cross loops. The harness below keeps everything on one loop and hands a
  test the raw frames and the close code, which is how §40.1's `44xx` codes are asserted.

Redis `FLUSHALL` is never issued: the compose instance is shared with whatever else the developer
is running. The "Redis was lost" behaviour of §40.6 is simulated instead, by `LostFanOutPublisher`
below — one dropped pub/sub message, everything else exactly as in production.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import pytest
import redis.asyncio as redis_asyncio
from app.api.container import Container
from app.api.main import create_app
from app.application.ports.event_publisher import EventEnvelope
from app.config.settings import Settings
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork, unit_of_work_factory
from app.infrastructure.realtime.redis_last_seq_no_cache import RedisLastSeqNoCache
from app.infrastructure.realtime.redis_publisher import RedisEventPublisher

pytestmark = pytest.mark.integration


@pytest.fixture
def publisher(redis_client: redis_asyncio.Redis, api_settings: Settings) -> RedisEventPublisher:
    """The real fan-out: these tests are about what reaches a subscriber (see the docstring)."""
    return RedisEventPublisher(redis_client, api_settings.session_cache_ttl_s)


class LostFanOutPublisher:
    """A publisher whose pub/sub message is lost but whose §40.6 cache write is not.

    This is what "Loss ⇒ clients fall back to replay from PostgreSQL on the next heartbeat gap"
    (§40.6) actually looks like from a client: the event is committed, the
    `session:{id}:last_seq_no` key is refreshed by the same publisher that failed to deliver, and
    the heartbeat carrying that key is therefore ahead of the client's own cursor. Simulating the
    loss this way needs no `FLUSHALL` against the shared test Redis.
    """

    def __init__(self, client: redis_asyncio.Redis, ttl_s: int) -> None:
        self._cache = RedisLastSeqNoCache(client, ttl_s)
        #: Every envelope that was *not* delivered, for a test that wants to assert the loss.
        self.dropped: list[EventEnvelope] = []

    async def publish(self, session_id: SessionId, envelopes: Any) -> None:
        """Drop the fan-out; refresh the read cache."""
        envelopes = list(envelopes)
        if not envelopes:
            return
        self.dropped.extend(envelopes)
        await self._cache.set(session_id, max(envelope.seq_no for envelope in envelopes))


@pytest.fixture
def silent_unit_of_work(
    container: Container,
    redis_client: redis_asyncio.Redis,
    api_settings: Settings,
) -> Callable[[], SqlAlchemyUnitOfWork]:
    """A Unit of Work whose commits reach PostgreSQL but whose fan-out is lost (see above)."""
    factory = unit_of_work_factory(
        container.session_factory,
        container.clock,
        LostFanOutPublisher(redis_client, api_settings.session_cache_ttl_s),
    )

    def make() -> SqlAlchemyUnitOfWork:
        unit = factory()
        assert isinstance(unit, SqlAlchemyUnitOfWork)
        return unit

    return make


def domain_event(event_type: EventType, **payload: Any) -> DomainEvent:
    """One appendable event with an arbitrary payload, for driving the read path."""
    return DomainEvent(
        event_type=event_type,
        actor=ActorRef(actor_type=ActorType.SIMULATION),
        monotonic_offset_ms=1000,
        correlation_id=uuid4(),
        payload=payload,
    )


async def append_events(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    *events: DomainEvent,
) -> list[int]:
    """Append through the real Unit of Work — one commit, then the publish (D5)."""
    async with unit_of_work() as uow:
        appended = await uow.events.append(session_id, list(events))
        await uow.commit()
    return [event.seq_no for event in appended]


# ---------------------------------------------------------------------------------------------
# The in-loop ASGI WebSocket harness
# ---------------------------------------------------------------------------------------------


@dataclass
class WebSocketClosed(Exception):
    """The server closed the socket; `code` is one of §40.1's."""

    code: int


class ASGIWebSocket:
    """A WebSocket client that speaks ASGI to the application object directly.

    No port is bound and no thread is started, so everything — the engine, the Redis client, the
    application and this client — lives on the one event loop pytest-asyncio gave the test.
    """

    def __init__(self, app: Any, path: str, params: dict[str, str]) -> None:
        self._app = app
        self._scope: dict[str, Any] = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "root_path": "",
            "path": path,
            "raw_path": path.encode(),
            "query_string": urlencode(params).encode(),
            "headers": [(b"host", b"testserver")],
            "subprotocols": [],
            "state": {},
        }
        self._inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self.closed_code: int | None = None

    async def __aenter__(self) -> ASGIWebSocket:
        self._inbound.put_nowait({"type": "websocket.connect"})
        self._task = asyncio.create_task(self._run(), name="asgi-ws-client")
        first = await self._next(10.0)
        if first["type"] == "websocket.close":
            self.closed_code = int(first.get("code", 1000))
            await self.aclose()
            raise WebSocketClosed(self.closed_code)
        assert first["type"] == "websocket.accept", first
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def _run(self) -> None:
        await self._app(self._scope, self._inbound.get, self._outbound.put)

    async def _next(self, wait_s: float) -> dict[str, Any]:
        return await asyncio.wait_for(self._outbound.get(), timeout=wait_s)

    async def send_json(self, body: Any) -> None:
        """Send one client frame."""
        self._inbound.put_nowait({"type": "websocket.receive", "text": json.dumps(body)})

    async def send_text(self, text: str) -> None:
        """Send one raw (possibly malformed) client frame."""
        self._inbound.put_nowait({"type": "websocket.receive", "text": text})

    async def receive(self, wait_s: float = 10.0) -> dict[str, Any]:
        """The next server frame as a dict; raises `WebSocketClosed` on a close."""
        message = await self._next(wait_s)
        if message["type"] == "websocket.close":
            self.closed_code = int(message.get("code", 1000))
            raise WebSocketClosed(self.closed_code)
        parsed: dict[str, Any] = json.loads(message["text"])
        return parsed

    async def receive_until(self, frame_type: str, wait_s: float = 10.0) -> list[dict[str, Any]]:
        """Every frame up to and including the first one of `frame_type`."""
        frames: list[dict[str, Any]] = []
        while True:
            frame = await self.receive(wait_s)
            frames.append(frame)
            if frame["type"] == frame_type:
                return frames

    async def expect_close(self, wait_s: float = 10.0) -> int:
        """Consume frames until the server closes, and return the close code."""
        try:
            while True:
                await self.receive(wait_s)
        except WebSocketClosed as closed:
            return closed.code

    async def aclose(self) -> None:
        """Disconnect as a browser would, and let the handler's `finally` blocks run."""
        self._inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=10.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None


@pytest.fixture
def websocket(container: Container) -> Callable[..., ASGIWebSocket]:
    """`websocket(session_id, token=…)` → an unopened `ASGIWebSocket` over the real app."""
    app = create_app(container)

    def open_socket(session_id: Any, *, token: str | None = None) -> ASGIWebSocket:
        params = {} if token is None else {"token": token}
        return ASGIWebSocket(app, f"/api/v1/ws/sessions/{session_id}", params)

    return open_socket


@pytest.fixture
async def redis_subscriber_count(
    redis_client: redis_asyncio.Redis,
) -> AsyncIterator[Callable[[Any], Any]]:
    """`PUBSUB NUMSUB session:{id}:events` — the resource-hygiene assertion of §40.6."""

    async def count(session_id: Any) -> int:
        channel = f"session:{str(session_id).lower()}:events"
        result = await redis_client.execute_command("PUBSUB", "NUMSUB", channel)
        return int(result[1])

    yield count


__all__ = [
    "ASGIWebSocket",
    "EventEnvelope",
    "LostFanOutPublisher",
    "WebSocketClosed",
    "append_events",
    "domain_event",
]
