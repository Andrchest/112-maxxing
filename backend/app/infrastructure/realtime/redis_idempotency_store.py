"""`RedisIdempotencyStore` — `idempotency:{user_id}:{client_command_id}` (HLD §40.6).

§40.6's key table, implemented literally: a Redis string holding the first response body of a
command, written with `SET … EX <IDEMPOTENCY_TTL_S>` (default 300 s, `SIM_IDEMPOTENCY_TTL_S`).

Redis is a *cache of an answer*, never the answer itself. Both methods therefore swallow every
client error and degrade to "not stored": a `get` that cannot reach Redis returns `None`, which
makes the command re-evaluate against PostgreSQL — §40.6's own documented loss behaviour — and a
`put` that fails costs nothing but the de-duplication of a retry. Nothing in the simulation state
depends on this key existing, which is what keeps SPEC §31's "a complete Redis flush loses no
simulation state" true.

Key names use the UUIDs in canonical lowercase hyphenated form and contain no braces (§40.6
"Placeholder note"), exactly like `redis_runner_lock.runner_lock_key`; the key itself is built by
`app.application.ports.idempotency_store.idempotency_key`, so the application and the adapter
cannot disagree about it.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

__all__ = ["RedisIdempotencyStore"]

logger = logging.getLogger(__name__)


class RedisIdempotencyStore:
    """`IdempotencyStore` over Redis (§40.6)."""

    def __init__(self, client: Redis, *, ttl_s: int) -> None:
        self._client = client
        #: `IDEMPOTENCY_TTL_S` (§40.6) — how long a first response stays replayable.
        self._ttl_s = ttl_s

    async def get(self, key: str) -> str | None:
        """The stored response body, or `None` — including when Redis is unreachable."""
        try:
            value = await self._client.get(key)
        except Exception:  # Redis is non-authoritative (§40.6): a miss re-evaluates the command
            logger.exception("reading the idempotency key %s failed; re-evaluating", key)
            return None
        return value if isinstance(value, str) else None

    async def put(self, key: str, value: str) -> None:
        """`SET key value EX ttl`; a failure only costs the de-duplication of a retry."""
        try:
            await self._client.set(key, value, ex=self._ttl_s)
        except Exception:  # see the module docstring: losing the note is a liveness cost only
            logger.exception("storing the idempotency key %s failed; a retry re-evaluates", key)
