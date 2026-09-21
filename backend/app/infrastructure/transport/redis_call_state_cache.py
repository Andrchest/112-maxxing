"""`RedisCallStateCache` — §40.6's `session:{id}:call_state` string key (SPEC §31, D5).

`SET key <json> EX SESSION_CACHE_TTL_S` on write, `GET` on read, and nothing else. The key is a
*cache* of `app.application.operator.views.project_call_state`; §40.6's invariant ("Redis holds
nothing that cannot be rebuilt from PostgreSQL") is what makes every failure below a miss rather
than an error.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.domain.common.ids import SessionId

__all__ = ["RedisCallStateCache", "call_state_key"]

logger = logging.getLogger(__name__)


def call_state_key(session_id: SessionId) -> str:
    """`session:{session_id}:call_state` — the session UUID, lowercase, no braces (§40.6)."""
    return f"session:{str(session_id).lower()}:call_state"


class RedisCallStateCache:
    """`CallStateCache` over `redis.asyncio`; every failure is a miss."""

    def __init__(self, client: Redis, ttl_s: int) -> None:
        self._client = client
        self._ttl_s = ttl_s

    async def get(self, session_id: SessionId) -> str | None:
        """The cached JSON document, or `None`."""
        try:
            raw = await self._client.get(call_state_key(session_id))
        except Exception:  # an unreachable Redis is a cache miss (§40.6)
            return None
        if isinstance(raw, bytes):  # a client built without `decode_responses=True`
            return raw.decode("utf-8", errors="replace")
        return raw if isinstance(raw, str) else None

    async def put(self, session_id: SessionId, document: str) -> None:
        """`SET … EX SESSION_CACHE_TTL_S`; a failure loses the cache and nothing else."""
        try:
            await self._client.set(call_state_key(session_id), document, ex=self._ttl_s)
        except Exception:
            logger.warning("could not cache the call state of session %s", session_id)
