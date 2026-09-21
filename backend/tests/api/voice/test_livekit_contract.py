"""Contract tests against a REAL LiveKit server — skipped unless one answers (E11 ruling 1).

The gate is built and proved against fakes and stubs; nothing in it may require an SFU. These
tests are the other half: they check the claims a stub cannot check — that the server we pinned
really answers on `SIM_LIVEKIT_URL`, and that the token this backend mints is one that server
accepts — and they are `requires_livekit`, so they are skipped on any box where no LiveKit is
running.

Run them with `make dev-infra-up` (which starts `infra/docker-compose.yml`'s `livekit` service)
and `SIM_LIVEKIT_URL` pointing at it. Nothing here starts, stops or leaves behind a container.
"""

from __future__ import annotations

import asyncio
import os
import socket
from urllib.parse import urlsplit

import pytest
from app.config.settings import Settings
from app.domain.common.ids import SessionId
from app.domain.enums import HealthStatus
from app.infrastructure.health.livekit_probe import LiveKitHealthProbe
from app.infrastructure.transport.livekit_token_service import LiveKitTokenService
from app.infrastructure.transport.livekit_transport_status import http_origin_of

pytestmark = [pytest.mark.integration, pytest.mark.requires_livekit]

LIVEKIT_URL = os.environ.get("SIM_LIVEKIT_URL", "ws://localhost:7880")


def _answers(url: str) -> bool:
    """Is anything listening where `url` points? One TCP connect, half a second."""
    parts = urlsplit(http_origin_of(url))
    host = parts.hostname or "localhost"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark.append(
    pytest.mark.skipif(
        not _answers(LIVEKIT_URL),
        reason=f"no LiveKit server answers on {LIVEKIT_URL} (start it with `make dev-infra-up`)",
    )
)


async def test_the_health_probe_reads_ready_from_a_live_server() -> None:
    reading = await LiveKitHealthProbe(LIVEKIT_URL).check()

    assert reading.component == "livekit"
    assert reading.status is HealthStatus.READY
    assert reading.provider == "livekit"


async def test_the_transport_status_sees_the_server_but_still_needs_the_agent(
    test_settings: Settings,
) -> None:
    """Even against a live SFU, `ring` stays denied until the voice-agent heartbeats (E11)."""
    from uuid import uuid4

    import redis.asyncio as redis_asyncio
    from app.infrastructure.transport.livekit_transport_status import LiveKitTransportStatus

    client: redis_asyncio.Redis = redis_asyncio.from_url(
        test_settings.redis_url, decode_responses=True
    )
    try:
        status = LiveKitTransportStatus(
            LIVEKIT_URL, client, health_key=f"voice:health:vad:{uuid4()}"
        )
        assert await status.transport_ready(SessionId(uuid4())) is False
    finally:
        await client.aclose()


async def test_a_minted_token_is_accepted_by_the_live_server(test_settings: Settings) -> None:
    """The one claim only a real SFU can settle: it validates our signature and our grant.

    A rejected token closes the WebSocket immediately with a 4xx; an accepted one leaves the
    handshake open. Connecting with a raw WebSocket upgrade keeps this test free of the `livekit`
    SDK, which `backend/` may never import (D2, `backend/tools/check_imports.py`).
    """
    minted = LiveKitTokenService(
        test_settings.livekit_api_key,
        test_settings.livekit_api_secret,
        livekit_url=LIVEKIT_URL,
        ttl_minutes=1,
    ).mint(room_name=f"contract-{os.getpid()}", participant_identity="contract-test")

    parts = urlsplit(http_origin_of(LIVEKIT_URL))
    host = parts.hostname or "localhost"
    port = parts.port or 7880
    reader, writer = await asyncio.open_connection(host, port)
    try:
        request = (
            f"GET /rtc/validate?access_token={minted.token} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        status_line = (await asyncio.wait_for(reader.readline(), timeout=5.0)).decode()
    finally:
        writer.close()
        await writer.wait_closed()

    # `/rtc/validate` answers 200 for a token this server accepts and 401 for one it does not.
    assert " 200 " in status_line, f"LiveKit rejected the minted token: {status_line.strip()}"
