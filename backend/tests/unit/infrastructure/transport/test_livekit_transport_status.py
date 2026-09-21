"""`LiveKitTransportStatus` — both halves of `ring`'s guard, and both ways round (D9, §10.8).

The guard means "the media plane can take a call": the LiveKit server answers **and** the
voice-agent heartbeat `voice:health:vad` says `READY` (§40.6, `60-inference-ops.md` §4.3). Every
combination is asserted here, because a guard that is satisfied by either half alone would let a
trainee's phone ring into a room nobody can join.

No fixed port is bound: the stub SFU listens on port 0 and the kernel picks one. No Redis is
needed either — the heartbeat half is a `get` on one key, which a five-line stub answers.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from app.domain.common.ids import SessionId
from app.infrastructure.transport.livekit_transport_status import (
    LiveKitTransportStatus,
    http_origin_of,
)

SESSION = SessionId(uuid4())


class StubRedis:
    """Answers one key, or raises — the two things the adapter must survive."""

    def __init__(self, value: str | None = None, *, raises: bool = False) -> None:
        self._value = value
        self._raises = raises
        self.keys_read: list[str] = []

    async def get(self, key: str) -> str | None:
        """The stored value for any key, or an explosion when the test asked for one."""
        self.keys_read.append(key)
        if self._raises:
            raise ConnectionError("redis is down")
        return self._value


def ready_document() -> str:
    """The `voice:health:vad` value `60-inference-ops.md` §4.3 specifies."""
    return json.dumps(
        {
            "state": "READY",
            "profile": "DEV_3060TI",
            "provider": "energy",
            "model_version": "n/a",
            "updated_at": "2026-01-01T00:00:00Z",
            "detail": None,
            "warmup_ms": 12,
        }
    )


@asynccontextmanager
async def stub_sfu() -> AsyncIterator[str]:
    """A socket that answers one minimal HTTP response, on an ephemeral port."""

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


async def closed_port_url() -> str:
    """A `ws://` URL nothing is listening on: bind an ephemeral port, then give it back."""
    server = await asyncio.start_server(lambda _r, _w: None, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    server.close()
    await server.wait_closed()
    return f"ws://{host}:{port}"


# -- the two halves ------------------------------------------------------------------------------


async def test_ready_when_the_server_answers_and_the_heartbeat_says_ready() -> None:
    async with stub_sfu() as url:
        redis = StubRedis(ready_document())
        status = LiveKitTransportStatus(url, redis, health_key=f"voice:health:vad:{uuid4()}")

        assert await status.transport_ready(SESSION) is True
        assert len(redis.keys_read) == 1


async def test_not_ready_when_the_heartbeat_key_is_missing() -> None:
    """§40.6: "A missing key is `NOT_READY`, never `READY`"."""
    async with stub_sfu() as url:
        status = LiveKitTransportStatus(
            url, StubRedis(None), health_key=f"voice:health:vad:{uuid4()}"
        )

        assert await status.transport_ready(SESSION) is False


async def test_not_ready_when_the_heartbeat_is_not_ready() -> None:
    async with stub_sfu() as url:
        document = json.dumps({"state": "WARMING"})
        status = LiveKitTransportStatus(
            url, StubRedis(document), health_key=f"voice:health:vad:{uuid4()}"
        )

        assert await status.transport_ready(SESSION) is False


async def test_not_ready_when_the_server_is_unreachable_even_with_a_ready_heartbeat() -> None:
    url = await closed_port_url()
    status = LiveKitTransportStatus(
        url, StubRedis(ready_document()), health_key=f"voice:health:vad:{uuid4()}"
    )

    assert await status.transport_ready(SESSION) is False


# -- never raises --------------------------------------------------------------------------------


async def test_an_unreachable_redis_is_false_not_an_exception() -> None:
    async with stub_sfu() as url:
        status = LiveKitTransportStatus(
            url, StubRedis(raises=True), health_key=f"voice:health:vad:{uuid4()}"
        )

        assert await status.transport_ready(SESSION) is False


async def test_a_heartbeat_value_that_is_not_json_is_false_not_an_exception() -> None:
    async with stub_sfu() as url:
        status = LiveKitTransportStatus(
            url, StubRedis("not json at all"), health_key=f"voice:health:vad:{uuid4()}"
        )

        assert await status.transport_ready(SESSION) is False


async def test_bytes_from_a_client_without_decode_responses_are_understood() -> None:
    class BytesRedis(StubRedis):
        async def get(self, key: str) -> bytes:  # type: ignore[override]
            self.keys_read.append(key)
            return ready_document().encode("utf-8")

    async with stub_sfu() as url:
        status = LiveKitTransportStatus(url, BytesRedis(), health_key=f"voice:health:vad:{uuid4()}")

        assert await status.transport_ready(SESSION) is True


# -- the URL mapping -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("ws://localhost:7880", "http://localhost:7880"),
        ("wss://livekit.example:443", "https://livekit.example:443"),
        ("http://livekit:7880", "http://livekit:7880"),
        ("https://livekit:7880", "https://livekit:7880"),
        ("localhost:7880", "localhost:7880"),
    ],
)
def test_the_ws_url_is_probed_over_http(given: str, expected: str) -> None:
    assert http_origin_of(given) == expected
