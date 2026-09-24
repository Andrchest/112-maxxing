"""`RedisRunnerLock` — `lock:session:{session_id}:runner` (HLD §40.6, D7).

§40.6's key table, implemented literally: a Redis string whose value is the owning backend
instance id, taken with `SET … NX EX <ttl>` and refreshed every `SIM_RUNNER_LOCK_REFRESH_S`.

`refresh` and `release` are **compare-and-act on the owner**, because the TTL can expire between
two refreshes and another instance can legitimately adopt the session in that window. A blind
`EXPIRE` would then extend a lock this process no longer holds, and a blind `DEL` would delete the
other instance's lock — both would break D7's single-runner guarantee. Each is therefore a small
Lua script, which Redis runs atomically.

Key names use the session UUID in canonical lowercase hyphenated form and never contain braces
(§40.6 "Placeholder note"), exactly like `redis_publisher.session_events_channel`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from redis.asyncio import Redis

from app.domain.common.ids import LessonId, SessionId

__all__ = ["RedisRunnerLock", "lesson_runner_lock_key", "runner_lock_key"]

#: Extend the TTL only while the value is still this owner's id.
_REFRESH_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""

#: Delete only while the value is still this owner's id.
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def runner_lock_key(session_id: SessionId) -> str:
    """`lock:session:{session_id}:runner` (§40.6), with the UUID in canonical lowercase form."""
    return f"lock:session:{str(session_id).lower()}:runner"


def lesson_runner_lock_key(lesson_id: LessonId) -> str:
    """`lock:lesson:{lesson_id}:runner` (HLD 70 §70.3.3), same form as the session key."""
    return f"lock:lesson:{str(lesson_id).lower()}:runner"


class RedisRunnerLock:
    """`RunnerLock` over Redis (D7, §40.6) — and, built with `lesson_runner_lock_key`, the
    `LessonRunnerLock` of HLD 70 §70.3.3: one implementation, two key spaces."""

    def __init__(self, client: Redis, key: Callable[[Any], str] = runner_lock_key) -> None:
        self._client = client
        #: `runner_lock_key` for sessions, `lesson_runner_lock_key` for lessons.
        self._key = key

    async def acquire(self, session_id: SessionId, owner: str, ttl_s: int) -> bool:
        """`SET key owner NX EX ttl` — `True` for the one instance that wins the race."""
        taken = await self._client.set(self._key(session_id), owner, nx=True, ex=ttl_s)
        return bool(taken)

    async def refresh(self, session_id: SessionId, owner: str, ttl_s: int) -> bool:
        """Extend the TTL while `owner` still holds the key; `False` means the lock was lost."""
        result = await self._client.eval(
            _REFRESH_SCRIPT, 1, self._key(session_id), owner, str(ttl_s)
        )
        return bool(int(result))

    async def release(self, session_id: SessionId, owner: str) -> bool:
        """Compare-and-delete: never deletes a lock another instance has taken over."""
        result = await self._client.eval(_RELEASE_SCRIPT, 1, self._key(session_id), owner)
        return bool(int(result))
