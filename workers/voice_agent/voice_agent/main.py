"""The voice-agent process entry point (D9, §3.7, `60-inference-ops.md` §4.3, SPEC §15).

A separate process, not a backend thread. It:

1. loads `Settings` and builds the `VoiceTurnConfig`, the `Clock` and the `UnitOfWorkFactory` —
   the **same** Unit of Work the backend uses, because D9 requires the agent to append
   `SessionEvent`s through the same `seq_no` row lock and never via REST;
2. subscribes to `voice:join` (§40.6, `{session_id, room, call_id}`) and starts one `TurnPipeline`
   per call, plus a `voice:cancel:{session_id}` subscription for that call's hang-up/abort;
3. heartbeats `voice:health:vad` with `SET … EX voice_health_ttl_s` every
   `voice_health_heartbeat_s` seconds. A missing key means NOT_READY, which is what the backend's
   `ring` guard reads as "the media plane cannot take a call" (this task's ruling on §10.8);
4. shuts down gracefully on SIGINT/SIGTERM: every pipeline is asked to stop, every recording is
   closed, the heartbeat key is deleted so the backend sees NOT_READY immediately rather than
   after the TTL.

The agent owns no domain rule (D9). It never decides a session's state; it produces audio,
recordings and events.

TODO(E12): the warm-up sequence of `60-inference-ops.md` §4.2 (VAD → ASR → LLM → TTS) and the
`voice:health:{asr,llm,tts}` keys. E11 heartbeats `vad` only, because `EnergyVAD` is the only
inference component this epic ships and publishing READY for a component that does not exist
would be a lie the `ring` guard then trusts.
TODO(E13)/TODO(E14): the real `TurnResponder`; until then every call runs `NullTurnResponder`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.application.ports.call_transport import CallTransport
from app.config.settings import Settings, get_settings
from app.domain.common.ids import SessionId
from app.infrastructure.clock import SystemClock
from app.infrastructure.transport.redis_voice_signals import JOIN_CHANNEL, cancel_channel

from voice_agent.wiring import VoiceAgentDeps, build_pipeline, build_transport

__all__ = ["VoiceAgent", "main", "run"]

logger = logging.getLogger(__name__)

#: `voice:health:{service}` of `60-inference-ops.md` §4.3. E11 owns the VAD component only.
HEALTH_KEY_PREFIX = "voice:health:"
VAD_SERVICE = "vad"
STATE_READY = "READY"


class VoiceAgent:
    """One process: the join subscriber, the per-call pipelines and the heartbeat."""

    def __init__(
        self,
        deps: VoiceAgentDeps,
        redis: Any,
        *,
        transport_factory: Any = None,
    ) -> None:
        self._deps = deps
        self._redis = redis
        #: Injectable so a test can drive the whole agent against `FakeCallTransport` (D13).
        self._transport_factory = transport_factory or self._default_transport
        self._calls: dict[SessionId, asyncio.Task[None]] = {}
        self._stopping = asyncio.Event()

    @property
    def active_sessions(self) -> tuple[SessionId, ...]:
        """Sessions with a live pipeline."""
        return tuple(self._calls)

    def _default_transport(self, session_id: SessionId, call_id: uuid.UUID, room: str) -> Any:
        return build_transport(self._deps.settings, self._deps.config)

    # -- health -------------------------------------------------------------------------------

    def health_key(self, service: str = VAD_SERVICE) -> str:
        """`voice:health:{service}`."""
        return f"{HEALTH_KEY_PREFIX}{service}"

    async def publish_health(self, state: str = STATE_READY) -> None:
        """`SET voice:health:vad {...} EX voice_health_ttl_s` (§4.3)."""
        settings = self._deps.settings
        payload = json.dumps(
            {
                "state": state,
                "profile": settings.model_profile,
                "provider": "energy",
                "model_version": None,
                "updated_at": self._deps.clock.now().isoformat(),
                "detail": None,
                "warmup_ms": 0,
            }
        )
        await self._redis.set(self.health_key(), payload, ex=settings.voice_health_ttl_s)

    async def clear_health(self) -> None:
        """Delete the heartbeat key so the backend sees NOT_READY at once, not after the TTL."""
        with contextlib.suppress(Exception):
            await self._redis.delete(self.health_key())

    async def _heartbeat(self) -> None:
        interval = self._deps.settings.voice_health_heartbeat_s
        while not self._stopping.is_set():
            try:
                await self.publish_health()
            except Exception:
                logger.exception("voice:health heartbeat failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)

    # -- the join subscription ----------------------------------------------------------------

    async def _join_subscription(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(JOIN_CHANNEL)
        try:
            async for message in pubsub.listen():
                if self._stopping.is_set():
                    return
                if message.get("type") != "message":
                    continue
                await self._on_join(message["data"])
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(JOIN_CHANNEL)
                await pubsub.aclose()

    async def _on_join(self, raw: bytes | str) -> None:
        """Start a pipeline for `{session_id, room, call_id}`; a repeat join is a no-op (§40.6).

        `voice:join` is re-published every `VOICE_JOIN_RETRY_MS` while the call is RINGING, so
        idempotence here is not an optimisation — it is what makes the retry safe.
        """
        try:
            payload = json.loads(raw)
            session_id = SessionId(uuid.UUID(str(payload["session_id"])))
            call_id = uuid.UUID(str(payload["call_id"]))
            room = str(payload["room"])
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            logger.warning("ignoring malformed voice:join payload %r", raw)
            return
        if session_id in self._calls:
            return
        self._calls[session_id] = asyncio.create_task(
            self._run_call(session_id, call_id, room), name=f"voice-call-{session_id}"
        )

    async def _cancel_signals(self, session_id: SessionId) -> AsyncIterator[str]:
        """`voice:cancel:{session_id}` → the pipeline's `_control` task."""
        channel = cancel_channel(session_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    reason = str(json.loads(message["data"])["reason"])
                except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                    reason = "ABORT"
                yield reason
                return
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()

    async def _run_call(self, session_id: SessionId, call_id: uuid.UUID, room: str) -> None:
        transport: CallTransport = self._transport_factory(session_id, call_id, room)
        pipeline = build_pipeline(
            self._deps, session_id=session_id, call_id=call_id, transport=transport
        )
        try:
            await transport.connect(call_id)
            await pipeline.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("voice pipeline failed for session %s", session_id)
        finally:
            with contextlib.suppress(Exception):
                await transport.disconnect()
            self._calls.pop(session_id, None)

    # -- lifecycle ----------------------------------------------------------------------------

    async def run(self) -> None:
        """Serve until `stop()`."""
        heartbeat = asyncio.create_task(self._heartbeat(), name="voice-heartbeat")
        joins = asyncio.create_task(self._join_subscription(), name="voice-join")
        try:
            await self._stopping.wait()
        finally:
            for task in (heartbeat, joins):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await self._drain_calls()
            await self.clear_health()

    async def stop(self) -> None:
        """Ask the agent to wind down."""
        self._stopping.set()

    async def _drain_calls(self) -> None:
        tasks = list(self._calls.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._calls.clear()


async def run(settings: Settings | None = None) -> None:
    """Build the process dependencies and serve (the `python -m voice_agent.main` body)."""
    from app.application.ports.event_publisher import EventPublisher
    from app.infrastructure.persistence.unit_of_work import unit_of_work_factory
    from app.infrastructure.realtime.redis_publisher import RedisEventPublisher
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    resolved = settings or get_settings()
    clock = SystemClock()
    redis: Any = Redis.from_url(resolved.redis_url)
    engine = create_async_engine(resolved.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    publisher: EventPublisher = RedisEventPublisher(redis, resolved.session_cache_ttl_s)
    deps = VoiceAgentDeps.build(
        resolved, clock, unit_of_work_factory(session_factory, clock, publisher)
    )
    agent = VoiceAgent(deps, redis)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(agent.stop()))
    try:
        await agent.run()
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    """`python -m voice_agent.main`."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover - process entry
    main()
