"""Composition root of the voice-agent process (D2, D9, D13).

This is the voice agent's counterpart to `app.api.container`: the one module that knows both the
application layer and the adapters, so that nothing else has to. It builds, per call:

* the `VoiceTurnConfig` from `Settings` (§4.1) — never literals;
* the `VADProvider`, the `ASRProvider` and (E14) the `TTSProvider` for the configured providers,
  through `voice_agent.providers` — the one module that knows a model's name (SPEC §19);
* the `CallTransport` for `SIM_CALL_TRANSPORT` (`fake` / `livekit`; `sip` is the documented stub);
* the `SessionRecorder` over two `WavFileSink`s under `Settings.data_dir` (§9.1, SPEC §41);
* the `VoiceEventAppender` over the **same** `UnitOfWork` the backend uses, so `seq_no` is
  allocated under the D5 row lock by whichever process appends (D9: "never via REST").

The agent owns no domain rule. It produces events and audio; every decision about session state
belongs to the backend's use cases.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.dialogue.dialogue_context import DialogueContextLoader
from app.application.dialogue.fallbacks import FallbackTemplates
from app.application.dialogue.generator import (
    CALLER_JSON_SCHEMA,
    CallerResponseGenerator,
    generator_config_from_settings,
)
from app.application.dialogue.interpreter import (
    DialogueInterpreter,
    interpreter_config_from_settings,
)
from app.application.dialogue.prompt_builder import (
    CallerPromptBuilder,
    caller_prompt_config_from_settings,
)
from app.application.dialogue.responder import DialogueResponder
from app.application.dialogue.speech_sink import CallerSpeechSink, NullCallerSpeechSink
from app.application.dialogue.validator import ResponseValidator, validator_config_from_settings
from app.application.ports.asr import ASRProvider
from app.application.ports.call_transport import CallTransport
from app.application.ports.clock import Clock
from app.application.ports.llm import (
    ChatMessage,
    JsonSchemaSpec,
    LLMClient,
    LlmCompletion,
    LlmStreamDelta,
    LlmUsage,
)
from app.application.ports.metrics_recorder import MetricsRecorder
from app.application.ports.tts import TTSProvider
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.voice.asr_responder import (
    AsrTurnResponder,
    UnitOfWorkSessionStageResolver,
)
from app.application.voice.config import VoiceTurnConfig, voice_turn_config_from_settings
from app.application.voice.events import VoiceEventAppender
from app.application.voice.recorder import RecordingPaths, SessionRecorder
from app.application.voice.resampler import Resampler
from app.application.voice.tts_speech_sink import TtsSpeechSink
from app.application.voice.turn_detector import TurnDetector
from app.application.voice.turn_pipeline import (
    ShowAsrPartials,
    TranscribedTurnResponder,
    TurnPipeline,
    TurnResponder,
)
from app.config.settings import Settings
from app.domain.common.ids import SessionId
from app.domain.session.policy import SESSION_POLICIES
from app.infrastructure.metrics import PgMetricsRecorder
from app.infrastructure.recording.wav_writer import WavFileSink

from voice_agent.providers import (
    LLM_FAKE,
    VAD_ENERGY,
    VAD_SILERO,
    build_asr,
    build_llm,
    build_tts,
    build_tts_fallback,
    build_vad,
)

__all__ = [
    "VAD_ENERGY",
    "VAD_SILERO",
    "NullCallerSpeechSink",
    "ScriptedFakeDialogueLLM",
    "VoiceAgentDeps",
    "build_asr",
    "build_dialogue_responder",
    "build_llm",
    "build_metrics",
    "build_pipeline",
    "build_responder",
    "build_speech_sink",
    "build_transport",
    "build_tts",
    "build_tts_fallback",
    "build_vad",
    "show_asr_partials",
]

#: `SIM_CALL_TRANSPORT` values this process understands (D9).
TRANSPORT_FAKE = "fake"
TRANSPORT_LIVEKIT = "livekit"
TRANSPORT_SIP = "sip"


@dataclass(frozen=True, slots=True)
class VoiceAgentDeps:
    """Process-wide collaborators, built once and shared by every call."""

    settings: Settings
    clock: Clock
    uow_factory: UnitOfWorkFactory
    config: VoiceTurnConfig

    @staticmethod
    def build(settings: Settings, clock: Clock, uow_factory: UnitOfWorkFactory) -> VoiceAgentDeps:
        """Load the turn config from `Settings` and freeze the process dependencies."""
        return VoiceAgentDeps(
            settings=settings,
            clock=clock,
            uow_factory=uow_factory,
            config=voice_turn_config_from_settings(settings),
        )


def build_transport(
    settings: Settings, config: VoiceTurnConfig, *, token: str | None = None
) -> CallTransport:
    """The `CallTransport` named by `SIM_CALL_TRANSPORT` (D9).

    `fake` is the gate's (D13) and needs a `FakeClock`, so it is not built here: a process running
    against the fake transport constructs it in its own test. This factory covers the two
    transports a deployment can select.
    """
    if settings.call_transport == TRANSPORT_LIVEKIT:
        from voice_agent.transport.livekit_transport import LiveKitCallTransport

        if not token:
            raise ValueError("the LiveKit transport needs a backend-minted access token")
        return LiveKitCallTransport(
            url=settings.livekit_url,
            token=token,
            outbound_queue_ms=config.outbound_queue_ms,
            outbound_sample_rate=config.sample_rate,
        )
    if settings.call_transport == TRANSPORT_SIP:
        from voice_agent.transport.sip_transport import SipCallTransport

        return SipCallTransport()
    raise ValueError(
        f"SIM_CALL_TRANSPORT={settings.call_transport!r} has no voice-agent transport; "
        f"use {TRANSPORT_LIVEKIT!r}, or {TRANSPORT_FAKE!r} from a test"
    )


def build_recorder(
    deps: VoiceAgentDeps, *, session_id: SessionId, call_id: uuid.UUID
) -> SessionRecorder:
    """Two WAV sinks under `data_dir/recordings/{session_id}/` (§9.1, SPEC §41)."""
    from pathlib import Path

    paths = RecordingPaths.for_call(session_id, call_id)
    data_dir = Path(deps.settings.data_dir)
    return SessionRecorder(
        session_id=session_id,
        call_id=call_id,
        config=deps.config,
        clock=deps.clock,
        trainee_sink=WavFileSink(
            data_dir=data_dir,
            relative_path=paths.trainee,
            sample_rate=deps.config.sample_rate,
        ),
        caller_sink=WavFileSink(
            data_dir=data_dir,
            relative_path=paths.caller,
            sample_rate=deps.config.sample_rate,
        ),
    )


def build_metrics(deps: VoiceAgentDeps) -> MetricsRecorder:
    """`PgMetricsRecorder` over the same Unit of Work the events go through (§2.6, SPEC §27)."""
    return PgMetricsRecorder(deps.uow_factory)


def build_responder(
    deps: VoiceAgentDeps,
    *,
    asr: ASRProvider,
    metrics: MetricsRecorder | None = None,
    next_stage: TranscribedTurnResponder | None = None,
) -> AsrTurnResponder:
    """The head of the responder chain: ASR (§3.7, §4.5).

    `next_stage` is E13's `DialogueResponder` (interpreter → gate → generator → validator), and
    E14's TTS sits behind it through `CallerSpeechSink`. With `None` the turn ends after
    `ASR_FINAL`, which is exactly what E12 owns.
    """
    return AsrTurnResponder(
        asr=asr,
        metrics=metrics if metrics is not None else build_metrics(deps),
        clock=deps.clock,
        config=deps.config,
        stage_resolver=UnitOfWorkSessionStageResolver(deps.uow_factory),
        timeout_ms=deps.settings.asr_timeout_ms,
        next_stage=next_stage,
    )


class ScriptedFakeDialogueLLM:
    """A settings-free `LLMClient` that answers both dialogue calls *validly* (D13, R10).

    `FakeLLM` is a script reader with an empty script by default, so a gate run with
    `SIM_LLM_PROVIDER=fake` would see an empty completion, fall back at the interpreter and fall
    back again at the generator — a chain that is wired but never actually exercised. This
    decorator gives the fake a default script instead: a schema-valid `InterpretedUtterance` for
    an interpreter call and a schema-valid, validator-clean caller reply for a generation call, so
    the whole chain runs end to end with no model, no weights and no settings.

    It lives here rather than in `app.inference.llm.fake_llm` deliberately: the fake is a *test
    double* owned by the inference package, and a default script is a property of how this process
    wires it, not of the double.
    """

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner

    @property
    def model_name(self) -> str:
        """The wrapped fake's model name."""
        return self._inner.model_name

    @property
    def n_ctx(self) -> int:
        """The wrapped fake's context size."""
        return self._inner.n_ctx

    async def warm_up(self) -> None:
        """Warm the wrapped fake up."""
        await self._inner.warm_up()

    async def cancel(self, request_id: str) -> None:
        """Cancel on the wrapped fake."""
        await self._inner.cancel(request_id)

    async def close(self) -> None:
        """Close the wrapped fake."""
        await self._inner.close()

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        request_id: str,
        max_tokens: int,
        temperature: float,
        top_p: float = 0.95,
        response_format: JsonSchemaSpec | None = None,
        stop: Sequence[str] = (),
        extra_body: dict[str, Any] | None = None,
        timeout_ms: int,
    ) -> LlmCompletion:
        """A valid answer for whichever of the two dialogue calls this is."""
        await self._inner.complete(
            messages,
            request_id=request_id,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            response_format=response_format,
            stop=stop,
            extra_body=extra_body,
            timeout_ms=timeout_ms,
        )
        text = _default_fake_answer(response_format)
        return LlmCompletion(
            text=text,
            finish_reason="stop",
            usage=LlmUsage(prompt_tokens=0, completion_tokens=len(text) // 3),
            model=self._inner.model_name,
            request_id=request_id,
        )

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        request_id: str,
        max_tokens: int,
        temperature: float,
        top_p: float = 0.95,
        response_format: JsonSchemaSpec | None = None,
        stop: Sequence[str] = (),
        extra_body: dict[str, Any] | None = None,
        timeout_ms: int,
    ) -> AsyncIterator[LlmStreamDelta]:
        """One delta carrying the whole default answer."""

        async def _one() -> AsyncIterator[LlmStreamDelta]:
            yield LlmStreamDelta(text=_default_fake_answer(response_format), index=0, is_first=True)

        return _one()


#: The `JsonSchemaSpec.name` `CallerResponseGenerator` sends (`generator.py`).
_CALLER_SCHEMA_NAME = "caller_utterance"
#: A schema-valid `InterpretedUtterance`: it asks for nothing, so the gate's spontaneous pass is
#: what decides the turn — the deterministic half of the chain, which is what a fake should drive.
_DEFAULT_INTERPRETATION = (
    '{"speech_act": "QUESTION", "requested_facts": [], "operator_assertions": [], '
    '"confirmation_targets": [], "semantic_confidence": 0.5}'
)
#: A caller reply that passes every §7 check: no number, no name, no Latin run, one sentence.
_DEFAULT_CALLER_UTTERANCE = '{"utterance": "Да, я слушаю."}'


def _default_fake_answer(response_format: JsonSchemaSpec | None) -> str:
    if response_format is not None and response_format.name == _CALLER_SCHEMA_NAME:
        return _DEFAULT_CALLER_UTTERANCE
    if response_format is not None and response_format.schema is CALLER_JSON_SCHEMA:
        return _DEFAULT_CALLER_UTTERANCE
    return _DEFAULT_INTERPRETATION


def build_dialogue_llm(deps: VoiceAgentDeps) -> LLMClient:
    """`SIM_LLM_PROVIDER`'s client; the fake gets `ScriptedFakeDialogueLLM`'s default script."""
    llm = build_llm(deps.settings)
    if deps.settings.llm_provider == LLM_FAKE:
        return ScriptedFakeDialogueLLM(llm)
    return llm


def build_speech_sink(
    deps: VoiceAgentDeps,
    *,
    tts: TTSProvider | None = None,
    metrics: MetricsRecorder | None = None,
) -> TtsSpeechSink:
    """E14's `CallerSpeechSink`: `TTSProvider` → playback → events → recording (§3.7, §6, §9.1).

    The providers themselves come from `voice_agent.providers` (E14-B), the one module that knows
    a model's name (SPEC §19): `build_tts` for `SIM_TTS_PROVIDER` and `build_tts_fallback` for
    `SIM_TTS_FALLBACK_PROVIDER`, which answers `None` for `"none"` — the gate's selection, because
    a fallback that is itself a fake would make INV 14's "both providers failed" row untestable.
    """
    settings = deps.settings
    return TtsSpeechSink(
        provider=tts if tts is not None else build_tts(settings),
        fallback_provider=build_tts_fallback(settings),
        metrics=metrics if metrics is not None else build_metrics(deps),
        clock=deps.clock,
        config=deps.config,
        uow_factory=deps.uow_factory,
        default_voice_id=settings.tts_voice_id,
        default_speaking_rate=settings.tts_speaking_rate,
        timeout_ms=settings.tts_timeout_ms,
        first_chunk_timeout_ms=settings.tts_first_chunk_timeout_ms,
        max_unit_chars=settings.tts_max_unit_chars,
    )


def build_dialogue_responder(
    deps: VoiceAgentDeps,
    *,
    llm: LLMClient | None = None,
    metrics: MetricsRecorder | None = None,
    sink: CallerSpeechSink | None = None,
    tts: TTSProvider | None = None,
) -> DialogueResponder:
    """The whole E13 chain: interpreter → Fact Access Gate → generator → validator → §7.8 (R10).

    Every stage is its own object and every literal comes from `Settings` (§5.1, §5.2, §5.3, §7).
    The Fact Access Gate is not built here because it is a pure function, not a collaborator —
    `DialogueResponder` calls `evaluate_fact_access` directly, which is what keeps "the gate is
    deterministic domain code" (SPEC §21) true rather than configurable.
    """
    settings = deps.settings
    client = llm if llm is not None else build_dialogue_llm(deps)
    recorder = metrics if metrics is not None else build_metrics(deps)
    validator = ResponseValidator(validator_config_from_settings(settings))
    return DialogueResponder(
        loader=DialogueContextLoader(
            deps.uow_factory, deps.clock, window_turns=settings.dialogue_window_turns
        ),
        interpreter=DialogueInterpreter(
            client, recorder, config=interpreter_config_from_settings(settings)
        ),
        generator=CallerResponseGenerator(
            client,
            recorder,
            CallerPromptBuilder(caller_prompt_config_from_settings(settings)),
            validator,
            config=generator_config_from_settings(settings),
        ),
        fallbacks=FallbackTemplates(),
        # E14: the real sink speaks the utterance. `NullCallerSpeechSink` stays importable —
        # a dialogue test that is about the *words* still wires it deliberately.
        sink=sink if sink is not None else build_speech_sink(deps, tts=tts, metrics=recorder),
        uow_factory=deps.uow_factory,
    )


def show_asr_partials(deps: VoiceAgentDeps) -> ShowAsrPartials:
    """Reads `SessionPolicy.show_asr_partials` for the session, once per call (§4.5, D6).

    The policy is a pure function of the session's mode (§10.10), so this is one aggregate read
    and a dictionary lookup — no new table and no new port. A session that cannot be read denies
    partials, which is the conservative answer: an assessment run must never leak interim text
    because a database hiccup made the default the permissive one.
    """

    async def read(session_id: SessionId) -> bool:
        async with deps.uow_factory() as uow:
            session = await uow.sessions.get(session_id)
        if session is None:
            return False
        return SESSION_POLICIES[session.session_mode].show_asr_partials

    return read


def build_pipeline(
    deps: VoiceAgentDeps,
    *,
    session_id: SessionId,
    call_id: uuid.UUID,
    transport: CallTransport,
    started_at: datetime | None = None,
    responder: TurnResponder | None = None,
    asr: ASRProvider | None = None,
    llm: LLMClient | None = None,
    tts: TTSProvider | None = None,
    record: bool = True,
) -> TurnPipeline:
    """One `TurnPipeline` for one call (§3.7).

    `asr` and `llm` are built from `SIM_ASR_PROVIDER` / `SIM_LLM_PROVIDER` when the caller does
    not supply them; the voice-agent process builds each **once** and passes it here so that a
    long-lived model is loaded per process, not per call.
    """
    vad = build_vad(deps.settings, deps.config)
    provider = asr if asr is not None else build_asr(deps.settings)
    return TurnPipeline(
        session_id=session_id,
        call_id=call_id,
        transport=transport,
        vad=vad,
        detector=TurnDetector(deps.config),
        appender=VoiceEventAppender(
            session_id=session_id,
            uow_factory=deps.uow_factory,
            clock=deps.clock,
            started_at=started_at,
        ),
        clock=deps.clock,
        config=deps.config,
        resampler=Resampler(
            target_sample_rate=deps.config.sample_rate, frame_samples=vad.frame_samples
        ),
        recorder=build_recorder(deps, session_id=session_id, call_id=call_id) if record else None,
        responder=(
            responder
            if responder is not None
            else build_responder(
                deps,
                asr=provider,
                next_stage=build_dialogue_responder(deps, llm=llm, tts=tts),
            )
        ),
        asr=provider,
        show_asr_partials=show_asr_partials(deps),
    )
