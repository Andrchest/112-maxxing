"""Composition-root wiring that no other test would notice (`app.api.container`, D2).

A container assembles ports; a wrong constructor argument there is invisible to every test that
only checks behaviour at the default value. This module asserts the settings that must *travel*
from `Settings` into an adapter, with a value that is deliberately not the default.

Nothing here connects to anything: `Redis` is a recorder, and the engine is built but never used
(`create_engine` opens no connection).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.api.container import Container
from app.config.settings import Settings
from app.domain.common.ids import SessionId

NON_DEFAULT_TTL_S = 77
"""Neither `Settings.session_cache_ttl_s`'s default nor the publisher's own fallback (3600)."""


class RecordingRedis:
    """Just enough `redis.asyncio.Redis` for `RedisEventPublisher` to run against."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.sets: list[tuple[str, str, int | None]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1

    async def set(self, key: str, value: Any, *, ex: int | None = None) -> bool:
        self.sets.append((key, str(value), ex))
        return True

    async def aclose(self) -> None:
        return None


class _Envelope:
    """The one attribute `RedisEventPublisher.publish` reads besides `model_dump_json`."""

    def __init__(self, seq_no: int) -> None:
        self.seq_no = seq_no

    def model_dump_json(self) -> str:
        return f'{{"seq_no": {self.seq_no}}}'


async def test_a_non_default_session_cache_ttl_reaches_the_event_publisher(
    test_settings: Settings,
) -> None:
    """`SIM_SESSION_CACHE_TTL_S` must reach `RedisEventPublisher`, not just the read cache (§40.6).

    The publisher writes `session:{id}:last_seq_no` with that TTL; a container that constructed it
    without the setting would silently use the adapter's own 3600 fallback, which is correct only
    while the setting is at its default. That is exactly the bug this asserts against.
    """
    settings = test_settings.model_copy(update={"session_cache_ttl_s": NON_DEFAULT_TTL_S})
    redis = RecordingRedis()
    container = Container(settings, redis=redis, owns_redis=False)  # type: ignore[arg-type]

    session_id = SessionId(uuid4())
    await container.publisher.publish(session_id, [_Envelope(7)])

    assert redis.sets == [(f"session:{session_id}:last_seq_no", "7", NON_DEFAULT_TTL_S)]
    assert container.last_seq_no_cache() is not None, "the read side reads the same key"

    await container.engine.dispose()


async def test_the_read_cache_uses_the_same_non_default_ttl(test_settings: Settings) -> None:
    """The writer and the reader of §40.6's key must not disagree about its lifetime."""
    settings = test_settings.model_copy(update={"session_cache_ttl_s": NON_DEFAULT_TTL_S})
    redis = RecordingRedis()
    container = Container(settings, redis=redis, owns_redis=False)  # type: ignore[arg-type]

    session_id = SessionId(uuid4())
    await container.last_seq_no_cache().set(session_id, 11)

    assert redis.sets == [(f"session:{session_id}:last_seq_no", "11", NON_DEFAULT_TTL_S)]

    await container.engine.dispose()
