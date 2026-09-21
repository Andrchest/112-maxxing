"""The Redis adapters behind the two voice ports, against the real compose Redis (§40.6).

The use-case tests record signals in memory; these assert the bytes that actually reach Redis —
the channel names and the payload keys §40.6 specifies — because a payload the voice-agent cannot
parse is a payload that fails only in production.

Worker-safe by construction: every session id is a fresh UUID, so the channels and keys below are
unique per test even when two xdist workers share a Redis logical database (E11-0).
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
import redis.asyncio as redis_asyncio
from app.domain.common.ids import SessionId
from app.infrastructure.transport.redis_call_state_cache import (
    RedisCallStateCache,
    call_state_key,
)
from app.infrastructure.transport.redis_voice_signals import (
    JOIN_CHANNEL,
    RedisVoiceSignals,
    cancel_channel,
)

pytestmark = pytest.mark.integration


async def receive_one(
    redis_client: redis_asyncio.Redis, channel: str, timeout_s: float = 5.0
) -> dict[str, object]:
    """Subscribe, run the publisher the caller armed, and return the one decoded message."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    try:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message is not None:
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                decoded: dict[str, object] = json.loads(data)
                return decoded
        raise AssertionError(f"no message on {channel} within {timeout_s} s")
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


# -- voice:join / voice:cancel ---------------------------------------------------------------------


async def test_voice_join_payload_is_the_one_40_6_specifies(
    redis_client: redis_asyncio.Redis,
) -> None:
    session_id = SessionId(uuid4())
    call_id = uuid4()
    signals = RedisVoiceSignals(redis_client)

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(JOIN_CHANNEL)
    try:
        await asyncio.sleep(0)
        received: dict[str, object] | None = None
        deadline = asyncio.get_running_loop().time() + 5.0
        await signals.publish_join(session_id, room=f"session-{session_id}", call_id=call_id)
        while asyncio.get_running_loop().time() < deadline and received is None:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message is None:
                continue
            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            candidate = json.loads(data)
            # The channel is shared by every session; ignore other workers' traffic.
            if candidate.get("session_id") == str(session_id).lower():
                received = candidate
    finally:
        await pubsub.unsubscribe(JOIN_CHANNEL)
        await pubsub.aclose()

    assert received is not None, "no voice:join for this session within 5 s"
    assert set(received) == {"session_id", "room", "call_id"}
    assert received["room"] == f"session-{session_id}"
    assert received["call_id"] == str(call_id).lower()


async def test_voice_cancel_channel_and_payload_are_the_ones_40_6_specifies(
    redis_client: redis_asyncio.Redis,
) -> None:
    session_id = SessionId(uuid4())
    call_id = uuid4()
    signals = RedisVoiceSignals(redis_client)
    channel = cancel_channel(session_id)

    assert channel == f"voice:cancel:{str(session_id).lower()}"
    assert "{" not in channel and "}" not in channel  # §40.6: substitute, never emit the braces

    async def publish() -> None:
        await asyncio.sleep(0.05)
        await signals.publish_cancel(
            session_id, call_id=call_id, reason="HANGUP", at_offset_ms=4321
        )

    task = asyncio.create_task(publish())
    try:
        received = await receive_one(redis_client, channel)
    finally:
        await task

    assert set(received) == {"call_id", "reason", "at_offset_ms"}
    assert received["call_id"] == str(call_id).lower()
    assert received["reason"] == "HANGUP"
    assert received["at_offset_ms"] == 4321


async def test_a_publish_with_no_subscriber_is_not_an_error(
    redis_client: redis_asyncio.Redis,
) -> None:
    """§40.6: losing the signal costs liveness. Nobody listening is the commonest way to lose it."""
    session_id = SessionId(uuid4())

    await RedisVoiceSignals(redis_client).publish_join(
        session_id, room=f"session-{session_id}", call_id=uuid4()
    )


async def test_an_unreachable_redis_never_fails_a_publish() -> None:
    """A hang-up must not fail because a cache is down."""

    class BrokenRedis:
        async def publish(self, channel: str, message: str) -> None:
            raise ConnectionError("redis is down")

    signals = RedisVoiceSignals(BrokenRedis())  # type: ignore[arg-type]
    session_id = SessionId(uuid4())

    await signals.publish_join(session_id, room="r", call_id=uuid4())
    await signals.publish_cancel(session_id, call_id=uuid4(), reason="ABORT", at_offset_ms=0)


# -- session:{id}:call_state -----------------------------------------------------------------------


async def test_the_call_state_key_round_trips_and_carries_a_ttl(
    redis_client: redis_asyncio.Redis,
) -> None:
    session_id = SessionId(uuid4())
    cache = RedisCallStateCache(redis_client, ttl_s=60)
    key = call_state_key(session_id)

    assert key == f"session:{str(session_id).lower()}:call_state"
    try:
        assert await cache.get(session_id) is None  # a cold cache is a miss, not an error

        await cache.put(session_id, '{"phase": "RINGING"}')

        assert await cache.get(session_id) == '{"phase": "RINGING"}'
        ttl = await redis_client.ttl(key)
        assert 0 < ttl <= 60
    finally:
        await redis_client.delete(key)


async def test_an_unreachable_redis_is_a_miss_and_a_silent_write() -> None:
    class BrokenRedis:
        async def get(self, key: str) -> str | None:
            raise ConnectionError("redis is down")

        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            raise ConnectionError("redis is down")

    cache = RedisCallStateCache(BrokenRedis(), ttl_s=60)  # type: ignore[arg-type]
    session_id = SessionId(uuid4())

    assert await cache.get(session_id) is None
    await cache.put(session_id, "{}")  # must not raise
