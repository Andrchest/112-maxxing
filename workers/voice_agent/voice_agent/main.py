"""The voice-agent process entry point (D9, §3.7, `60-inference-ops.md` §4.3, SPEC §15).

A separate process, not a backend thread. It:

1. loads `Settings` and builds the `VoiceTurnConfig`, the `Clock` and the `UnitOfWorkFactory` —
   the **same** Unit of Work the backend uses, because D9 requires the agent to append
   `SessionEvent`s through the same `seq_no` row lock and never via REST;
2. subscribes to `voice:join` (§40.6, `{session_id, room, call_id}`) and starts one `TurnPipeline`
   per call, plus a `voice:cancel:{session_id}` subscription for that call's hang-up/abort;
3. warms the inference components up in `60-inference-ops.md` §4.2's **sequential** order — VAD,
   then ASR, then the LLM — and heartbeats one `voice:health:{service}` key per warmed
   component with `SET … EX voice_health_ttl_s` every `voice_health_heartbeat_s` seconds. A
   missing key means
   NOT_READY, which is what the backend's `ring` guard reads as "the media plane cannot take a
   call" (E11's ruling on §10.8). A component goes WARMING → READY on a successful warm-up and
   WARMING → NOT_READY on a failure, and it keeps heartbeating NOT_READY rather than going
   silent, so the backend can tell "down" from "never started";
4. shuts down gracefully on SIGINT/SIGTERM: every pipeline is asked to stop, every recording is
   closed, the heartbeat key is deleted so the backend sees NOT_READY immediately rather than
   after the TTL.

The agent owns no domain rule (D9). It never decides a session's state; it produces audio,
recordings and events.

`voice:health:tts` is deliberately still absent: §4.2's sequence has four steps and this process
owns three of them today. Publishing READY for a component that does not exist would be a lie the
`ring` guard then trusts, so the TTS key arrives with the epic that brings the component —
TODO(E14).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import signal
import uuid
import wave
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.application.ports.asr import ASRProvider
from app.application.ports.call_transport import CallTransport
from app.application.ports.llm import LLMClient
from app.application.ports.vad import VADProvider
from app.application.voice.config import BYTES_PER_SAMPLE, MS_PER_S
from app.config.settings import Settings, get_settings
from app.domain.common.ids import SessionId
from app.infrastructure.clock import SystemClock
from app.infrastructure.transport.redis_voice_signals import JOIN_CHANNEL, cancel_channel

from voice_agent.providers import build_asr, build_vad
from voice_agent.wiring import (
    VoiceAgentDeps,
    build_dialogue_llm,
    build_pipeline,
    build_transport,
)

__all__ = ["VoiceAgent", "main", "run", "synthetic_tone"]

logger = logging.getLogger(__name__)

#: `voice:health:{service}` of `60-inference-ops.md` §4.3.
HEALTH_KEY_PREFIX = "voice:health:"
VAD_SERVICE = "vad"
ASR_SERVICE = "asr"
LLM_SERVICE = "llm"
#: The components this process warms up and heartbeats, in §4.2's warm-up order.
#: TODO(E14): `"tts"`.
HEALTH_SERVICES: tuple[str, ...] = (VAD_SERVICE, ASR_SERVICE, LLM_SERVICE)
#: `HealthStatus` (§4.1). `FATAL` is E18's admin-clearable state and is not published here.
STATE_READY = "READY"
STATE_WARMING = "WARMING"
STATE_NOT_READY = "NOT_READY"

#: The ASR warm-up transcribes `SIM_ASR_WARMUP_SAMPLE_PATH` when it is set; with no sample it
#: synthesises one second of a tone, which warms the graph without shipping an audio file.
WARMUP_TONE_MS = 1000
WARMUP_TONE_HZ = 440.0
#: Peak amplitude of the synthetic warm-up tone: loud enough not to be silence, quiet enough not
#: to clip. It is never played to anyone.
WARMUP_TONE_AMPLITUDE = 0.3
_INT16_MAX = 32767


@dataclass(frozen=True, slots=True)
class _ComponentHealth:
    """One `voice:health:{service}` payload's variable part (§4.3)."""

    state: str
    provider: str | None = None
    model_version: str | None = None
    detail: str | None = None
    warmup_ms: int = 0


def synthetic_tone(
    sample_rate: int, *, duration_ms: int = WARMUP_TONE_MS, frequency: float = WARMUP_TONE_HZ
) -> bytes:
    """`duration_ms` of a mono s16le sine at `frequency` — the ASR warm-up's fallback audio.

    Deterministic and dependency-free (no numpy in this process's warm-up path), so a warm-up is
    the same every time and a failure to warm up is a fact about the model rather than the tone.
    """
    samples = (sample_rate * duration_ms) // MS_PER_S
    pcm = bytearray(samples * BYTES_PER_SAMPLE)
    for index in range(samples):
        value = math.sin(2.0 * math.pi * frequency * index / sample_rate)
        scaled = int(value * WARMUP_TONE_AMPLITUDE * _INT16_MAX)
        pcm[index * BYTES_PER_SAMPLE : (index + 1) * BYTES_PER_SAMPLE] = scaled.to_bytes(
            BYTES_PER_SAMPLE, "little", signed=True
        )
    return bytes(pcm)


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
        #: Built once per process, warmed once, shared by every call (§4.2).
        self._vad: VADProvider | None = None
        self._asr: ASRProvider | None = None
        self._llm: LLMClient | None = None
        #: `service -> (state, provider, model_version, warmup_ms, detail)`, what the heartbeat
        #: republishes every `voice_health_heartbeat_s` seconds (§4.3).
        self._health: dict[str, _ComponentHealth] = {
            service: _ComponentHealth(state=STATE_NOT_READY) for service in HEALTH_SERVICES
        }

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

    def health_state(self, service: str) -> str:
        """The last published state of one component (§4.1's `HealthStatus`)."""
        return self._health[service].state

    async def publish_health(self, state: str | None = None) -> None:
        """`SET voice:health:{service} {...} EX voice_health_ttl_s` for every component (§4.3).

        `state` overrides every component's own state; it exists for the one case that is about
        the *process* rather than a component — a caller that wants to force the whole set.
        """
        for service in HEALTH_SERVICES:
            await self._publish_component(service, state)

    async def _publish_component(self, service: str, state: str | None = None) -> None:
        settings = self._deps.settings
        health = self._health[service]
        payload = json.dumps(
            {
                "state": state or health.state,
                "profile": settings.model_profile,
                "provider": health.provider,
                "model_version": health.model_version,
                "updated_at": self._deps.clock.now().isoformat(),
                "detail": health.detail,
                "warmup_ms": health.warmup_ms,
            }
        )
        await self._redis.set(self.health_key(service), payload, ex=settings.voice_health_ttl_s)

    async def clear_health(self) -> None:
        """Delete every heartbeat key so the backend sees NOT_READY at once, not after the TTL."""
        for service in HEALTH_SERVICES:
            with contextlib.suppress(Exception):
                await self._redis.delete(self.health_key(service))

    async def _heartbeat(self) -> None:
        interval = self._deps.settings.voice_health_heartbeat_s
        while not self._stopping.is_set():
            try:
                await self.publish_health()
            except Exception:
                logger.exception("voice:health heartbeat failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)

    # -- warm-up (`60-inference-ops.md` §4.2) -------------------------------------------------

    async def warm_up(self) -> None:
        """§4.2's sequence, in order and **not** concurrently: VAD, then ASR, then the LLM.

        Sequential because the two share one GPU and one page cache: warming them at the same
        time measures contention rather than readiness, and on the 8 GB dev card it is how an
        out-of-memory failure is manufactured. Each component publishes WARMING before it starts
        and READY or NOT_READY when it finishes, so the backend's `ring` guard sees the
        transition rather than a silence.

        A failed warm-up is not a failed process: the component stays NOT_READY, keeps
        heartbeating, and `REQUIRE_INFERENCE_READY` is what decides whether a session may start.
        Crashing here would take the working components down with the broken one.
        """
        await self._warm_component(VAD_SERVICE, self._warm_vad)
        await self._warm_component(ASR_SERVICE, self._warm_asr)
        await self._warm_component(LLM_SERVICE, self._warm_llm)

    async def _warm_component(
        self, service: str, warm: Callable[[], Awaitable[tuple[str, str | None]]]
    ) -> None:
        self._health[service] = _ComponentHealth(state=STATE_WARMING)
        with contextlib.suppress(Exception):
            await self._publish_component(service)
        started_ms = self._deps.clock.monotonic_ms()
        try:
            provider, model_version = await warm()
        except Exception as exc:
            logger.exception("warming %s up failed; it stays NOT_READY", service)
            self._health[service] = _ComponentHealth(
                state=STATE_NOT_READY,
                detail=f"{type(exc).__name__}: {exc}",
                warmup_ms=max(0, self._deps.clock.monotonic_ms() - started_ms),
            )
        else:
            self._health[service] = _ComponentHealth(
                state=STATE_READY,
                provider=provider,
                model_version=model_version,
                warmup_ms=max(0, self._deps.clock.monotonic_ms() - started_ms),
            )
        with contextlib.suppress(Exception):
            await self._publish_component(service)

    async def _warm_vad(self) -> tuple[str, str | None]:
        """§4.2 step 1: load the model, `reset()`, score one zero frame."""
        vad = build_vad(self._deps.settings, self._deps.config)
        self._vad = vad
        await vad.warm_up()
        return vad.provider_name, None

    async def _warm_asr(self) -> tuple[str, str | None]:
        """§4.2 step 2: transcribe the warm-up sample, or one second of synthetic tone."""
        asr = build_asr(self._deps.settings)
        self._asr = asr
        await asr.warm_up()
        audio = self._warmup_audio(asr.required_sample_rate)
        await asr.transcribe(audio, asr.required_sample_rate, request_id=f"warmup:{ASR_SERVICE}")
        return asr.provider_name, asr.model_version

    async def _warm_llm(self) -> tuple[str, str | None]:
        """§4.2 step 3: build the dialogue `LLMClient` once per process and warm it up.

        `LLMClient.warm_up()` is the port's own "load and be ready" call; the client — not this
        process — knows whether that means an HTTP probe against llama-server or nothing at all
        (`FakeLLM`). A failure leaves `voice:health:llm` at NOT_READY and the process running, the
        same as a failed ASR warm-up: `REQUIRE_INFERENCE_READY` decides whether a session may
        start, and crashing here would take the working components down with the broken one.
        """
        llm = build_dialogue_llm(self._deps)
        self._llm = llm
        await llm.warm_up()
        return self._deps.settings.llm_provider, llm.model_name

    def _warmup_audio(self, sample_rate: int) -> bytes:
        """`SIM_ASR_WARMUP_SAMPLE_PATH`'s PCM, or a synthesised tone (§4.2).

        §4.2 asks for "a real RU WAV, not silence", because a CTC graph warmed on silence takes a
        different path than one warmed on speech. A configured sample is therefore used whenever
        there is one; the tone is the fallback for a checkout that has no audio fixture, and it
        is still not silence.
        """
        path = self._deps.settings.asr_warmup_sample_path
        if path:
            with contextlib.suppress(Exception), wave.open(path, "rb") as source:
                return source.readframes(source.getnframes())
            logger.warning("could not read %s; warming ASR on a synthetic tone instead", path)
        return synthetic_tone(sample_rate)

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
            self._deps,
            session_id=session_id,
            call_id=call_id,
            transport=transport,
            asr=self._asr,
            llm=self._llm,
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
        await self.warm_up()
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
