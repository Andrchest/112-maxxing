"""`VoiceHealthSubscriber` — the pub/sub loop, with no Redis and no database (E18-B).

The loop's whole contract is: subscribe to `voice:health` on `start()`, hand every message to the
handler, survive a handler that raises, and leave no task behind on `stop()`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.infrastructure.health import VOICE_HEALTH_CHANNEL, VoiceHealthSubscriber


class FakePubSub:
    """The four methods `VoiceHealthSubscriber` uses, over a queue a test feeds."""

    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = False
        self.queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed.append(channel)

    async def aclose(self) -> None:
        self.closed = True

    async def get_message(self, **kwargs: Any) -> Any:
        return await self.queue.get()


class FakeRedis:
    """Just enough `redis.asyncio.Redis` to hand out one `FakePubSub`."""

    def __init__(self, pubsub: FakePubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self) -> FakePubSub:
        return self._pubsub


async def _drain(handled: list[str | bytes], expected: int) -> None:
    for _ in range(200):
        if len(handled) >= expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"only {len(handled)} of {expected} messages reached the handler")


async def test_every_message_reaches_the_handler_and_stop_leaves_no_task() -> None:
    """`start()` subscribes to the documented channel; `stop()` unsubscribes and closes."""
    pubsub = FakePubSub()
    handled: list[str | bytes] = []

    async def handler(raw: str | bytes) -> None:
        handled.append(raw)

    before = len(asyncio.all_tasks())
    subscriber = VoiceHealthSubscriber(FakeRedis(pubsub), handler)  # type: ignore[arg-type]
    await subscriber.start()
    await subscriber.start()  # idempotent: starting twice must not open a second subscription
    await pubsub.queue.put({"data": '{"service": "llm"}'})
    await pubsub.queue.put({"data": b'{"service": "tts"}'})
    await pubsub.queue.put({"data": 42})  # not a payload at all — skipped, not fatal
    await _drain(handled, 2)
    await subscriber.stop()

    assert pubsub.subscribed == [VOICE_HEALTH_CHANNEL]
    assert pubsub.unsubscribed == [VOICE_HEALTH_CHANNEL]
    assert pubsub.closed is True
    assert handled == ['{"service": "llm"}', b'{"service": "tts"}']
    assert len(asyncio.all_tasks()) == before, "stop() cancels *and awaits* the reader"


async def test_a_raising_handler_does_not_stop_the_loop() -> None:
    """A health change that cannot be recorded must not take the next one down with it."""
    pubsub = FakePubSub()
    handled: list[str | bytes] = []

    async def handler(raw: str | bytes) -> None:
        handled.append(raw)
        if len(handled) == 1:
            raise RuntimeError("the database went away")

    subscriber = VoiceHealthSubscriber(FakeRedis(pubsub), handler)  # type: ignore[arg-type]
    await subscriber.start()
    try:
        await pubsub.queue.put({"data": "first"})
        await pubsub.queue.put({"data": "second"})
        await _drain(handled, 2)
    finally:
        await subscriber.stop()

    assert handled == ["first", "second"]


async def test_stopping_a_subscriber_that_never_started_is_a_no_op() -> None:
    """The lifespan's `finally` must be safe even when `start()` never ran."""
    pubsub = FakePubSub()

    async def handler(raw: str | bytes) -> None:
        return None

    await VoiceHealthSubscriber(FakeRedis(pubsub), handler).stop()  # type: ignore[arg-type]

    assert pubsub.subscribed == []
    assert pubsub.closed is False
