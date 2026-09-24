"""`RedisVoiceSignals` — `voice:join` and `voice:cancel:{session_id}` over Redis (§40.6, D9).

The two payloads are §40.6's, key for key:

* `voice:join` → `{session_id, room, call_id}`;
* `voice:cancel:{session_id}` → `{call_id, reason, at_offset_ms}`.

Both UUIDs are written in canonical lowercase hyphenated form, as §40.6 requires of the session id
in a channel name, and `{session_id}` in the cancel channel is the session UUID with no braces.

Neither publish ever raises. §40.6: losing `voice:join` means "the agent never joins" and the
backend re-publishes while the stage is `RINGING`; losing `voice:cancel` means "the caller
finishes one utterance into a closed call; no state is corrupted". Neither is worth failing a
committed command over, so a Redis error is logged at `warning` and swallowed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from uuid import UUID

from redis.asyncio import Redis

from app.domain.common.ids import SessionId

__all__ = ["JOIN_CHANNEL", "RedisVoiceSignals", "cancel_channel"]

logger = logging.getLogger(__name__)

JOIN_CHANNEL = "voice:join"
"""§40.6: one channel for every session; the payload names the session."""


def cancel_channel(session_id: SessionId) -> str:
    """`voice:cancel:{session_id}` — the session UUID, lowercase, no braces (§40.6)."""
    return f"voice:cancel:{str(session_id).lower()}"


class RedisVoiceSignals:
    """`VoiceSignalPublisher` over `redis.asyncio`."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def publish_join(
        self,
        session_id: SessionId,
        *,
        room: str,
        call_id: UUID,
        extra: Mapping[str, str | None] | None = None,
    ) -> None:
        """`voice:join` — `{session_id, room, call_id}`, plus a ДДС call's additive keys (I3 E6b,
        HLD 80 §80.3.6: `call_kind`, `assignment_id`, `persona_id`, `endpoint`)."""
        await self._publish(
            JOIN_CHANNEL,
            {
                "session_id": str(session_id).lower(),
                "room": room,
                "call_id": str(call_id).lower(),
                **(extra or {}),
            },
        )

    async def publish_cancel(
        self, session_id: SessionId, *, call_id: UUID, reason: str, at_offset_ms: int
    ) -> None:
        """`voice:cancel:{session_id}` — `{call_id, reason, at_offset_ms}`."""
        await self._publish(
            cancel_channel(session_id),
            {
                "call_id": str(call_id).lower(),
                "reason": reason,
                "at_offset_ms": at_offset_ms,
            },
        )

    async def _publish(self, channel: str, payload: dict[str, object]) -> None:
        try:
            await self._client.publish(channel, json.dumps(payload, ensure_ascii=False))
        except Exception:  # a signal is liveness, never correctness (§40.6)
            logger.warning("could not publish %s; the voice signal is lost", channel)
