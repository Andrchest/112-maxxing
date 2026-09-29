"""`RedisLoginAttemptStore` — the `LoginAttemptStore` port over Redis (I7 E51, G5, ТЗ ¶295).

One Lua script per increment, the same idiom as `redis_runner_lock`'s compare-and-act scripts:
`INCR` then, only on the increment that just created the key (result `1`), `EXPIRE` it. Two plain
calls could race two concurrent requests into each setting their own `EXPIRE`, which is harmless
here (both would set the same `window_s`) but the script keeps it atomic anyway rather than relying
on that.

Every method swallows a Redis error and degrades to "no signal" (`0` / a no-op increment): a
brute-force counter is a security signal, not simulation state, and SPEC §31's "a complete Redis
flush loses no simulation state" extends the same way `RedisIdempotencyStore` already does — losing
this counter costs a weaker throttle for one window, never a login the account owner cannot
retry.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

__all__ = ["RedisLoginAttemptStore"]

logger = logging.getLogger(__name__)

#: `INCR`, then `EXPIRE` only on the increment that just created the key.
_INCREMENT_SCRIPT = """
local n = redis.call('incr', KEYS[1])
if n == 1 then
  redis.call('expire', KEYS[1], ARGV[1])
end
return n
"""


class RedisLoginAttemptStore:
    """`LoginAttemptStore` over Redis."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def count(self, key: str) -> int:
        try:
            value = await self._client.get(key)
        except Exception:  # non-authoritative: an unreachable store answers "not throttled"
            logger.exception("reading the login-attempt counter %s failed; treating as 0", key)
            return 0
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):  # pragma: no cover - Redis never stores a non-int here
            return 0

    async def increment(self, key: str, *, window_s: int) -> int:
        try:
            result = await self._client.eval(_INCREMENT_SCRIPT, 1, key, str(window_s))
        except Exception:
            logger.exception("incrementing the login-attempt counter %s failed; uncounted", key)
            return 0
        return int(result)

    async def clear(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except Exception:
            logger.exception("clearing the login-attempt counter %s failed", key)
