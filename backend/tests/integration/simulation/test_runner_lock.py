"""`RedisRunnerLock` against a real Redis (HLD `40-realtime-protocol.md` §40.6, D7).

The key name, the `SET NX EX` semantics and the two compare-and-act operations are what D7's
"a Redis lock `lock:session:{id}:runner` guarantees a single runner" actually rests on, so they are
tested against the real server rather than against the in-memory fake.

Every test deletes the key it made: a leaked lock would make the next run of the suite adopt
nothing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import redis.asyncio as redis_asyncio
from app.domain.common.ids import SessionId
from app.infrastructure.realtime.redis_runner_lock import RedisRunnerLock, runner_lock_key

pytestmark = pytest.mark.integration


@pytest.fixture
async def session_id(redis_client: redis_asyncio.Redis) -> AsyncIterator[SessionId]:
    """A fresh session id whose lock key is deleted afterwards, whoever ended up holding it."""
    made = SessionId(uuid4())
    try:
        yield made
    finally:
        await redis_client.delete(runner_lock_key(made))


def test_the_key_name_is_the_one_the_redis_inventory_prints() -> None:
    """§40.6: the UUID in canonical lowercase form, and never a literal brace."""
    session_id = SessionId(uuid4())
    key = runner_lock_key(session_id)
    assert key == f"lock:session:{session_id!s}:runner"
    assert "{" not in key and "}" not in key
    assert key == key.lower()


async def test_only_one_owner_acquires_and_the_value_is_the_instance_id(
    redis_client: redis_asyncio.Redis, session_id: SessionId
) -> None:
    lock = RedisRunnerLock(redis_client)
    assert await lock.acquire(session_id, "instance-a", 30) is True
    assert await lock.acquire(session_id, "instance-b", 30) is False
    assert await redis_client.get(runner_lock_key(session_id)) == "instance-a"


async def test_refresh_and_release_act_only_for_the_owner(
    redis_client: redis_asyncio.Redis, session_id: SessionId
) -> None:
    """A loser must not be able to extend or delete the winner's lock (D7)."""
    lock = RedisRunnerLock(redis_client)
    await lock.acquire(session_id, "instance-a", 30)

    assert await lock.refresh(session_id, "instance-b", 30) is False
    assert await lock.release(session_id, "instance-b") is False
    assert await redis_client.get(runner_lock_key(session_id)) == "instance-a"

    assert await lock.refresh(session_id, "instance-a", 30) is True
    assert await lock.release(session_id, "instance-a") is True
    assert await redis_client.get(runner_lock_key(session_id)) is None


async def test_a_released_lock_can_be_adopted_by_another_instance(
    redis_client: redis_asyncio.Redis, session_id: SessionId
) -> None:
    lock = RedisRunnerLock(redis_client)
    await lock.acquire(session_id, "instance-a", 30)
    await lock.release(session_id, "instance-a")
    assert await lock.acquire(session_id, "instance-b", 30) is True
    assert await lock.refresh(session_id, "instance-a", 30) is False


async def test_acquire_sets_the_ttl_the_settings_ask_for(
    redis_client: redis_asyncio.Redis, session_id: SessionId
) -> None:
    """`SIM_RUNNER_LOCK_TTL_S` (default 30) is what expires an abandoned lock (§40.6)."""
    lock = RedisRunnerLock(redis_client)
    await lock.acquire(session_id, "instance-a", 30)
    assert 0 < await redis_client.ttl(runner_lock_key(session_id)) <= 30

    await redis_client.expire(runner_lock_key(session_id), 100)
    assert await lock.refresh(session_id, "instance-a", 30) is True
    assert await redis_client.ttl(runner_lock_key(session_id)) <= 30
