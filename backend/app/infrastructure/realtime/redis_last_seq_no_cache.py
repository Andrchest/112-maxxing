"""`RedisLastSeqNoCache` — the `session:{session_id}:last_seq_no` key of HLD §40.6.

§40.6: string, the highest published `seq_no`, TTL `SESSION_CACHE_TTL_S` (default 3600),
"refreshed on publish", read by the WebSocket handlers' heartbeat frames. "Loss ⇒ the handler
reads `MAX(seq_no)` from PostgreSQL instead" — so every failure here answers `None` and lets the
caller fall back, and no failure ever propagates: a heartbeat must not kill a socket.

The key name is the §40.6 one, with the session UUID in canonical lowercase hyphenated form and
no braces ("Placeholder note").
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.domain.common.ids import SessionId

__all__ = ["RedisLastSeqNoCache", "session_last_seq_no_key"]

logger = logging.getLogger(__name__)


def session_last_seq_no_key(session_id: SessionId) -> str:
    """`session:{session_id}:last_seq_no` (§40.6)."""
    return f"session:{str(session_id).lower()}:last_seq_no"


class RedisLastSeqNoCache:
    """`LastSeqNoCache` over one Redis string key per session."""

    def __init__(self, client: Redis, ttl_s: int) -> None:
        self._client = client
        self._ttl_s = ttl_s

    async def get(self, session_id: SessionId) -> int | None:
        """The cached maximum, or `None` when the key is missing, unreadable or not an integer."""
        try:
            raw = await self._client.get(session_last_seq_no_key(session_id))
        except Exception:  # Redis is non-authoritative (§40.6, SPEC §31)
            logger.warning("reading the last_seq_no cache failed; falling back to PostgreSQL")
            return None
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning("the last_seq_no cache holds a non-integer; falling back to PostgreSQL")
            return None

    async def set(self, session_id: SessionId, seq_no: int) -> None:
        """`SET … EX SESSION_CACHE_TTL_S`; a failure is logged and swallowed."""
        try:
            await self._client.set(session_last_seq_no_key(session_id), seq_no, ex=self._ttl_s)
        except Exception:  # Redis is non-authoritative (§40.6, SPEC §31)
            logger.warning(
                "refreshing the last_seq_no cache failed; heartbeats will read PostgreSQL"
            )
