"""`VoiceHealthSubscriber` — the backend's tail of the `voice:health` channel (§4.3, §40.6).

One long-lived task, started and stopped by the FastAPI lifespan next to the `SimulationRunner`
and disabled wherever the runner is (`SIM_RUNNER_ENABLED=false`), so an API test never leaves a
subscriber behind. `stop()` cancels *and awaits* the task and closes the pub/sub connection, which
is what `backend/tests/api/test_lifespan.py`'s task count asserts on.

Every message is handed to `AppendInferenceHealthChanged`, which owns the whole decision about
what to write. A handler that raises is logged and the loop continues: the inference health of the
next transition must not depend on the last one having been recordable, and a health change may
never take a session down with it (SPEC §39).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

from redis.asyncio import Redis

from app.infrastructure.health.voice_health import VOICE_HEALTH_CHANNEL

__all__ = ["VoiceHealthSubscriber"]

logger = logging.getLogger(__name__)

MessageHandler = Callable[[str | bytes], Awaitable[object]]
"""What the subscriber does with one raw message — `AppendInferenceHealthChanged.from_message`."""


class VoiceHealthSubscriber:
    """Subscribes to `voice:health` and feeds every message to `handler`."""

    def __init__(self, client: Redis, handler: MessageHandler) -> None:
        self._client = client
        self._handler = handler
        self._task: asyncio.Task[None] | None = None
        self._pubsub: object | None = None

    async def start(self) -> None:
        """Complete the `SUBSCRIBE` and start the reader task; starting twice is a no-op."""
        if self._task is not None:
            return
        pubsub = self._client.pubsub()
        await pubsub.subscribe(VOICE_HEALTH_CHANNEL)
        self._pubsub = pubsub
        self._task = asyncio.create_task(
            self._read(pubsub), name=f"voice-health-subscribe:{VOICE_HEALTH_CHANNEL}"
        )

    async def stop(self) -> None:
        """Cancel and await the reader, unsubscribe and close the connection."""
        task, pubsub = self._task, self._pubsub
        self._task, self._pubsub = None, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(VOICE_HEALTH_CHANNEL)  # type: ignore[attr-defined]
            finally:
                await pubsub.aclose()  # type: ignore[attr-defined]

    async def _read(self, pubsub: object) -> None:
        get_message = pubsub.get_message  # type: ignore[attr-defined]
        while True:
            message = await get_message(ignore_subscribe_messages=True, timeout=None)
            if message is None:
                continue
            data = message.get("data")
            if not isinstance(data, str | bytes):
                continue
            try:
                await self._handler(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("recording a voice:health transition failed; the loop continues")
