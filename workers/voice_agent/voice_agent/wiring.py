"""Composition root of the voice-agent process (D2, D9, D13).

This is the voice agent's counterpart to `app.api.container`: the one module that knows both the
application layer and the adapters, so that nothing else has to. It builds, per call:

* the `VoiceTurnConfig` from `Settings` (§4.1) — never literals;
* the `VADProvider` and the `ASRProvider` for the configured providers, through
  `voice_agent.providers` — the one module that knows a model's name (SPEC §19);
* the `CallTransport` for `SIM_CALL_TRANSPORT` (`fake` / `livekit`; `sip` is the documented stub);
* the `SessionRecorder` over two `WavFileSink`s under `Settings.data_dir` (§9.1, SPEC §41);
* the `VoiceEventAppender` over the **same** `UnitOfWork` the backend uses, so `seq_no` is
  allocated under the D5 row lock by whichever process appends (D9: "never via REST").

The agent owns no domain rule. It produces events and audio; every decision about session state
belongs to the backend's use cases.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.application.ports.asr import ASRProvider
from app.application.ports.call_transport import CallTransport
from app.application.ports.clock import Clock
from app.application.ports.metrics_recorder import MetricsRecorder
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.voice.asr_responder import (
    AsrTurnResponder,
    UnitOfWorkSessionStageResolver,
)
from app.application.voice.config import VoiceTurnConfig, voice_turn_config_from_settings
from app.application.voice.events import VoiceEventAppender
from app.application.voice.recorder import RecordingPaths, SessionRecorder
from app.application.voice.resampler import Resampler
from app.application.voice.turn_detector import TurnDetector
from app.application.voice.turn_pipeline import ShowAsrPartials, TurnPipeline, TurnResponder
from app.config.settings import Settings
from app.domain.common.ids import SessionId
from app.domain.session.policy import SESSION_POLICIES
from app.infrastructure.metrics import PgMetricsRecorder
from app.infrastructure.recording.wav_writer import WavFileSink

from voice_agent.providers import VAD_ENERGY, VAD_SILERO, build_asr, build_vad

__all__ = [
    "VAD_ENERGY",
    "VAD_SILERO",
    "VoiceAgentDeps",
    "build_asr",
    "build_metrics",
    "build_pipeline",
    "build_responder",
    "build_transport",
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
    next_stage: TurnResponder | None = None,
) -> AsrTurnResponder:
    """The head of the responder chain: ASR (§3.7, §4.5).

    `next_stage` is where E13 attaches the interpreter → gate → generator → validator chain and
    E14 the TTS playback behind it. With `None` the turn ends after `ASR_FINAL`, which is exactly
    what E12 owns.
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
    record: bool = True,
) -> TurnPipeline:
    """One `TurnPipeline` for one call (§3.7).

    `asr` is built from `SIM_ASR_PROVIDER` when the caller does not supply one; the voice-agent
    process builds it **once** and passes it here so that a long-lived model is loaded per
    process, not per call.
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
        responder=responder if responder is not None else build_responder(deps, asr=provider),
        asr=provider,
        show_asr_partials=show_asr_partials(deps),
    )
