"""`AsrTurnResponder` against fakes (§3.7, §4.5, §9.1, SPEC §17, §19, §27, §42 item 14).

Everything here runs on `FakeASR`, `FakeClock` and the in-memory Unit of Work of `conftest.py`:
the responder's job is bookkeeping — one transcription, one transaction, one metric — and none of
that needs a model or a database to be pinned down.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

import pytest
from app.application.ports.metrics_recorder import InferenceStage, NullMetricsRecorder
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.asr_responder import AsrTurnResponder, audio_duration_ms
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

from tests.unit.application.voice.conftest import InMemoryVoiceUnitOfWork, VoiceStore, uow_factory

CALL_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
STAGE_ID = RoleStageId(uuid.UUID("22222222-2222-4222-8222-222222222222"))
TEXT_RU = "Горит квартира на пятом этаже"


class RecordingNextStage:
    """A `TranscribedTurnResponder` that only remembers what it was handed (R1).

    The seam carries the transcript, not just the audio: E13's chain starts from the very text
    `ASR_FINAL` and the `transcript_segments` row were written from, so the two can never drift.
    """

    def __init__(self) -> None:
        self.handed: list[TranscribedTurn] = []

    @property
    def turns(self) -> list[DetectedTurn]:
        """The `DetectedTurn` of each handover, for the assertions E12 already had."""
        return [transcribed.turn for transcribed in self.handed]

    async def respond_transcribed(self, transcribed: TranscribedTurn, context: TurnContext) -> None:
        self.handed.append(transcribed)


def a_turn(config: VoiceTurnConfig, *, index: int = 0, speech_ms: int = 640) -> DetectedTurn:
    """One finalized turn carrying `speech_ms` of non-silent s16le audio."""
    return DetectedTurn(
        turn_id=uuid.uuid4(),
        turn_index=index,
        audio=b"\x10\x27" * ((config.sample_rate * speech_ms) // 1000),
        start_ms=1000 * (index + 1),
        end_ms=1000 * (index + 1) + speech_ms,
        is_barge_in=False,
        pre_roll_ms=config.pre_roll_ms,
        end_reason=TurnEndReason.ENDPOINT_SILENCE,
        discarded_short=False,
    )


async def a_stage(session_id: SessionId) -> RoleStageId | None:
    return STAGE_ID


async def no_stage(session_id: SessionId) -> RoleStageId | None:
    return None


@pytest.fixture
def session_id() -> SessionId:
    return SessionId(uuid.uuid4())


@pytest.fixture
def store() -> VoiceStore:
    return VoiceStore()


@pytest.fixture
def factory(store: VoiceStore, clock: FakeClock) -> Callable[[], InMemoryVoiceUnitOfWork]:
    return uow_factory(store, clock)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def metrics() -> NullMetricsRecorder:
    return NullMetricsRecorder()


def make_context(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
    *,
    audio_segment_ids: dict[uuid.UUID, uuid.UUID] | None = None,
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
        audio_segment_ids=audio_segment_ids or {},
    )


def make_responder(
    asr: FakeASR,
    metrics: NullMetricsRecorder,
    clock: FakeClock,
    config: VoiceTurnConfig,
    *,
    next_stage: TranscribedTurnResponder | None = None,
    timeout_ms: int = 4000,
    stage: Callable[[SessionId], object] = a_stage,
) -> AsrTurnResponder:
    return AsrTurnResponder(
        asr=asr,
        metrics=metrics,
        clock=clock,
        config=config,
        stage_resolver=stage,  # type: ignore[arg-type]
        timeout_ms=timeout_ms,
        next_stage=next_stage,
    )


# ---------------------------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------------------------


async def test_a_final_writes_transcript_turn_and_event_in_one_commit(
    config: VoiceTurnConfig,
    session_id: SessionId,
    store: VoiceStore,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    metrics: NullMetricsRecorder,
) -> None:
    """§9.1: the transcript row, the turn row and `ASR_FINAL` are one transaction."""
    audio_segment_id = uuid.uuid4()
    turn = a_turn(config)
    responder = make_responder(FakeASR([TEXT_RU]), metrics, clock, config)
    context = make_context(
        session_id, factory, clock, config, audio_segment_ids={turn.turn_id: audio_segment_id}
    )

    await responder.respond(turn, context)

    assert store.commits == 1
    assert [event.event_type for event in store.events] == [EventType.ASR_FINAL]
    assert len(store.transcripts) == 1
    assert len(store.turns) == 1

    segment = store.transcripts[0]
    assert segment.text == TEXT_RU
    assert segment.speaker == "TRAINEE"
    assert segment.is_final is True
    assert segment.confidence == 0.9
    assert segment.asr_provider == "fake"
    assert segment.asr_model == "fake-1"
    assert segment.turn_index == turn.turn_index
    assert segment.start_ms == turn.start_ms
    assert segment.end_ms == turn.end_ms
    # The recorder's segment for this very turn (§9.1) — not a new id, not `None`.
    assert segment.audio_segment_id == audio_segment_id

    event = store.events[0]
    assert event.payload["transcript_segment_id"] == str(segment.id)
    assert event.payload["audio_segment_id"] == str(audio_segment_id)
    assert event.payload["text"] == TEXT_RU
    assert event.payload["turn_id"] == str(turn.turn_id)
    assert event.payload["turn_index"] == turn.turn_index
    assert event.correlation_id == turn.turn_id

    row = store.turns[0]
    assert row.role_stage_id == STAGE_ID
    assert row.turn_index == turn.turn_index
    assert row.user_speech_started_offset_ms == turn.start_ms
    assert row.user_speech_ended_offset_ms == turn.end_ms
    assert row.operator_transcript_segment_id == segment.id
    assert row.correlation_id == turn.turn_id


async def test_the_turn_is_handed_to_the_next_stage(
    config: VoiceTurnConfig,
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    metrics: NullMetricsRecorder,
) -> None:
    """The chain continues after a non-empty final (E13's seam)."""
    next_stage = RecordingNextStage()
    responder = make_responder(FakeASR([TEXT_RU]), metrics, clock, config, next_stage=next_stage)
    turn = a_turn(config)

    await responder.respond(turn, make_context(session_id, factory, clock, config))

    assert [handed.turn_id for handed in next_stage.turns] == [turn.turn_id]


async def test_an_empty_final_is_logged_but_not_answered(
    config: VoiceTurnConfig,
    session_id: SessionId,
    store: VoiceStore,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    metrics: NullMetricsRecorder,
) -> None:
    """Whitespace-only speech still produces `ASR_FINAL` and a row — but no answer."""
    next_stage = RecordingNextStage()
    responder = make_responder(FakeASR(["   "]), metrics, clock, config, next_stage=next_stage)

    await responder.respond(a_turn(config), make_context(session_id, factory, clock, config))

    assert [event.event_type for event in store.events] == [EventType.ASR_FINAL]
    assert len(store.transcripts) == 1
    assert next_stage.turns == []


async def test_a_session_without_a_role_stage_still_gets_its_transcript(
    config: VoiceTurnConfig,
    session_id: SessionId,
    store: VoiceStore,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    metrics: NullMetricsRecorder,
) -> None:
    """`dialogue_turns.role_stage_id` is NOT NULL; the read model is skipped, the log is not."""
    responder = make_responder(FakeASR([TEXT_RU]), metrics, clock, config, stage=no_stage)

    await responder.respond(a_turn(config), make_context(session_id, factory, clock, config))

    assert len(store.transcripts) == 1
    assert store.turns == []
    assert [event.event_type for event in store.events] == [EventType.ASR_FINAL]


# ---------------------------------------------------------------------------------------------
# Telemetry (SPEC §27)
# ---------------------------------------------------------------------------------------------


async def test_every_call_is_measured(
    config: VoiceTurnConfig,
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    metrics: NullMetricsRecorder,
) -> None:
    """One `InferenceMetric` per call, with the audio duration and the realtime factor."""
    turn = a_turn(config, speech_ms=640)
    responder = make_responder(FakeASR([TEXT_RU]), metrics, clock, config)

    await responder.respond(turn, make_context(session_id, factory, clock, config))

    assert len(metrics.metrics) == 1
    metric = metrics.metrics[0]
    assert metric.stage is InferenceStage.ASR
    assert metric.status == "OK"
    assert metric.error_kind is None
    assert metric.provider == "fake"
    assert metric.model_version == "fake-1"
    assert metric.request_id == str(turn.turn_id)
    assert metric.turn_id == turn.turn_id
    assert metric.input_audio_ms == audio_duration_ms(turn.audio, config.sample_rate) == 640
    assert metric.total_latency_ms is not None
    assert metric.realtime_factor == pytest.approx(metric.total_latency_ms / 640)


async def test_a_metrics_failure_never_fails_the_turn(
    config: VoiceTurnConfig,
    session_id: SessionId,
    store: VoiceStore,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
) -> None:
    """§2.6: telemetry is not a second way for a turn to fail."""

    class BrokenMetrics(NullMetricsRecorder):
        async def record(self, metric: object) -> None:  # type: ignore[override]
            raise RuntimeError("the metrics table is on fire")

    responder = make_responder(FakeASR([TEXT_RU]), BrokenMetrics(), clock, config)

    await responder.respond(a_turn(config), make_context(session_id, factory, clock, config))

    assert [event.event_type for event in store.events] == [EventType.ASR_FINAL]
    assert len(store.transcripts) == 1


# ---------------------------------------------------------------------------------------------
# The failure path (SPEC §42 item 14)
# ---------------------------------------------------------------------------------------------


async def test_an_exception_becomes_model_error_and_stops_the_chain(
    config: VoiceTurnConfig,
    session_id: SessionId,
    store: VoiceStore,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    metrics: NullMetricsRecorder,
) -> None:
    """The turn ends quietly: `MODEL_ERROR`, an ERROR metric, no transcript, no next stage."""
    next_stage = RecordingNextStage()
    responder = make_responder(
        FakeASR([RuntimeError("cuda is sulking")]), metrics, clock, config, next_stage=next_stage
    )
    turn = a_turn(config)

    await responder.respond(turn, make_context(session_id, factory, clock, config))

    assert [event.event_type for event in store.events] == [EventType.MODEL_ERROR]
    payload = store.events[0].payload
    assert payload["component"] == "ASR"
    assert payload["provider"] == "fake"
    assert payload["model"] == "fake-1"
    assert payload["error_code"] == "RuntimeError"
    assert payload["message"] == "cuda is sulking"
    assert payload["recoverable"] is True
    assert payload["turn_index"] == turn.turn_index
    assert store.transcripts == []
    assert store.turns == []
    assert next_stage.turns == []
    assert metrics.metrics[0].status == "ERROR"
    assert metrics.metrics[0].error_kind == "RuntimeError"


async def test_a_timeout_becomes_model_error_with_the_timeout_code(
    config: VoiceTurnConfig,
    session_id: SessionId,
    store: VoiceStore,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    metrics: NullMetricsRecorder,
) -> None:
    """`SIM_ASR_TIMEOUT_MS`: a wedged provider ends the turn rather than the call."""

    class SlowASR(FakeASR):
        async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> object:  # type: ignore[override]
            await asyncio.sleep(10)
            raise AssertionError("unreachable")

    responder = make_responder(SlowASR([TEXT_RU]), metrics, clock, config, timeout_ms=10)

    await responder.respond(a_turn(config), make_context(session_id, factory, clock, config))

    assert [event.event_type for event in store.events] == [EventType.MODEL_ERROR]
    assert store.events[0].payload["error_code"] == "TIMEOUT"
    assert metrics.metrics[0].status == "TIMEOUT"
    assert store.transcripts == []


async def test_cancellation_records_a_cancelled_metric_and_propagates(
    config: VoiceTurnConfig,
    session_id: SessionId,
    store: VoiceStore,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    metrics: NullMetricsRecorder,
) -> None:
    """Barge-in: a cancelled response must actually stop (§6.1 step 2)."""

    class HangingASR(FakeASR):
        async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> object:  # type: ignore[override]
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    responder = make_responder(HangingASR([TEXT_RU]), metrics, clock, config)
    task = asyncio.create_task(
        responder.respond(a_turn(config), make_context(session_id, factory, clock, config))
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert metrics.metrics[0].status == "CANCELLED"
    assert metrics.metrics[0].error_kind == "BARGE_IN"
    assert store.events == []
    assert store.transcripts == []
