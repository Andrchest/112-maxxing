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

**A service head's call (I3 E6c, HLD 80 §80.4).** `build_service_head_responder` puts
`ServiceHeadResponder` behind ASR instead of the frozen caller chain — `ResponderContextLoader`
(script + snapshot, the runner-side `responder_scripts` probe, no WorldTruth / CallerBelief
repository), the interpreter against the responder slot catalog, `ResponderTemplates` (or, under
`SIM_RESPONDER_DIALOGUE=llm`, the checked paraphrase) — and a `PersonaSpeechSink`: the same TTS
stage speaking in the persona's logical voice (`tts.voice_map` resolves it), which never touches
the scenario caller's emotion. The fixed lines come from the `voice_agent.tts_cache` cache when the
process has warmed it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.dds.end_dds_call import EndDdsCallBySystem
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
from app.application.dialogue.responder_context import ResponderContextLoader
from app.application.dialogue.service_head import LeakValuesProbe, ServiceHeadResponder
from app.application.dialogue.speech_sink import CallerSpeechSink, NullCallerSpeechSink
from app.application.dialogue.validator import ResponseValidator, validator_config_from_settings
from app.application.ports.asr import ASRProvider
from app.application.ports.call_transport import CallTransport
from app.application.ports.clock import Clock
from app.application.ports.inference_guard import InferenceGuard
from app.application.ports.llm import (
    ChatMessage,
    JsonSchemaSpec,
    LLMClient,
    LlmCompletion,
    LlmStreamDelta,
    LlmUsage,
)
from app.application.ports.metrics_recorder import MetricsRecorder
from app.application.ports.tts import TTSProvider, TtsVoiceSpec
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.vad import VADProvider
from app.application.simulation.responder_scripts import ScenarioResponderScripts
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
    TurnContext,
    TurnPipeline,
    TurnResponder,
)
from app.config.profile import active_profile, apply_profile, validate_vram_margin
from app.config.settings import Settings
from app.domain.common.ids import SessionId
from app.domain.dds.call import DdsCallEndReason
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
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
    "AGENT_IDENTITY_PREFIX",
    "AGENT_TOKEN_TTL_MINUTES",
    "VAD_ENERGY",
    "VAD_SILERO",
    "NullCallerSpeechSink",
    "PersonaSpeechSink",
    "ScriptedFakeDialogueLLM",
    "VoiceAgentDeps",
    "agent_participant_identity",
    "build_agent_token",
    "build_asr",
    "build_dialogue_responder",
    "build_leak_values",
    "build_llm",
    "build_metrics",
    "build_pipeline",
    "build_responder",
    "build_service_head_responder",
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
        """Load the turn config from `Settings` and freeze the process dependencies.

        Deliberately profile-agnostic: `settings` is used exactly as given, with no model-profile
        overlay. Every existing test in this package (and `voice_agent.providers`'s own gate
        selection, D13) builds `Settings` by hand and calls this directly, relying on the class
        defaults already being the gate's fake providers (`energy`/`fake`) — overlaying a profile
        here would silently swap those for `DEV_3060TI`'s real ones underneath every such test.
        `build_for_startup` below is the profile-aware counterpart for the real process.
        """
        return VoiceAgentDeps(
            settings=settings,
            clock=clock,
            uow_factory=uow_factory,
            config=voice_turn_config_from_settings(settings),
        )

    @staticmethod
    def build_for_startup(
        settings: Settings, clock: Clock, uow_factory: UnitOfWorkFactory
    ) -> VoiceAgentDeps:
        """The real process's entry point (E18-A, HLD 60 §2/§2.5): overlay the active model
        profile onto `settings` (`app.config.profile.apply_profile`), validate its VRAM margin,
        then delegate to `build`.

        `ProfileRefused` is left to propagate — an uncaught exception here, before any model is
        loaded, is what gives the voice-agent process its non-zero exit code at start-up, exactly
        like `app.api.container.build_container` does for the API. `voice_agent.main.run` is the
        intended caller; `main.py` is outside this task's file ownership (E18-A brief, FILES), so
        wiring this in there is left for whichever task owns that module's start-up sequence — see
        the E18-A task report's "HLD gaps".
        """
        profile = active_profile(settings)
        validate_vram_margin(profile)
        overlaid = apply_profile(settings, profile)
        return VoiceAgentDeps.build(overlaid, clock, uow_factory)


#: TTL of the token the agent mints for itself (E19-E3). A call is bounded by the session, not by
#: a clock the agent controls, so the only safe bound is "longer than any call anyone will run":
#: `VoiceTurnConfig.max_turn_ms` bounds one TURN (30 s), not the call, and
#: `Settings.livekit_token_ttl_minutes` (10) is the TRAINEE's browser token — deliberately short,
#: because a browser can ask the API for another one and the agent cannot. Two hours is the ruling's
#: ceiling and is checked only at join, so a long call already in progress is never cut off by it.
AGENT_TOKEN_TTL_MINUTES = 120

#: `participant_identity` of the agent in the room. One identity per CALL, not per session or per
#: process: LiveKit refuses a second participant with the same identity, so a reconnect or a second
#: call in the same session must not collide with a stale one.
AGENT_IDENTITY_PREFIX = "voice-agent"


def agent_participant_identity(call_id: uuid.UUID) -> str:
    """`voice-agent:<call_id>` — the identity the agent joins the room under (E19-E3)."""
    return f"{AGENT_IDENTITY_PREFIX}:{call_id}"


def build_agent_token(settings: Settings, *, room: str, call_id: uuid.UUID) -> str:
    """The agent's OWN LiveKit access token for `room`, minted locally (E19-E3, D9, SPEC §41).

    A LiveKit access token is a plain HS256 JWT over `SIM_LIVEKIT_API_SECRET`, which this process
    already holds — so the agent needs neither the SDK nor a REST call to the backend to obtain
    one, and D9's "the agent never talks to the backend via REST" is preserved. The signing code is
    the backend's own `LiveKitTokenService`, reused rather than copied, so the agent and the
    trainee's browser token can never drift apart in claims or algorithm
    (`check_imports.py` allows `voice_agent` → `app.infrastructure`; only `livekit` itself is
    confined to `voice_agent.transport`).

    **No token ever travels over Redis.** HLD 40's `voice:join` payload stays
    `{session_id, room, call_id}`; the agent mints from that, at the moment it joins.

    The grant is `LiveKitTokenService`'s: `roomJoin` on exactly this room, `canPublish` +
    `canSubscribe` (a call is two-way audio), and nothing else — no `roomAdmin`, no `roomCreate`,
    no `canPublishData`. The token is returned to one caller and never logged (SPEC §41).
    """
    from app.infrastructure.transport.livekit_token_service import LiveKitTokenService

    service = LiveKitTokenService(
        settings.livekit_api_key,
        settings.livekit_api_secret,
        livekit_url=settings.livekit_url,
        ttl_minutes=AGENT_TOKEN_TTL_MINUTES,
    )
    return service.mint(
        room_name=room, participant_identity=agent_participant_identity(call_id)
    ).token


def build_transport(
    settings: Settings,
    config: VoiceTurnConfig,
    *,
    token: str | None = None,
    clock: Clock | None = None,
    started_at: datetime | None = None,
) -> CallTransport:
    """The `CallTransport` named by `SIM_CALL_TRANSPORT` (D9).

    `fake` is the gate's (D13) and needs a `FakeClock`, so it is not built here: a process running
    against the fake transport constructs it in its own test. This factory covers the two
    transports a deployment can select.

    `clock` and `started_at` are the session's time base (R13): the LiveKit transport stamps every
    `AudioFrame.capture_offset_ms` and `TransportEvent.at_offset_ms` as a session offset through
    them, so that SPEC §27's `speech_end_to_first_audio_ms` subtracts two offsets with one origin.
    A LiveKit transport asked for without a `clock` is a wiring bug, not a default.
    """
    if settings.call_transport == TRANSPORT_LIVEKIT:
        from voice_agent.transport.livekit_transport import LiveKitCallTransport

        if not token:
            raise ValueError("the LiveKit transport needs a backend-minted access token")
        if clock is None:
            raise ValueError(
                "the LiveKit transport needs the session's Clock: its capture offsets are "
                "session offsets (R13)"
            )
        return LiveKitCallTransport(
            url=settings.livekit_url,
            token=token,
            outbound_queue_ms=config.outbound_queue_ms,
            outbound_sample_rate=config.sample_rate,
            clock=clock,
            started_at=started_at,
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
    guard: InferenceGuard | None = None,
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
        guard=guard,
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
    tts_fallback: TTSProvider | None = None,
    metrics: MetricsRecorder | None = None,
    guard: InferenceGuard | None = None,
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
        # E20-G/G5: `tts_fallback` is a parameter for the SAME reason `vad` is (E19-E2). It used to
        # be built here, fresh and UNWARMED, on every call, while `voice_agent.main` warmed a
        # *different* instance at start-up — so INV 14's "retry the whole utterance once on the
        # configured fallback" could only ever raise
        # `RuntimeError: PiperTTS.warm_up() must be called before stream()`, which surfaced as a
        # misleading `MODEL_ERROR{TIMEOUT}` and, to the trainee, as a silent caller (E20-C's §46
        # walk, open item 6). The process warms one fallback and passes it here.
        fallback_provider=(
            tts_fallback if tts_fallback is not None else build_tts_fallback(settings)
        ),
        metrics=metrics if metrics is not None else build_metrics(deps),
        clock=deps.clock,
        config=deps.config,
        uow_factory=deps.uow_factory,
        default_voice_id=settings.tts_voice_id,
        default_speaking_rate=settings.tts_speaking_rate,
        timeout_ms=settings.tts_timeout_ms,
        first_chunk_timeout_ms=settings.tts_first_chunk_timeout_ms,
        max_unit_chars=settings.tts_max_unit_chars,
        guard=guard,
    )


def build_dialogue_responder(
    deps: VoiceAgentDeps,
    *,
    llm: LLMClient | None = None,
    metrics: MetricsRecorder | None = None,
    sink: CallerSpeechSink | None = None,
    tts: TTSProvider | None = None,
    tts_fallback: TTSProvider | None = None,
    guard: InferenceGuard | None = None,
    operator_label_ru: str | None = None,
) -> DialogueResponder:
    """The whole E13 chain: interpreter → Fact Access Gate → generator → validator → §7.8 (R10).

    `operator_label_ru` (I3 E6b) is the one change a ДДС claimant call-back makes to this chain:
    the caller prompt names the other party «ДИСПЕТЧЕР» instead of «ОПЕРАТОР» (HLD 80 §80.3.4).

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
            (
                CallerPromptBuilder(caller_prompt_config_from_settings(settings))
                if operator_label_ru is None
                else CallerPromptBuilder(
                    caller_prompt_config_from_settings(settings),
                    operator_label_ru=operator_label_ru,
                )
            ),
            validator,
            config=generator_config_from_settings(settings),
        ),
        fallbacks=FallbackTemplates(),
        # E14: the real sink speaks the utterance. `NullCallerSpeechSink` stays importable —
        # a dialogue test that is about the *words* still wires it deliberately.
        sink=(
            sink
            if sink is not None
            else build_speech_sink(
                deps, tts=tts, tts_fallback=tts_fallback, metrics=recorder, guard=guard
            )
        ),
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


class PersonaSpeechSink(TtsSpeechSink):
    """E14's TTS stage speaking as a service head (I3 E6c): the persona's logical voice for every
    line, and no trigger on the scenario caller's emotion — the head is not the caller."""

    def __init__(self, *, voice: TtsVoiceSpec, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._persona_voice = voice

    async def _voice_for(self, session_id: SessionId) -> TtsVoiceSpec:
        return self._persona_voice

    async def _apply_interruption_trigger(self, context: TurnContext) -> None:
        return None


def build_leak_values(deps: VoiceAgentDeps) -> LeakValuesProbe:
    """Every world / caller value of the session's scenario — the `llm` leak check's list (D10).

    Read by code for code: the list never reaches a prompt (`ServiceHeadResponder`)."""
    from app.domain.scenario.validation import build_fact_definitions
    from app.domain.scenario.version import ScenarioVersion

    async def read(session_id: SessionId) -> list[str]:
        async with deps.uow_factory() as uow:
            session = await uow.sessions.get(session_id)
            document = (
                None
                if session is None
                else await uow.scenarios.get_version_document(session.scenario_version_id)
            )
        if document is None:
            return []
        definitions = build_fact_definitions(ScenarioVersion.model_validate(dict(document)))
        values: list[str] = []
        for definition in definitions.values():
            for value in (definition.world_value, definition.caller_value):
                if isinstance(value, str) and value.strip():
                    values.append(value)
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    values.append(str(value))
        return values

    return read


def build_service_head_responder(
    deps: VoiceAgentDeps,
    *,
    voice_id: str,
    llm: LLMClient | None = None,
    metrics: MetricsRecorder | None = None,
    tts: TTSProvider | None = None,
    tts_fallback: TTSProvider | None = None,
    guard: InferenceGuard | None = None,
    reference: Any = None,
) -> ServiceHeadResponder:
    """The service head's chain for one call (HLD 80 §80.4; see the module docstring)."""
    from app.infrastructure.reference.file_catalog import FileReferenceCatalog

    settings = deps.settings
    client = llm if llm is not None else build_dialogue_llm(deps)
    recorder = metrics if metrics is not None else build_metrics(deps)
    return ServiceHeadResponder(
        loader=ResponderContextLoader(
            deps.uow_factory,
            deps.clock,
            ScenarioResponderScripts(deps.uow_factory),
            reference if reference is not None else FileReferenceCatalog(settings.reference_dir),
        ),
        interpreter=DialogueInterpreter(
            client, recorder, config=interpreter_config_from_settings(settings)
        ),
        sink=PersonaSpeechSink(
            voice=TtsVoiceSpec(voice_id=voice_id, speaking_rate=settings.tts_speaking_rate),
            provider=tts if tts is not None else build_tts(settings),
            fallback_provider=(
                tts_fallback if tts_fallback is not None else build_tts_fallback(settings)
            ),
            metrics=recorder,
            clock=deps.clock,
            config=deps.config,
            uow_factory=deps.uow_factory,
            default_voice_id=voice_id,
            default_speaking_rate=settings.tts_speaking_rate,
            timeout_ms=settings.tts_timeout_ms,
            first_chunk_timeout_ms=settings.tts_first_chunk_timeout_ms,
            max_unit_chars=settings.tts_max_unit_chars,
            guard=guard,
        ),
        uow_factory=deps.uow_factory,
        mode=settings.responder_dialogue,
        llm=client,
        leak_values=build_leak_values(deps),
        llm_timeout_ms=settings.llm_interpreter_timeout_ms,
    )


class DdsCallEventAppender(VoiceEventAppender):
    """The voice appender of a ДДС call (I3 E6b): every event but `CALL_ENDED`.

    `CALL_ENDED` is the 112 call's event — `project_call_state` folds it into the operator's phone
    widget and it is pushed to the OPERATOR_112 socket — so a ДДС call-back must never write one;
    the backend's `DDS_CALL_ENDED` ends a ДДС call (HLD 80 §80.3.6). Every per-turn event passes
    through unchanged, under the call's `call_id`.

    The one `CALL_ENDED` a pipeline writes on its own authority — `TRANSPORT_LOST`, the media plane
    gone past `reconnect_grace_s` — becomes SYSTEM's `hang_up` of the ДДС call instead
    (`EndDdsCallBySystem`, `DDS_CALL_ENDED {reason: TRANSPORT_LOST}`). Every other reason (the
    trainee's hang-up, a `voice:cancel`, the browser leaving the room) is the backend's to record.
    """

    async def append(self, events: Sequence[DomainEvent], **rows: Any) -> list[SessionEvent]:
        kept: list[DomainEvent] = []
        for event in events:
            if event.event_type is not EventType.CALL_ENDED:
                kept.append(event)
            elif event.payload.get("reason") == DdsCallEndReason.TRANSPORT_LOST.value:
                await EndDdsCallBySystem(self._uow_factory, self._clock)(
                    self.session_id, uuid.UUID(str(event.payload["call_id"]))
                )
        return await super().append(kept, **rows)


def build_pipeline(
    deps: VoiceAgentDeps,
    *,
    session_id: SessionId,
    call_id: uuid.UUID,
    transport: CallTransport,
    started_at: datetime | None = None,
    responder: TurnResponder | None = None,
    vad: VADProvider | None = None,
    asr: ASRProvider | None = None,
    llm: LLMClient | None = None,
    tts: TTSProvider | None = None,
    tts_fallback: TTSProvider | None = None,
    metrics: MetricsRecorder | None = None,
    record: bool = True,
    guard: InferenceGuard | None = None,
    dds_call: bool = False,
    first_turn_index: int = 0,
    operator_label_ru: str | None = None,
    next_stage: TranscribedTurnResponder | None = None,
) -> TurnPipeline:
    """One `TurnPipeline` for one call (§3.7).

    **A ДДС claimant call-back (I3 E6b, HLD 80 §80.3.6)** is this very pipeline — the frozen caller
    chain, unchanged — built with three additive arguments: `dds_call` keeps the pipeline's
    `CALL_ENDED` out of the log (that event and `session:{id}:call_state` are the 112 call's; a
    ДДС call ends through `DDS_CALL_ENDED`, which the backend appends), `first_turn_index`
    continues the session's turn numbering (`dialogue_turns` is unique per session), and
    `operator_label_ru` is the prompt's speaker label («ДИСПЕТЧЕР»).

    **A service head's call (I3 E6c)** is the same pipeline with `dds_call` and `first_turn_index`
    and a different chain behind ASR: `next_stage` (`build_service_head_responder`) replaces the
    frozen caller chain, which is then not built at all.

    `vad`, `asr` and `llm` are built from `SIM_VAD_PROVIDER` / `SIM_ASR_PROVIDER` /
    `SIM_LLM_PROVIDER` when the caller does not supply them; the voice-agent process builds each
    **once** and passes it here so that a long-lived model is loaded per process, not per call.

    **`vad` is a parameter for a reason** (E19-E2). It used to be built here, unconditionally and
    per call, while `voice_agent.main.VoiceAgent._warm_vad` warmed a *different* instance it kept in
    `self._vad` and never passed on — so with `SIM_VAD_PROVIDER=silero` (every model profile) the
    first frame of the first real call raised `SileroVAD.warm_up() must be called before
    process()`. `EnergyVAD` (the gate's, D13) has no such precondition, which is why no gate test
    saw it. `60-inference-ops.md` §4.2 warms one instance per process at start-up, and
    `main.VoiceAgent`'s own comment already says the VAD is "built once per process, warmed once,
    shared by every call" — this parameter is what makes that true. Re-use across calls is safe
    because `TurnPipeline.run()` calls `vad.reset()` before the first frame of every call.

    **`metrics` is a parameter for the same reason, and this is H3 (E20-H).** Left to their own
    defaults, `build_responder` (the ASR side, which calls `register_turn`) and
    `build_dialogue_responder` (the TTS side, through `build_speech_sink`, which calls
    `record_turn_latency`) each fall back to their own `build_metrics(deps)` — **two different**
    `PgMetricsRecorder` instances, each with its own in-memory `turn_id -> turn_index` registry.
    `record_turn_latency` then looks up a `turn_id` nobody ever registered on *its* instance,
    logs "no turn_index is registered" and returns without writing, so
    `dialogue_turns.speech_end_to_first_audio_ms` — SPEC §27's own metric — stays `NULL` on every
    real call (reproduced on the real stack, E20-C's §46 walk item 16). One recorder, built once
    per call and threaded through both builders, is what makes the registration and the lookup
    the same dictionary.
    """
    vad = vad if vad is not None else build_vad(deps.settings, deps.config)
    provider = asr if asr is not None else build_asr(deps.settings)
    recorder = metrics if metrics is not None else build_metrics(deps)
    return TurnPipeline(
        session_id=session_id,
        call_id=call_id,
        transport=transport,
        vad=vad,
        detector=TurnDetector(deps.config, first_turn_index=first_turn_index),
        appender=(DdsCallEventAppender if dds_call else VoiceEventAppender)(
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
                metrics=recorder,
                next_stage=(
                    next_stage
                    if next_stage is not None
                    else build_dialogue_responder(
                        deps,
                        llm=llm,
                        tts=tts,
                        tts_fallback=tts_fallback,
                        metrics=recorder,
                        guard=guard,
                        operator_label_ru=operator_label_ru,
                    )
                ),
                guard=guard,
            )
        ),
        asr=provider,
        show_asr_partials=show_asr_partials(deps),
        guard=guard,
    )
