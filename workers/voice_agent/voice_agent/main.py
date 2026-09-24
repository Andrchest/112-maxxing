"""The voice-agent process entry point (D9, §3.7, `60-inference-ops.md` §4.3, SPEC §15).

A separate process, not a backend thread. It:

1. loads `Settings` and builds the `VoiceTurnConfig`, the `Clock` and the `UnitOfWorkFactory` —
   the **same** Unit of Work the backend uses, because D9 requires the agent to append
   `SessionEvent`s through the same `seq_no` row lock and never via REST;
2. subscribes to `voice:join` (§40.6, `{session_id, room, call_id}`) and starts one `TurnPipeline`
   per call, plus a `voice:cancel:{session_id}` subscription for that call's hang-up/abort;
   calls are keyed by `(session_id, call_id)` (I3 E6b, HLD 80 §80.3.6): a ДДС call-back to the
   claimant (`call_kind: CLAIMANT`) runs beside the session's 112 call, on the same frozen caller
   pipeline, and never writes the 112 call's `CALL_ENDED` or `session:{id}:call_state`; a call to a
   service head (`call_kind: SERVICE_HEAD`, I3 E6c) and the AI 112 operator (`call_kind:
   OPERATOR_112`, I3 E6d) run the responder chain instead (`build_service_head_responder`) in the
   persona's voice;
3. warms the inference components up in `60-inference-ops.md` §4.2's **sequential** order — VAD,
   then ASR, then the LLM, then TTS — and heartbeats one `voice:health:{service}` key per warmed
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

§4.2's sequence has four steps and this process now runs all four: VAD, ASR, the LLM and — since
E14 — TTS, each with its own `voice:health:{service}` key.
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
from datetime import datetime
from pathlib import Path
from typing import Any

from app.application.dialogue.prompt_builder import DISPATCHER_LABEL_RU
from app.application.ports.asr import ASRProvider
from app.application.ports.call_transport import CallTransport
from app.application.ports.llm import LLMClient
from app.application.ports.tts import TTSProvider, TtsVoiceSpec
from app.application.ports.vad import VADProvider
from app.application.voice.config import BYTES_PER_SAMPLE, MS_PER_S
from app.application.voice.events import VoiceEventAppender, call_ended_event
from app.config.settings import Settings, get_settings
from app.domain.common.ids import SessionId
from app.domain.dds.call import DdsCallKind
from app.inference.errors import InferenceOutOfMemoryError, ModelNotAvailableError
from app.infrastructure.clock import SystemClock
from app.infrastructure.transport.redis_voice_signals import JOIN_CHANNEL, cancel_channel

from voice_agent.health import (
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_REWARM_INTERVAL_S,
    STATE_FATAL,
    STATE_NOT_READY,
    STATE_READY,
    STATE_WARMING,
    GuardedLLMClient,
    HealthTransition,
    InferenceHealth,
    InferenceHealthGuard,
)
from voice_agent.preflight_http import PreflightHttpServer, resolve_preflight_port
from voice_agent.providers import build_asr, build_vad
from voice_agent.tts_cache import CACHE_DIR_NAME, CachedTTSProvider, TtsLineCache
from voice_agent.wiring import (
    TRANSPORT_LIVEKIT,
    VoiceAgentDeps,
    build_agent_token,
    build_dialogue_llm,
    build_pipeline,
    build_service_head_responder,
    build_transport,
    build_tts,
    build_tts_fallback,
)

__all__ = [
    "HEALTH_CHANNEL",
    "HEALTH_FATAL_KEY",
    "STATE_FATAL",
    "STATE_NOT_READY",
    "STATE_READY",
    "STATE_WARMING",
    "VoiceAgent",
    "main",
    "run",
    "synthetic_tone",
]

logger = logging.getLogger(__name__)

#: `voice:health:{service}` of `60-inference-ops.md` §4.3.
HEALTH_KEY_PREFIX = "voice:health:"
VAD_SERVICE = "vad"
ASR_SERVICE = "asr"
LLM_SERVICE = "llm"
TTS_SERVICE = "tts"
#: The components this process warms up and heartbeats, in §4.2's warm-up order.
HEALTH_SERVICES: tuple[str, ...] = (VAD_SERVICE, ASR_SERVICE, LLM_SERVICE, TTS_SERVICE)

#: `voice:join.call_kind` of the session's 112 call — absent from the payload means this (§80.3.6).
CALL_KIND_CALLER = "CALLER"
#: The ДДС call kinds this build runs: the claimant call-back on the frozen caller chain (I3 E6b),
#: the service head (I3 E6c) and the AI 112 operator (I3 E6d) on the responder chain.
SUPPORTED_DDS_CALL_KINDS: frozenset[str] = frozenset(
    {DdsCallKind.CLAIMANT.value, DdsCallKind.SERVICE_HEAD.value, DdsCallKind.OPERATOR_112.value}
)
#: The ДДС call kinds whose AI party is a persona on the responder chain (HLD 80 §80.3.6).
RESPONDER_CALL_KINDS: frozenset[str] = frozenset(
    {DdsCallKind.SERVICE_HEAD.value, DdsCallKind.OPERATOR_112.value}
)

#: `CALL_ENDED.reason` when the call's transport could not be built at all (E19-E3). A free `str`
#: like the pipeline's own `TRANSPORT_CLOSED` / `TRANSPORT_LOST` / `CANCELLED`, and deliberately
#: distinct from them: those three mean a media plane that existed and then did not.
CALL_ENDED_TRANSPORT_UNAVAILABLE = "TRANSPORT_UNAVAILABLE"
#: §4.3: every transition is announced here, and the backend turns each message into an
#: `INFERENCE_HEALTH_CHANGED` on every ACTIVE session. Same literal as the reader's
#: `app.infrastructure.health.voice_health.VOICE_HEALTH_CHANNEL`.
HEALTH_CHANNEL = "voice:health"
#: §4.3: FATAL is additionally mirrored here **without an expiry**, so that a restart loop cannot
#: make a fatal condition look transient. Cleared only by `clearInferenceFatal` (ADMIN) or by a
#: clean warm-up after a manual restart.
HEALTH_FATAL_KEY = "voice:health:fatal"
#: `60-inference-ops.md` §4.2 step 4: the text the TTS warm-up synthesises and drains to the end.
WARMUP_TTS_TEXT_RU = "Алло, я вас слушаю."
#: §4.1's unrecoverable warm-up failures: a missing model file and a GPU allocation failure both go
#: straight to FATAL rather than being retried every `rewarm_interval_s` seconds forever. Every
#: other exception (a timeout, a connection refused, a worker that is not up yet) is recoverable.
UNRECOVERABLE_WARMUP_ERRORS: tuple[type[BaseException], ...] = (
    InferenceOutOfMemoryError,
    ModelNotAvailableError,
)

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
    """One `voice:health:{service}` payload's variable part (§4.3).

    The `state` field is **not** here any more (E18-C): §4.1's state is owned by
    `voice_agent.health.ServiceHealth`, the pure state machine, and this record carries only the
    descriptive half of the frame — which provider answered, which model version it reported, how
    long the warm-up took. Two sources of truth for one state is how a FATAL service ends up
    heartbeating READY.
    """

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
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        rewarm_interval_s: int = DEFAULT_REWARM_INTERVAL_S,
        preflight_http: bool = False,
    ) -> None:
        self._deps = deps
        self._redis = redis
        #: Injectable so a test can drive the whole agent against `FakeCallTransport` (D13).
        self._transport_factory = transport_factory or self._default_transport
        #: One pipeline per call, keyed by `(session_id, call_id)` (I3 E6b, HLD 80 §80.3.6): the
        #: 112 call and a ДДС call of the same session are two entries.
        self._calls: dict[tuple[SessionId, uuid.UUID], asyncio.Task[None]] = {}
        self._stopping = asyncio.Event()
        #: The service heads' pre-synthesised lines (I3 E6c, `voice_agent.tts_cache`): filled in
        #: the background after the warm-up, per persona voice, and read back from disk.
        self._line_cache = TtsLineCache(
            Path(deps.settings.data_dir) / CACHE_DIR_NAME / deps.settings.tts_provider
        )
        #: Built once per process, warmed once, shared by every call (§4.2).
        self._vad: VADProvider | None = None
        self._asr: ASRProvider | None = None
        self._llm: LLMClient | None = None
        self._tts: TTSProvider | None = None
        #: The CONFIGURED TTS **fallback** (`SIM_TTS_FALLBACK_PROVIDER`), warmed beside the primary
        #: at start-up (E20-G/G5). `None` means either "no fallback configured" or "its warm-up
        #: failed" — the two are told apart by `_tts_fallback_detail`.
        self._tts_fallback: TTSProvider | None = None
        #: `"fallback unavailable: …"` once the fallback's warm-up has failed; surfaced as the
        #: `detail` of `voice:health:tts` (§4.3) so a degraded-but-serving process says so.
        self._tts_fallback_detail: str | None = None
        #: The WARN of a failed fallback warm-up is logged ONCE per process, not on every re-warm
        #: cycle (§4.1's `rewarm_interval_s` would otherwise fill the log).
        self._tts_fallback_warned = False
        #: `service -> detail` a warm step wants carried into the SUCCESS frame (a component that
        #: came up READY but degraded). Consumed by `_warm_component`.
        self._warm_details: dict[str, str] = {}
        #: §4.1's four state machines. `health.failure_threshold` / `health.rewarm_interval_s`
        #: come from the active profile's `health` block (`app.config.profile.HealthProfile`).
        self._states = InferenceHealth(
            services=HEALTH_SERVICES,
            failure_threshold=failure_threshold,
            rewarm_interval_s=rewarm_interval_s,
        )
        #: §4.4's `guard_inference(stage)`, one per process, handed to every call's pipeline.
        self._guard = InferenceHealthGuard(
            self._states,
            self._apply_transition,
            monotonic_s=lambda: self._deps.clock.monotonic_ms() / MS_PER_S,
        )
        #: `service -> (provider, model_version, warmup_ms, detail)`, the descriptive half of the
        #: frame the heartbeat republishes every `voice_health_heartbeat_s` seconds (§4.3).
        self._health: dict[str, _ComponentHealth] = {
            service: _ComponentHealth() for service in HEALTH_SERVICES
        }
        #: `GET /preflight/asr` and `GET /preflight/tts` (§5 checks 5-6). Off by default so a test
        #: never binds a socket; `run()`'s real process turns it on.
        self._preflight: PreflightHttpServer | None = (
            PreflightHttpServer(
                asr_probe=self._probe_asr,
                tts_probe=self._probe_tts,
                port=resolve_preflight_port(deps.settings),
            )
            if preflight_http
            else None
        )

    @property
    def active_sessions(self) -> tuple[SessionId, ...]:
        """Sessions with a live pipeline (each once, however many calls it has)."""
        return tuple(dict.fromkeys(session_id for session_id, _call_id in self._calls))

    @property
    def active_calls(self) -> tuple[tuple[SessionId, uuid.UUID], ...]:
        """`(session_id, call_id)` of every live pipeline (I3 E6b)."""
        return tuple(self._calls)

    def _default_transport(
        self,
        session_id: SessionId,
        call_id: uuid.UUID,
        room: str,
        started_at: datetime | None = None,
    ) -> Any:
        """The call's `CallTransport`, with the agent's OWN access token when it needs one.

        `SIM_CALL_TRANSPORT=livekit` needs a token, and until E19-E3 nothing supplied one: this
        factory called `build_transport` with none, which raises, on the first line of `_run_call`
        and therefore outside its `try` — the task's exception was never retrieved and the agent
        silently never joined any room. The token is minted here, locally, per call, from the
        `{session_id, room, call_id}` the `voice:join` payload already carries (no token has ever
        travelled over Redis and none does now — HLD 40 §40.6).

        `started_at` is the session's own, read from the aggregate by `_run_call`: it is the origin
        the transport's capture offsets are defined against (R13), the same one this call's
        `VoiceEventAppender` stamps its events with.
        """
        if self._deps.settings.call_transport != TRANSPORT_LIVEKIT:
            return build_transport(self._deps.settings, self._deps.config)
        return build_transport(
            self._deps.settings,
            self._deps.config,
            token=build_agent_token(self._deps.settings, room=room, call_id=call_id),
            clock=self._deps.clock,
            started_at=started_at,
        )

    # -- health -------------------------------------------------------------------------------

    def health_key(self, service: str = VAD_SERVICE) -> str:
        """`voice:health:{service}`."""
        return f"{HEALTH_KEY_PREFIX}{service}"

    def health_state(self, service: str) -> str:
        """The current state of one component (§4.1's `HealthStatus`)."""
        return self._states.state(service)

    @property
    def guard(self) -> InferenceHealthGuard:
        """§4.4's guard, shared by every call's pipeline — what the OOM tests assert against."""
        return self._guard

    @property
    def states(self) -> InferenceHealth:
        """The four §4.1 state machines, read-only for a caller."""
        return self._states

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
        machine_state = self._states.state(service)
        payload = json.dumps(
            {
                "state": state or machine_state,
                "profile": settings.model_profile,
                "provider": health.provider,
                "model_version": health.model_version,
                "updated_at": self._deps.clock.now().isoformat(),
                "detail": health.detail or self._states[service].detail,
                "warmup_ms": health.warmup_ms,
            }
        )
        await self._redis.set(self.health_key(service), payload, ex=settings.voice_health_ttl_s)

    async def _apply_transition(self, transition: HealthTransition) -> None:
        """§4.3: refresh the service's key, announce the transition, latch FATAL.

        The order matters. The key is written first so that a backend reading `voice:health:{s}`
        the instant it hears the announcement already sees the new state; the announcement is what
        becomes `INFERENCE_HEALTH_CHANGED` on every ACTIVE session; and the un-expiring
        `voice:health:fatal` mirror is last, because it is the one write that outlives this process.

        Every step is individually suppressed: health bookkeeping must never take a call down, and
        a Redis that has gone away is exactly the condition the TTL already covers.
        """
        with contextlib.suppress(Exception):
            await self._publish_component(transition.service)
        with contextlib.suppress(Exception):
            await self._redis.publish(
                HEALTH_CHANNEL,
                json.dumps(
                    {
                        "service": transition.service,
                        "from": transition.from_state,
                        "to": transition.to_state,
                        "detail": transition.detail,
                        "at": self._deps.clock.now().isoformat(),
                    }
                ),
            )
        if transition.is_fatal:
            with contextlib.suppress(Exception):
                # No `ex=`: §4.3's mirror has no expiry by design.
                await self._redis.set(
                    HEALTH_FATAL_KEY,
                    json.dumps(
                        {
                            "service": transition.service,
                            "state": STATE_FATAL,
                            "detail": transition.detail,
                            "at": self._deps.clock.now().isoformat(),
                        }
                    ),
                )

    async def clear_health(self) -> None:
        """Delete every heartbeat key so the backend sees NOT_READY at once, not after the TTL.

        `voice:health:fatal` is **not** deleted here: a fatal condition that vanished because the
        process shut down is exactly the "restart loop makes a fatal look transient" failure §4.3
        latched the key to prevent. Only `clearInferenceFatal` or a clean warm-up clears it.
        """
        for service in HEALTH_SERVICES:
            with contextlib.suppress(Exception):
                await self._redis.delete(self.health_key(service))

    async def _clear_fatal_after_clean_warmup(self) -> None:
        """§4.3's other clearer: "a clean warm-up after a manual restart".

        A process restart is the manual part. If every service came up READY, no fatal condition
        survives and the latch is stale — leaving it would refuse every session for ever.
        """
        if self._states.any_fatal or not self._states.all_ready:
            return
        with contextlib.suppress(Exception):
            await self._redis.delete(HEALTH_FATAL_KEY)

    async def _heartbeat(self) -> None:
        interval = self._deps.settings.voice_health_heartbeat_s
        while not self._stopping.is_set():
            try:
                await self.publish_health()
            except Exception:
                logger.exception("voice:health heartbeat failed")
            try:
                # §4.1's periodic re-warm rides the heartbeat: one periodic task, not five.
                await self._rewarm()
            except Exception:
                logger.exception("the periodic re-warm failed")
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
        for service, warm in self._warm_steps().items():
            await self._warm_component(service, warm)
        await self._clear_fatal_after_clean_warmup()

    def _warm_steps(self) -> dict[str, Callable[[], Awaitable[tuple[str, str | None]]]]:
        """§4.2's four steps, in order — also what the periodic re-warm loop looks a step up in."""
        return {
            VAD_SERVICE: self._warm_vad,
            ASR_SERVICE: self._warm_asr,
            LLM_SERVICE: self._warm_llm,
            TTS_SERVICE: self._warm_tts,
        }

    async def _warm_component(
        self, service: str, warm: Callable[[], Awaitable[tuple[str, str | None]]]
    ) -> None:
        """One §4.2 step, driven through §4.1's state machine.

        A FATAL service is skipped outright: `warm_started()` answers `None` for it, which is
        §4.1's "only a process restart leaves FATAL" as one branch rather than a flag.
        """
        started = self._states[service].warm_started()
        if started is None and self._states.state(service) == STATE_FATAL:
            logger.warning("%s is FATAL; §4.1 forbids re-warming it in this process", service)
            return
        self._health[service] = _ComponentHealth()
        self._warm_details.pop(service, None)
        if started is not None:
            await self._apply_transition(started)
        started_ms = self._deps.clock.monotonic_ms()
        try:
            provider, model_version = await warm()
        except Exception as exc:
            recoverable = not isinstance(exc, UNRECOVERABLE_WARMUP_ERRORS)
            logger.exception(
                "warming %s up failed; it becomes %s",
                service,
                STATE_NOT_READY if recoverable else STATE_FATAL,
            )
            self._health[service] = _ComponentHealth(
                detail=f"{type(exc).__name__}: {exc}",
                warmup_ms=max(0, self._deps.clock.monotonic_ms() - started_ms),
            )
            transition = self._states[service].warm_failed(
                recoverable=recoverable,
                detail=f"{type(exc).__name__}: {exc}",
                now_s=self._deps.clock.monotonic_ms() / MS_PER_S,
            )
        else:
            self._health[service] = _ComponentHealth(
                provider=provider,
                model_version=model_version,
                # A step that came up READY but DEGRADED says so in the frame (E20-G/G5: a TTS
                # whose configured fallback could not be warmed is still a serving TTS).
                detail=self._warm_details.pop(service, None),
                warmup_ms=max(0, self._deps.clock.monotonic_ms() - started_ms),
            )
            transition = self._states[service].warm_succeeded()
        if transition is not None:
            await self._apply_transition(transition)
        else:  # the state did not change, but the frame's descriptive half did
            with contextlib.suppress(Exception):
                await self._publish_component(service)

    async def _rewarm(self) -> None:
        """§4.1's periodic re-warm: NOT_READY → WARMING every `health.rewarm_interval_s`.

        Polled on the heartbeat's cadence rather than on a timer per service — the heartbeat is
        already the process's one periodic task, and `ServiceHealth.due_for_rewarm` is what decides
        whether enough time has passed. FATAL is never due, so it is never retried.
        """
        steps = self._warm_steps()
        for service in self._states.due_for_rewarm(self._deps.clock.monotonic_ms() / MS_PER_S):
            if self._stopping.is_set():
                return
            logger.info("re-warming %s (§4.1 periodic re-warm)", service)
            await self._warm_component(service, steps[service])

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
        await llm.warm_up()
        # §4.4: the interpreter and the generator both reach the LLM through this one client, and
        # neither `app.application.dialogue` stage may know a health guard exists (D2/D3). Wrapping
        # the port object here is what puts both call sites behind `guard_inference("LLM")`.
        self._llm = GuardedLLMClient(llm, self._guard)
        return self._deps.settings.llm_provider, llm.model_name

    async def _warm_tts(self) -> tuple[str, str | None]:
        """§4.2 step 4: `stream(warmup.tts_text, default voice)`, **drained to completion**.

        Drained, not merely started: §2.4's contract is that the first chunk arrives without
        waiting for full synthesis, and a warm-up that stopped at the first chunk would leave the
        rest of the graph cold — which is exactly the 87-second cold call the measurements warn
        about. A failure leaves `voice:health:tts` NOT_READY and the process running, like every
        other component.

        The **configured fallback** (`SIM_TTS_FALLBACK_PROVIDER`) is warmed here too (E20-G/G5).
        It used to be left cold, so INV 14's "retry the whole utterance once on the fallback"
        could only ever fail — E20-C's §46 walk reproduced it verbatim:
        `RuntimeError: PiperTTS.warm_up() must be called before stream()`, surfacing to the
        trainee's timeline as a misleading `MODEL_ERROR{"error_code": "TIMEOUT"}` and to the
        trainee as a silent caller. A fallback that cannot be warmed is NEVER fatal: it is one
        WARN per process and a `fallback unavailable: …` detail on `voice:health:tts`, because a
        primary that works is still a working caller.
        """
        settings = self._deps.settings
        tts = build_tts(settings)
        self._tts = tts
        await tts.warm_up()
        stream = tts.stream(
            WARMUP_TTS_TEXT_RU,
            TtsVoiceSpec(
                voice_id=settings.tts_voice_id,
                speaking_rate=settings.tts_speaking_rate,
            ),
            request_id=f"warmup:{TTS_SERVICE}",
            max_chunk_ms=self._deps.config.tts_chunk_ms,
        )
        async for _chunk in stream:
            pass
        # After the primary is proven, so a slow fallback never delays the primary's own warm-up.
        await self._warm_tts_fallback()
        return tts.provider_name, tts.model_version

    async def _warm_tts_fallback(self) -> None:
        """Warm `SIM_TTS_FALLBACK_PROVIDER` beside the primary (E20-G/G5). Never raises.

        `"none"` (`build_tts_fallback` answers `None`) is a legitimate configuration — the gate's
        own — and is not a warning. Any other failure downgrades the frame's `detail` and is
        logged once; the caller's primary TTS is untouched, so `voice:health:tts` still reaches
        READY.
        """
        settings = self._deps.settings
        self._tts_fallback = None
        self._tts_fallback_detail = None
        try:
            fallback = build_tts_fallback(settings)
        except Exception as exc:  # an unrecognised provider name, configuration only
            self._note_fallback_unavailable(exc)
            return
        if fallback is None:
            return
        try:
            await fallback.warm_up()
        except Exception as exc:
            self._note_fallback_unavailable(exc)
            return
        self._tts_fallback = fallback

    def _note_fallback_unavailable(self, exc: BaseException) -> None:
        """One WARN per process, plus the `voice:health:tts` detail (§4.3)."""
        detail = f"fallback unavailable: {type(exc).__name__}: {exc}"
        self._tts_fallback_detail = detail
        self._warm_details[TTS_SERVICE] = detail
        if not self._tts_fallback_warned:
            self._tts_fallback_warned = True
            logger.warning(
                "the configured TTS fallback %r could not be warmed up (%s); INV 14's retry has "
                "no warmed provider to fall back on — the primary is unaffected",
                self._deps.settings.tts_fallback_provider,
                detail,
            )

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

    # -- the preflight endpoints (`60-inference-ops.md` §5, checks 5 and 6) --------------------

    async def _probe_asr(self) -> dict[str, Any]:
        """`GET /preflight/asr`: transcribe the warm-up sample with the **already loaded** ASR.

        Never loads: a provider that has not been warmed raises, which the HTTP layer turns into
        the 503 preflight reads as "ASR does not respond" — the truthful answer, and far better
        than a preflight that itself loads a model onto a card it is checking has room.
        """
        asr = self._asr
        if asr is None:
            raise RuntimeError("no ASR provider is loaded in this process (it was never warmed)")
        audio = self._warmup_audio(asr.required_sample_rate)
        started_ms = self._deps.clock.monotonic_ms()
        result = await asr.transcribe(
            audio, asr.required_sample_rate, request_id=f"preflight:{ASR_SERVICE}"
        )
        return {
            "text": result.text,
            "latency_ms": max(0, self._deps.clock.monotonic_ms() - started_ms),
            "provider": asr.provider_name,
            "model_version": asr.model_version,
        }

    async def _probe_tts(self) -> dict[str, Any]:
        """`GET /preflight/tts`: synthesise `warmup.tts_text` and report the audio it produced."""
        tts = self._tts
        if tts is None:
            raise RuntimeError("no TTS provider is loaded in this process (it was never warmed)")
        settings = self._deps.settings
        started_ms = self._deps.clock.monotonic_ms()
        output_audio_ms = 0
        stream = tts.stream(
            WARMUP_TTS_TEXT_RU,
            TtsVoiceSpec(voice_id=settings.tts_voice_id, speaking_rate=settings.tts_speaking_rate),
            request_id=f"preflight:{TTS_SERVICE}",
            max_chunk_ms=self._deps.config.tts_chunk_ms,
        )
        async for chunk in stream:
            output_audio_ms += chunk.audio_ms
        return {
            "output_audio_ms": output_audio_ms,
            "latency_ms": max(0, self._deps.clock.monotonic_ms() - started_ms),
            "provider": tts.provider_name,
            "model_version": tts.model_version,
        }

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
        idempotence here is not an optimisation — it is what makes the retry safe. Idempotence is
        per `(session_id, call_id)` (I3 E6b): the additive `call_kind` key (absent ⇒ `CALLER`, the
        112 call) says whose call it is, and a ДДС kind this build does not run is ignored.
        """
        try:
            payload = json.loads(raw)
            session_id = SessionId(uuid.UUID(str(payload["session_id"])))
            call_id = uuid.UUID(str(payload["call_id"]))
            room = str(payload["room"])
            call_kind = str(payload.get("call_kind") or CALL_KIND_CALLER)
            persona_id = payload.get("persona_id")
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            logger.warning("ignoring malformed voice:join payload %r", raw)
            return
        if call_kind != CALL_KIND_CALLER and call_kind not in SUPPORTED_DDS_CALL_KINDS:
            logger.warning("ignoring voice:join for a %s call: not run by this build", call_kind)
            return
        key = (session_id, call_id)
        if key in self._calls:
            return
        run = (
            self._run_call(session_id, call_id, room)
            if call_kind == CALL_KIND_CALLER
            else self._run_call(session_id, call_id, room, dds_call=True)
            if call_kind == DdsCallKind.CLAIMANT.value
            else self._run_call(
                session_id,
                call_id,
                room,
                dds_call=True,
                call_kind=call_kind,
                persona_id=None if persona_id is None else str(persona_id),
            )
        )
        self._calls[key] = asyncio.create_task(run, name=f"voice-call-{session_id}-{call_id}")

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

    async def _watch_cancel(self, session_id: SessionId, call_id: uuid.UUID, pipeline: Any) -> None:
        """`voice:cancel:{session_id}` for THIS call only → `pipeline.stop(reason)` (I3 E6b).

        The channel is per session and names the call; a ДДС call's pipeline must not stop on the
        112 call's hang-up, nor the other way round, so every message is filtered on `call_id`.
        """
        wanted = str(call_id).lower()
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(cancel_channel(session_id))
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    if str(data.get("call_id", "")).lower() != wanted:
                        continue
                    reason = str(data["reason"])
                except (KeyError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
                    continue
                logger.info("voice:cancel for ДДС call %s: %s", call_id, reason)
                await pipeline.stop(reason)
                return
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(cancel_channel(session_id))
                await pubsub.aclose()

    async def _next_turn_index(self, session_id: SessionId) -> int:
        """Where a ДДС call's turn numbering starts: after the session's last turn (I3 E6b).

        `dialogue_turns` is unique on `(session_id, turn_index)` and a new `TurnDetector` counts
        from 0, so a call-back after the 112 call would otherwise overwrite that call's turn rows.
        """
        try:
            async with self._deps.uow_factory() as uow:
                events = await uow.events.read(session_id)
        except Exception:
            logger.exception("could not read the turn numbering of session %s", session_id)
            return 0
        indices = [
            int(event.payload["turn_index"])
            for event in events
            if isinstance(event.payload.get("turn_index"), int)
        ]
        return max(indices) + 1 if indices else 0

    async def _run_call(
        self,
        session_id: SessionId,
        call_id: uuid.UUID,
        room: str,
        *,
        dds_call: bool = False,
        call_kind: str = CALL_KIND_CALLER,
        persona_id: str | None = None,
    ) -> None:
        """One call: build the transport, build the pipeline, run until the media plane goes away.

        **Everything that can fail is inside the `try`** (E19-E3). Building the transport used to
        sit on the line above it, so a failure there — the missing access token, a bad
        `SIM_CALL_TRANSPORT`, an unreachable LiveKit URL — raised inside a task created by
        `_on_join` whose exception nobody retrieves: no log line, no event, no call, and an agent
        that looked healthy while joining nothing. A failure now ends the call the way any other
        media-plane failure ends it, with `CALL_ENDED` carrying an explicit reason.
        """
        transport: CallTransport | None = None
        watcher: asyncio.Task[None] | None = None
        try:
            started_at = await self._session_started_at(session_id)
            transport = self._transport_factory(session_id, call_id, room, started_at)
            # I3 E6b (HLD 80 §80.3.4, §80.3.6): a claimant call-back is this same pipeline with
            # three additive arguments — no `CALL_ENDED`, the session's turn numbering continued,
            # and the prompt's speaker label «ДИСПЕТЧЕР».
            dds_options: dict[str, Any] = (
                {
                    "dds_call": True,
                    "first_turn_index": await self._next_turn_index(session_id),
                    "operator_label_ru": DISPATCHER_LABEL_RU,
                }
                if dds_call
                else {}
            )
            if call_kind in RESPONDER_CALL_KINDS:
                # I3 E6c (HLD 80 §80.4): the service head's chain behind ASR, in its own voice;
                # the fixed lines come from the warmed cache when there is one. I3 E6d: the AI
                # 112 operator is the same chain — the loader and the templates read the kind.
                dds_options["next_stage"] = build_service_head_responder(
                    self._deps,
                    voice_id=self._persona_voice(persona_id),
                    llm=self._llm,
                    tts=(
                        None
                        if self._tts is None
                        else CachedTTSProvider(self._tts, self._line_cache)
                    ),
                    tts_fallback=self._tts_fallback,
                    guard=self._guard,
                )
            pipeline = build_pipeline(
                self._deps,
                session_id=session_id,
                call_id=call_id,
                transport=transport,
                # R13: the transport's capture offsets and this pipeline's event offsets are
                # stamped against the SAME session origin, through the same helper. Passing it
                # here is also what stops `VoiceEventAppender` defaulting `started_at` to `None`
                # and stamping every event of a real call with offset 0.
                started_at=started_at,
                # Every one of these four is the instance `warm_up()` warmed at start-up (§4.2).
                # The VAD was missing here until E19-E2, so `build_pipeline` built an unwarmed one
                # per call and `SileroVAD.process()` refused the first frame of the first real call.
                vad=self._vad,
                asr=self._asr,
                llm=self._llm,
                tts=self._tts,
                # E20-G/G5: the fallback instance THIS process warmed at start-up, so INV 14's
                # retry has a warmed provider to fall back on.
                tts_fallback=self._tts_fallback,
                guard=self._guard,
                **dds_options,
            )
            await transport.connect(call_id)
            if dds_call:
                watcher = asyncio.create_task(
                    self._watch_cancel(session_id, call_id, pipeline),
                    name=f"voice-cancel-{session_id}-{call_id}",
                )
            await pipeline.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("voice pipeline failed for session %s", session_id)
            if transport is None and not dds_call:
                # The pipeline never existed, so nothing else will ever write `CALL_ENDED` for this
                # call and the trainee-facing timeline would simply stop. Say why (SPEC §39, "never
                # silently reset the simulation"). A ДДС call writes no `CALL_ENDED` (I3 E6b): the
                # trainee still holds «Положить трубку», and the line is theirs to put down.
                await self._end_call_unavailable(session_id, call_id)
        finally:
            if watcher is not None:
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await watcher
            if transport is not None:
                with contextlib.suppress(Exception):
                    await transport.disconnect()
            self._calls.pop((session_id, call_id), None)

    def _persona_voice(self, persona_id: str | None) -> str:
        """The logical voice of `persona_id` in the reference pack, else `SIM_TTS_VOICE_ID`."""
        for persona in self._personas():
            if persona.id == persona_id:
                return persona.voice_id
        return self._deps.settings.tts_voice_id

    def _personas(self) -> list[Any]:
        """Every persona of every pack of the reference directory (I3 E6c), or none."""
        try:
            from app.infrastructure.reference.file_catalog import FileReferenceCatalog

            catalog = FileReferenceCatalog(self._deps.settings.reference_dir).catalog()
        except Exception:
            logger.exception("the reference pack's personas could not be read")
            return []
        found: dict[str, Any] = {}
        for pack_id in catalog.pack_ids:
            personas = catalog.personas(pack_id)
            if personas is not None:
                for persona in personas.personas:
                    found.setdefault(persona.id, persona)
        return list(found.values())

    async def warm_line_cache(self) -> int:
        """Pre-synthesise every persona's fixed lines in its voice (I3 E6c, `tts_cache`).

        Runs in the background after the warm-up, never before READY: with a whole-utterance TTS
        it takes minutes the first time, and a restart reads the files back instead. Returns how
        many lines are cached; a failure is only a smaller cache."""
        from app.application.dialogue.responder_templates import ResponderTemplates

        if self._tts is None:
            return 0
        templates = ResponderTemplates()
        by_voice: dict[str, list[str]] = {}
        for persona in self._personas():
            by_voice.setdefault(persona.voice_id, []).extend(templates.static_lines(persona))
        cached = 0
        settings = self._deps.settings
        for voice_id, lines in by_voice.items():
            if self._stopping.is_set():
                break
            try:
                cached += await self._line_cache.warm(
                    self._tts,
                    TtsVoiceSpec(voice_id=voice_id, speaking_rate=settings.tts_speaking_rate),
                    lines,
                )
            except Exception:
                logger.exception("warming the line cache for %s failed", voice_id)
        return cached

    async def _session_started_at(self, session_id: SessionId) -> datetime | None:
        """The session's `started_at` — the origin every offset of this call is measured from.

        Read once per call from the aggregate, never cached across calls: it is persisted state
        (SPEC §39, D7), which is exactly why an offset derived from it survives a restart of
        either process. `None` (an unreadable or not-yet-started session) degrades to the
        behaviour that was there before R13 rather than refusing the call: `session_offset_ms`
        answers `0` for it, and the call still runs.
        """
        try:
            async with self._deps.uow_factory() as uow:
                session = await uow.sessions.get(session_id)
        except Exception:
            logger.exception("could not read started_at for session %s", session_id)
            return None
        return None if session is None else session.started_at

    async def _end_call_unavailable(self, session_id: SessionId, call_id: uuid.UUID) -> None:
        """`CALL_ENDED{reason: TRANSPORT_UNAVAILABLE}` for a call whose transport never existed.

        Best-effort and never raising: this runs on a path that is already failing, and an append
        that fails here must not replace one logged failure with a different one.
        """
        try:
            appender = VoiceEventAppender(
                session_id=session_id, uow_factory=self._deps.uow_factory, clock=self._deps.clock
            )
            offset_ms = appender.offset_ms()
            await appender.append(
                [
                    call_ended_event(
                        call_id=call_id,
                        offset_ms=offset_ms,
                        at_offset_ms=offset_ms,
                        duration_ms=0,
                        reason=CALL_ENDED_TRANSPORT_UNAVAILABLE,
                    )
                ]
            )
        except Exception:
            logger.exception(
                "could not append CALL_ENDED for the unavailable transport of session %s",
                session_id,
            )

    # -- lifecycle ----------------------------------------------------------------------------

    async def run(self) -> None:
        """Serve until `stop()`."""
        await self.warm_up()
        if self._preflight is not None:
            # After the warm-up, deliberately: both endpoints probe the **loaded** providers and a
            # socket that answered 503 for the whole warm-up would be noise, not information.
            await self._preflight.start()
        heartbeat = asyncio.create_task(self._heartbeat(), name="voice-heartbeat")
        joins = asyncio.create_task(self._join_subscription(), name="voice-join")
        lines = asyncio.create_task(self.warm_line_cache(), name="voice-line-cache")
        try:
            await self._stopping.wait()
        finally:
            for task in (heartbeat, joins, lines):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if self._preflight is not None:
                await self._preflight.stop()
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
    """Build the process dependencies and serve (the `python -m voice_agent.main` body).

    **The profile is validated first, before a socket or an engine exists** (HLD 60 §2.5, R1):
    `active_profile` + `validate_vram_margin` run inside `VoiceAgentDeps.build_for_startup`, and a
    `ProfileRefused` propagates out of `main()` uncaught, which is what gives this process its
    non-zero exit. No env var downgrades it to a warning. Because it happens before `Redis.from_url`
    and `create_async_engine`, a refused profile also never writes a single `voice:health:*` key —
    a process that will not run must not first advertise itself as warming up.
    """
    from app.application.ports.event_publisher import EventPublisher
    from app.config.profile import active_profile, validate_vram_margin
    from app.infrastructure.persistence.unit_of_work import unit_of_work_factory
    from app.infrastructure.realtime.redis_publisher import RedisEventPublisher
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    resolved = settings or get_settings()
    clock = SystemClock()
    # Fail fast, before a socket or an engine exists: `ProfileRefused` here exits the process.
    # (`build_for_startup` below runs both of these again — it is the one profile-aware entry
    # point, E18-A — but the refusal must land before any I/O, so it is also checked here.)
    profile = active_profile(resolved)
    validate_vram_margin(profile)
    #: `redis_url` / `database_url` are required env fields that no profile carries, so they are
    #: read off `resolved`; every model knob comes from `deps.settings` after the overlay.
    redis: Any = Redis.from_url(resolved.redis_url)
    engine = create_async_engine(resolved.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    publisher: EventPublisher = RedisEventPublisher(redis, resolved.session_cache_ttl_s)
    deps = VoiceAgentDeps.build_for_startup(
        resolved, clock, unit_of_work_factory(session_factory, clock, publisher)
    )
    agent = VoiceAgent(
        deps,
        redis,
        failure_threshold=profile.health.failure_threshold,
        rewarm_interval_s=profile.health.rewarm_interval_s,
        preflight_http=True,
    )

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
