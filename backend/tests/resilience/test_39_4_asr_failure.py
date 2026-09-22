"""SPEC §39 #4 — "ASR failure: do not corrupt state." (`docs/SPEC.md:1038-1039`).

The mechanism (HLD `60-inference-ops.md` §6, D9): `AsrTurnResponder` runs before any state write,
so a failing transcription logs `MODEL_ERROR{stage:"ASR"}` and writes **nothing else** — no
`ASR_FINAL`, no `transcript_segments` row, no `dialogue_turns` row, no handover to the dialogue
stage. `test_inv_14_asr_failure_keeps_session.py` already proves this against real PostgreSQL with
a full session snapshot diff; this module drives the same public seam (`AsrTurnResponder`) over the
lighter in-memory `VoiceStore` for exactly SPEC §39's own wording, and closes on "never silently
reset": nothing an earlier turn wrote is dropped or rewritten by a later, healthy one.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.asr_responder import AsrTurnResponder
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.turn_detector import DetectedTurn, TurnEndReason
from app.application.voice.turn_pipeline import (
    TranscribedTurn,
    TranscribedTurnResponder,
    TurnContext,
)
from app.domain.common.ids import RoleStageId, SessionId
from app.domain.events.types import EventType
from app.inference.asr import FakeASR

from tests.resilience.conftest import assert_prefix_preserved
from tests.unit.application.voice.conftest import InMemoryVoiceUnitOfWork, VoiceStore, uow_factory

CALL_ID = uuid.UUID("39494949-3949-4949-8949-394949494949")
STAGE_ID = RoleStageId(uuid.UUID("39494949-3949-4949-8949-394949494950"))
TEXT_RU = "Второй ход: машина сбила человека"


class RecordingNextStage(TranscribedTurnResponder):
    """Whether the dialogue stage was ever reached — a failed turn must never hand over."""

    def __init__(self) -> None:
        self.handed: list[TranscribedTurn] = []

    async def respond_transcribed(self, transcribed: TranscribedTurn, context: TurnContext) -> None:
        self.handed.append(transcribed)


async def a_stage(session_id: SessionId) -> RoleStageId | None:
    return STAGE_ID


def a_turn(config: VoiceTurnConfig, *, index: int = 0) -> DetectedTurn:
    return DetectedTurn(
        turn_id=uuid.uuid4(),
        turn_index=index,
        audio=b"\x10\x27" * (config.sample_rate // 2),
        start_ms=1000 * (index + 1),
        end_ms=1000 * (index + 1) + 500,
        is_barge_in=False,
        pre_roll_ms=config.pre_roll_ms,
        end_reason=TurnEndReason.ENDPOINT_SILENCE,
        discarded_short=False,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def config() -> VoiceTurnConfig:
    return VoiceTurnConfig()


@pytest.fixture
def store() -> VoiceStore:
    return VoiceStore()


@pytest.fixture
def factory(store: VoiceStore, clock: FakeClock) -> Callable[[], InMemoryVoiceUnitOfWork]:
    return uow_factory(store, clock)


@pytest.fixture
def session_id() -> SessionId:
    return SessionId(uuid.uuid4())


def a_context(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> TurnContext:
    return TurnContext(
        session_id=session_id,
        call_id=CALL_ID,
        config=config,
        transport=FakeCallTransport(clock=clock),
        appender=VoiceEventAppender(
            session_id=session_id, uow_factory=factory, clock=clock, started_at=clock.now()
        ),
        recorder=None,
    )


async def test_an_asr_failure_writes_only_model_error_and_never_hands_over(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """SPEC §39 #4: a failing ASR call corrupts nothing — it writes exactly one `MODEL_ERROR`."""
    before = list(store.events)
    next_stage = RecordingNextStage()
    responder = AsrTurnResponder(
        asr=FakeASR([RuntimeError("CUDA error: out of memory")]),
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        stage_resolver=a_stage,  # type: ignore[arg-type]
        timeout_ms=4000,
        next_stage=next_stage,
    )

    await responder.respond(a_turn(config), a_context(session_id, factory, clock, config))

    assert [event.event_type for event in store.events] == [EventType.MODEL_ERROR]
    assert store.transcripts == [], "no transcript_segments row may be written on a failed ASR"
    assert store.turns == [], "no dialogue_turns row may be written on a failed ASR"
    assert next_stage.handed == [], "a failed turn must never reach the dialogue stage"
    error = store.events[0].payload
    assert error["component"] == "ASR"
    assert error["recoverable"] is True
    assert_prefix_preserved(before, store.events)


async def test_the_next_turn_transcribes_normally_and_the_failing_turn_is_untouched(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """'Do not corrupt state' means the next turn still works and turn 0's log stays intact."""
    next_stage = RecordingNextStage()
    responder = AsrTurnResponder(
        asr=FakeASR([RuntimeError("boom"), TEXT_RU]),
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        stage_resolver=a_stage,  # type: ignore[arg-type]
        timeout_ms=4000,
        next_stage=next_stage,
    )
    context = a_context(session_id, factory, clock, config)

    await responder.respond(a_turn(config, index=0), context)
    turn_0_snapshot = list(store.events)
    await responder.respond(a_turn(config, index=1), context)

    assert_prefix_preserved(turn_0_snapshot, store.events)
    new_types = [event.event_type for event in store.events[len(turn_0_snapshot) :]]
    assert EventType.ASR_FINAL in new_types
    assert [transcript.text for transcript in store.transcripts] == [TEXT_RU]
    assert len(next_stage.handed) == 1, "only the healthy turn reaches the dialogue stage"
