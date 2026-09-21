"""`ring` fires only when the media plane can take a call (§10.8 guard, D9, E11 ruling 3).

The guard is `guard_session_active_and_transport_ready`, and E11 settled what `transport_ready`
means: the LiveKit server is reachable **and** the voice-agent heartbeat `voice:health:vad` is
`READY` (§40.6, `60-inference-ops.md` §4.3). Both halves are exercised here through the *real*
`LiveKitTransportStatus` adapter — not through the fake — because the fake could be scripted to
agree with a wrong adapter.

Two rules keep these worker-safe under `pytest -n auto`: the stub SFU listens on an ephemeral port
(never a fixed one), and the heartbeat key is suffixed with a fresh UUID, so two workers sharing a
Redis logical database never see each other's heartbeat.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import redis.asyncio as redis_asyncio
from app.application.testing.fakes import FakeCallTransportStatus, InMemoryVoiceSignals
from app.domain.common.ids import SessionId
from app.domain.enums import HealthStatus
from app.domain.events.types import EventType
from app.infrastructure.transport.livekit_transport_status import LiveKitTransportStatus

from tests.api.voice.conftest import OperatorFlow

pytestmark = pytest.mark.integration


@asynccontextmanager
async def stub_sfu() -> AsyncIterator[str]:
    """A socket that answers one minimal HTTP response, on a kernel-chosen port."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readline()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
        except Exception:  # pragma: no cover - the client may hang up first
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    try:
        yield f"ws://{host}:{port}"
    finally:
        server.close()
        await server.wait_closed()


async def unreachable_url() -> str:
    """A `ws://` URL nothing listens on: take an ephemeral port, then give it straight back."""
    server = await asyncio.start_server(lambda _r, _w: None, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    server.close()
    await server.wait_closed()
    return f"ws://{host}:{port}"


@pytest.fixture
def health_key() -> str:
    """`voice:health:vad`, suffixed per test so parallel workers never collide (E11-0)."""
    return f"voice:health:vad:{uuid4()}"


async def set_heartbeat(redis_client: redis_asyncio.Redis, key: str, state: HealthStatus) -> None:
    """Write the heartbeat `60-inference-ops.md` §4.3 specifies, with its documented TTL."""
    await redis_client.set(
        key,
        json.dumps(
            {
                "state": state.value,
                "profile": "DEV_3060TI",
                "provider": "energy",
                "model_version": "n/a",
                "updated_at": "2026-01-01T00:00:00Z",
                "detail": None,
                "warmup_ms": 7,
            }
        ),
        ex=15,
    )


async def rang(flow: OperatorFlow) -> bool:
    """Did the simulation's `ring` trigger fire and write `CALL_RINGING`?"""
    fired = await flow.advance_call_flow()
    in_log = EventType.CALL_RINGING.value in await flow.event_types()
    assert fired == in_log, "a fired `ring` must have appended CALL_RINGING, and vice versa"
    return fired


# -- the real adapter, all four combinations -------------------------------------------------------


async def test_no_heartbeat_no_ring(
    flow: OperatorFlow, redis_client: redis_asyncio.Redis, health_key: str
) -> None:
    """The SFU is up but no voice-agent is alive: ringing would call into an empty room.

    This is the test the brief asks to be provable: make `LiveKitTransportStatus.transport_ready`
    return `True` unconditionally and this must fail.
    """
    async with stub_sfu() as url:
        flow.container.call_transport_status = LiveKitTransportStatus(
            url, redis_client, health_key=health_key
        )
        assert await redis_client.get(health_key) is None

        assert await rang(flow) is False


async def test_a_not_ready_heartbeat_is_not_a_ring(
    flow: OperatorFlow, redis_client: redis_asyncio.Redis, health_key: str
) -> None:
    async with stub_sfu() as url:
        await set_heartbeat(redis_client, health_key, HealthStatus.WARMING)
        flow.container.call_transport_status = LiveKitTransportStatus(
            url, redis_client, health_key=health_key
        )

        try:
            assert await rang(flow) is False
        finally:
            await redis_client.delete(health_key)


async def test_an_unreachable_livekit_is_not_a_ring(
    flow: OperatorFlow, redis_client: redis_asyncio.Redis, health_key: str
) -> None:
    """The agent is alive but there is no SFU to join — still no call."""
    await set_heartbeat(redis_client, health_key, HealthStatus.READY)
    flow.container.call_transport_status = LiveKitTransportStatus(
        await unreachable_url(), redis_client, health_key=health_key
    )

    try:
        assert await rang(flow) is False
    finally:
        await redis_client.delete(health_key)


async def test_both_up_rings_and_summons_the_agent(
    flow: OperatorFlow,
    redis_client: redis_asyncio.Redis,
    health_key: str,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    async with stub_sfu() as url:
        await set_heartbeat(redis_client, health_key, HealthStatus.READY)
        flow.container.call_transport_status = LiveKitTransportStatus(
            url, redis_client, health_key=health_key
        )

        try:
            assert await rang(flow) is True
        finally:
            await redis_client.delete(health_key)

    assert len(voice_signals.joins) == 1
    assert voice_signals.joins[0][1] == f"session-{flow.session_id}"


# -- the fake, scripted both ways ------------------------------------------------------------------


async def test_the_fake_status_denies_and_then_allows_the_same_session(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """The same session, one tick apart: the only thing that changed is the transport reading."""
    fake = FakeCallTransportStatus(ready=False)
    flow.container.call_transport_status = fake

    assert await rang(flow) is False
    assert voice_signals.joins == []

    fake.ready = True
    assert await rang(flow) is True
    assert len(voice_signals.joins) == 1
    assert fake.calls == [SessionId(flow.session_id)] * 2


async def test_a_per_session_override_denies_only_that_session(flow: OperatorFlow) -> None:
    fake = FakeCallTransportStatus(ready=True)
    fake.per_session[SessionId(flow.session_id)] = False
    flow.container.call_transport_status = fake

    assert await rang(flow) is False
