"""Composition root of the voice-agent process (D2, D9, D13).

This is the voice agent's counterpart to `app.api.container`: the one module that knows both the
application layer and the adapters, so that nothing else has to. It builds, per call:

* the `VoiceTurnConfig` from `Settings` (§4.1) — never literals;
* the `VADProvider` for the configured provider (`energy` today; TODO(E12) `silero`);
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

from app.application.ports.call_transport import CallTransport
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.vad import VADProvider
from app.application.voice.config import VoiceTurnConfig, voice_turn_config_from_settings
from app.application.voice.events import VoiceEventAppender
from app.application.voice.recorder import RecordingPaths, SessionRecorder
from app.application.voice.resampler import Resampler
from app.application.voice.turn_detector import TurnDetector
from app.application.voice.turn_pipeline import TurnPipeline, TurnResponder
from app.config.settings import Settings
from app.domain.common.ids import SessionId
from app.inference.vad import EnergyVAD
from app.infrastructure.recording.wav_writer import WavFileSink

__all__ = ["VoiceAgentDeps", "build_pipeline", "build_transport", "build_vad"]

#: `SIM_CALL_TRANSPORT` values this process understands (D9).
TRANSPORT_FAKE = "fake"
TRANSPORT_LIVEKIT = "livekit"
TRANSPORT_SIP = "sip"

#: `vad.provider` values. `energy` is the gate's and the fallback (`60-inference-ops.md` §1).
VAD_ENERGY = "energy"
VAD_SILERO = "silero"


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


def build_vad(settings: Settings, config: VoiceTurnConfig) -> VADProvider:
    """The configured `VADProvider`.

    TODO(E12): `SileroVAD` for `SIM_VAD_PROVIDER=silero`, which every model profile selects. Until
    then the value is accepted and falls back to `EnergyVAD` with a warning rather than refusing
    to start, because §2.2 names the energy detector as the documented fallback when the onnx
    model is absent.
    """
    provider = getattr(settings, "vad_provider", VAD_ENERGY)
    if provider not in (VAD_ENERGY, VAD_SILERO):
        raise ValueError(f"unknown VAD provider {provider!r}")
    return EnergyVAD(frame_samples=config.frame_samples, required_sample_rate=config.sample_rate)


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


def build_pipeline(
    deps: VoiceAgentDeps,
    *,
    session_id: SessionId,
    call_id: uuid.UUID,
    transport: CallTransport,
    started_at: datetime | None = None,
    responder: TurnResponder | None = None,
    record: bool = True,
) -> TurnPipeline:
    """One `TurnPipeline` for one call (§3.7)."""
    vad = build_vad(deps.settings, deps.config)
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
        responder=responder,
    )
