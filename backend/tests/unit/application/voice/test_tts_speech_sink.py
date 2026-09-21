"""`TtsSpeechSink` and `delivered_text_for` against fakes (§3.7, §6, §9.1; SPEC §18, §25, §27).

`FakeTTS`, `FakeCallTransport`, `FakeClock` and the in-memory Unit of Work of `conftest.py`: the
sink's job is ordering and bookkeeping — one playback, one set of events, one set of rows — and
none of that needs a model or a database to be pinned down.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from app.application.dialogue.speech_sink import PlannedCallerUtterance
from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.call_transport import AudioFrame, DeliveredAudio
from app.application.ports.metrics_recorder import InferenceStage, NullMetricsRecorder
from app.application.ports.tts import TtsChunk, TtsUnavailableError
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.tts_speech_sink import TtsSpeechSink, delivered_text_for
from app.application.voice.turn_pipeline import ActiveCallerUtterance, TurnContext
from app.domain.caller.emotion import EmotionLabel, EmotionState
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.inference.tts.fake_tts import FakeTTS

from tests.unit.application.voice.conftest import (
    InMemoryVoiceUnitOfWork,
    VoiceStore,
    uow_factory,
)

CALL_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
TEXT_RU = "Алло, я вас слушаю."
EMOTION = EmotionState(emotion=EmotionLabel.PANICKED, stress_level=0.6)


# ---------------------------------------------------------------------------------------------
# §6.3's pure function
# ---------------------------------------------------------------------------------------------


def chunk(*, audio_ms: int, end: int, exact: bool = True, index: int = 0) -> TtsChunk:
    return TtsChunk(
        frame=AudioFrame(
            pcm=b"\x00" * 2,
            sample_rate=16_000,
            num_channels=1,
            samples_per_channel=1,
            capture_offset_ms=0,
        ),
        text_offset_start=0,
        text_offset_end=end,
        alignment_is_exact=exact,
        chunk_index=index,
        audio_ms=audio_ms,
    )


PLANNED = "Улица Ленина пять квартира двенадцать"


@pytest.mark.parametrize(
    ("chunks", "delivered_ms", "total_ms", "expected", "expected_exact"),
    [
        # Nothing delivered: known exactly, and known to be nothing.
        ([], 0, 0, "", True),
        ([chunk(audio_ms=40, end=10)], 0, 40, "", True),
        # A negative figure can only come from clamping upstream; it still means "nothing".
        ([chunk(audio_ms=40, end=10)], -5, 40, "", True),
        # Exact alignment: the prefix is the last fully delivered chunk's `text_offset_end`.
        (
            [chunk(audio_ms=40, end=13, index=0), chunk(audio_ms=40, end=len(PLANNED), index=1)],
            40,
            80,
            "Улица Ленина",
            True,
        ),
        # Everything delivered: the whole text, exactly.
        (
            [chunk(audio_ms=40, end=13, index=0), chunk(audio_ms=40, end=len(PLANNED), index=1)],
            80,
            80,
            PLANNED,
            True,
        ),
        # More delivered than generated (clamped upstream): still the whole text.
        (
            [chunk(audio_ms=40, end=13, index=0), chunk(audio_ms=40, end=len(PLANNED), index=1)],
            999,
            80,
            PLANNED,
            True,
        ),
        # Word-proportional: half the audio, half the words, and the boundary is flagged.
        (
            [
                chunk(audio_ms=40, end=13, exact=False, index=0),
                chunk(audio_ms=40, end=len(PLANNED), exact=False, index=1),
            ],
            40,
            80,
            "Улица Ленина",
            False,
        ),
        # Word-proportional with a partial word: the trailing fragment is dropped.
        (
            [chunk(audio_ms=100, end=len(PLANNED), exact=False)],
            25,
            100,
            "Улица",
            False,
        ),
    ],
)
def test_delivered_text_for_table(
    chunks: list[TtsChunk],
    delivered_ms: int,
    total_ms: int,
    expected: str,
    expected_exact: bool,
) -> None:
    """§6.3 steps 1-4, both branches and every clamp."""
    text, exact = delivered_text_for(
        PLANNED, chunks, delivered_audio_ms=delivered_ms, total_audio_ms_generated=total_ms
    )

    assert (text, exact) == (expected, expected_exact)


def test_the_proportional_branch_never_divides_by_zero() -> None:
    """A provider that reported no generated audio still yields an answer, not a crash."""
    assert delivered_text_for(
        PLANNED,
        [chunk(audio_ms=0, end=5, exact=False)],
        delivered_audio_ms=10,
        total_audio_ms_generated=0,
    ) == ("", False)


# ---------------------------------------------------------------------------------------------
# The sink
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store() -> VoiceStore:
    return VoiceStore()


@pytest.fixture
def factory(store: VoiceStore, clock: FakeClock) -> Callable[[], InMemoryVoiceUnitOfWork]:
    return uow_factory(store, clock)


@pytest.fixture
def session_id() -> SessionId:
    return SessionId(uuid.uuid4())


def a_planned(*, fact_ids: tuple[str, ...] = ("incident.address",)) -> PlannedCallerUtterance:
    return PlannedCallerUtterance(
        turn_id=uuid.uuid4(),
        turn_index=0,
        text=TEXT_RU,
        fact_ids=fact_ids,
        emotion=EMOTION,
        source="LLM",
    )


def make_context(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
    *,
    transport: FakeCallTransport | None = None,
    registered: list[ActiveCallerUtterance | None] | None = None,
    speech_ended: dict[uuid.UUID, int] | None = None,
) -> TurnContext:
    return TurnContext(
        session_id=session_id,
        call_id=CALL_ID,
        config=config,
        transport=transport or FakeCallTransport(clock=clock),
        appender=VoiceEventAppender(
            session_id=session_id, uow_factory=factory, clock=clock, started_at=clock.now()
        ),
        recorder=None,
        speech_ended_offset_ms=speech_ended or {},
        set_active_utterance=(
            None if registered is None else registered.append  # type: ignore[arg-type]
        ),
    )


def make_sink(
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
    metrics: NullMetricsRecorder,
    *,
    provider: FakeTTS | None = None,
    fallback: FakeTTS | None = None,
) -> TtsSpeechSink:
    return TtsSpeechSink(
        provider=provider or FakeTTS(),
        fallback_provider=fallback,
        metrics=metrics,
        clock=clock,
        config=config,
        uow_factory=factory,
    )


def types_of(store: VoiceStore) -> list[EventType]:
    return [event.event_type for event in store.events]


async def test_the_happy_path_event_order_is_the_documented_one(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """SPEC §16/§18: …CALLER_TTS_STARTED, CALLER_TTS_ENDED, FACTS_DELIVERED, in that order."""
    metrics = NullMetricsRecorder()
    sink = make_sink(factory, clock, config, metrics)
    planned = a_planned()

    await sink.speak(planned, make_context(session_id, factory, clock, config))

    assert types_of(store) == [
        EventType.CALLER_TTS_STARTED,
        EventType.CALLER_TTS_ENDED,
        EventType.FACTS_DELIVERED,
    ]


async def test_caller_tts_started_carries_the_exact_text_and_the_provider(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """SPEC §25: "store the actual text sent to TTS"; §10.13 fixes the key names."""
    sink = make_sink(factory, clock, config, NullMetricsRecorder())
    planned = a_planned()

    await sink.speak(planned, make_context(session_id, factory, clock, config))

    payload = store.events[0].payload
    assert payload["text_sent_to_tts"] == TEXT_RU
    assert payload["text"] == TEXT_RU
    assert payload["tts_provider"] == payload["provider"] == "fake"
    assert payload["tts_model"] == payload["model_version"] == "fake-tts-1"
    assert payload["voice_id"] == "ru_female_1"
    assert payload["turn_id"] == str(planned.turn_id)
    assert payload["first_audio_offset_ms"] == payload["at_offset_ms"]


async def test_facts_delivered_names_every_planned_fact(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """D10: a fact is revealed by an uninterrupted playback, and by nothing else."""
    sink = make_sink(factory, clock, config, NullMetricsRecorder())
    planned = a_planned(fact_ids=("incident.address", "incident.floor"))

    await sink.speak(planned, make_context(session_id, factory, clock, config))

    payload = store.events[-1].payload
    assert payload["fact_ids"] == ["incident.address", "incident.floor"]
    assert payload["delivered_via"] == "TTS_COMPLETED"
    assert payload["turn_index"] == 0


async def test_an_utterance_that_reveals_nothing_appends_no_facts_delivered(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """`fact_ids` empty (a §7.8 fallback row, say) means there is nothing to reveal."""
    sink = make_sink(factory, clock, config, NullMetricsRecorder())

    await sink.speak(a_planned(fact_ids=()), make_context(session_id, factory, clock, config))

    assert EventType.FACTS_DELIVERED not in types_of(store)


async def test_the_caller_transcript_row_and_the_turn_row_are_written(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """§9.1: speaker CALLER, `asr_provider`/`asr_model` NULL, text = what was spoken."""
    sink = make_sink(factory, clock, config, NullMetricsRecorder())

    await sink.speak(a_planned(), make_context(session_id, factory, clock, config))

    assert len(store.transcripts) == 1
    row = store.transcripts[0]
    assert row.speaker == "CALLER"
    assert row.text == TEXT_RU
    assert row.asr_provider is None and row.asr_model is None
    assert row.is_final is True

    assert len(store.caller_outcomes) == 1
    outcome = store.caller_outcomes[0]
    assert outcome.delivered_text == TEXT_RU
    assert outcome.interrupted is False
    assert outcome.caller_transcript_segment_id == row.id


async def test_the_transcript_row_commits_with_the_ended_event(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """§9.1's ordering guarantee: one unit of work, so neither can exist without the other."""
    sink = make_sink(factory, clock, config, NullMetricsRecorder())
    store.fail_on_transcript_add = RuntimeError("the transcript insert failed")

    with pytest.raises(RuntimeError):
        await sink.speak(a_planned(), make_context(session_id, factory, clock, config))

    assert EventType.CALLER_TTS_ENDED not in types_of(store)
    assert store.transcripts == []


async def test_the_frames_are_teed_into_the_caller_recording(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """§9.1: the caller WAV is written from the frames that actually went to the transport."""

    class RecordingRecorder:
        def __init__(self) -> None:
            self.teed: list[tuple[str, AudioFrame]] = []

        def tee(self, speaker: str, frame: AudioFrame) -> None:
            self.teed.append((speaker, frame))

        def segment_for(
            self, speaker: str, *, start_ms: int, end_ms: int, segment_id: uuid.UUID | None = None
        ) -> StoredAudioSegment:
            written = sum(len(frame.pcm) for _, frame in self.teed)
            return StoredAudioSegment(
                id=segment_id or uuid.uuid4(),
                session_id=SessionId(uuid.uuid4()),
                speaker="CALLER",
                file_path="recordings/x/caller.wav",
                start_ms=start_ms,
                end_ms=end_ms,
                byte_offset=0,
                byte_length=written,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

    recorder = RecordingRecorder()
    transport = FakeCallTransport(clock=clock)
    context = make_context(session_id, factory, clock, config, transport=transport)
    context = TurnContext(
        session_id=context.session_id,
        call_id=context.call_id,
        config=context.config,
        transport=context.transport,
        appender=context.appender,
        recorder=recorder,  # type: ignore[arg-type]
    )
    sink = make_sink(factory, clock, config, NullMetricsRecorder())

    await sink.speak(a_planned(), context)

    assert recorder.teed, "the caller recording must receive the spoken frames"
    assert {speaker for speaker, _ in recorder.teed} == {"CALLER"}
    assert len(recorder.teed) == len(transport.played_frames)
    # Session-relative stamps, not the provider's utterance-relative zero (D9).
    offsets = [frame.capture_offset_ms for _, frame in recorder.teed]
    assert offsets == sorted(offsets)


async def test_the_utterance_is_registered_with_the_pipeline(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """The one hook: `_barge_in` must be able to reach the stream and the playback (§6.1)."""
    registered: list[ActiveCallerUtterance | None] = []
    sink = make_sink(factory, clock, config, NullMetricsRecorder())

    await sink.speak(
        a_planned(), make_context(session_id, factory, clock, config, registered=registered)
    )

    assert len(registered) == 1
    active = registered[0]
    assert active is not None
    assert isinstance(active, ActiveCallerUtterance)
    assert active.playback is not None


async def test_the_first_audio_latency_is_recorded(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """SPEC §27's critical product metric, through the port that already has it (§2.6)."""
    metrics = NullMetricsRecorder()
    sink = make_sink(factory, clock, config, metrics)
    planned = a_planned()

    await sink.speak(
        planned,
        make_context(
            session_id,
            factory,
            clock,
            config,
            speech_ended={planned.turn_id: 0},
        ),
    )

    assert len(metrics.turn_latencies) == 1
    recorded_session, recorded_turn, value = metrics.turn_latencies[0]
    assert recorded_turn == planned.turn_id
    assert recorded_session == uuid.UUID(str(session_id))
    assert value >= 0


async def test_one_ok_tts_metric_per_provider_call(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """SPEC §27: a metric per TTS call, with `ttft_ms` and `realtime_factor`."""
    metrics = NullMetricsRecorder()
    sink = make_sink(factory, clock, config, metrics)

    await sink.speak(a_planned(), make_context(session_id, factory, clock, config))

    assert len(metrics.metrics) == 1
    metric = metrics.metrics[0]
    assert metric.stage is InferenceStage.TTS
    assert metric.status == "OK"
    assert metric.provider == "fake"
    assert metric.output_audio_ms and metric.output_audio_ms > 0
    assert metric.ttft_ms is not None
    assert metric.realtime_factor is not None
    assert metric.fallback_count == 0


# ---------------------------------------------------------------------------------------------
# Failure and fallback (INV 14 for TTS)
# ---------------------------------------------------------------------------------------------


async def test_a_provider_failure_retries_the_whole_utterance_on_the_fallback(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """MODEL_ERROR → MODEL_FALLBACK_USED → the fallback speaks, and the facts are revealed."""
    metrics = NullMetricsRecorder()
    sink = make_sink(
        factory,
        clock,
        config,
        metrics,
        provider=FakeTTS(fail_on_chunk=0),
        fallback=FakeTTS(provider_name="piper", model_version="ru_RU-irina-medium"),
    )

    await sink.speak(a_planned(), make_context(session_id, factory, clock, config))

    assert types_of(store) == [
        EventType.MODEL_ERROR,
        EventType.MODEL_FALLBACK_USED,
        EventType.CALLER_TTS_STARTED,
        EventType.CALLER_TTS_ENDED,
        EventType.FACTS_DELIVERED,
    ]
    error = store.events[0].payload
    assert error["component"] == error["stage"] == "TTS"
    assert error["recoverable"] is True
    fallback = store.events[1].payload
    assert fallback["component"] == fallback["stage"] == "TTS"
    assert store.events[2].payload["tts_provider"] == "piper"
    assert [metric.status for metric in metrics.metrics] == ["ERROR", "OK"]
    assert metrics.metrics[-1].fallback_count == 1


async def test_the_planned_emotion_reaches_both_the_primary_and_the_fallback_provider(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """MANAGER RULING on E14-B's gap 1 (item 4): `TtsVoiceSpec.emotion` carries
    `PlannedCallerUtterance.emotion` to a provider without any mutable provider-side state —
    `FakeTTS.requests` records the last spec each provider was handed, primary and fallback alike.
    """
    primary = FakeTTS(fail_on_chunk=0)
    fallback = FakeTTS(provider_name="piper", model_version="ru_RU-irina-medium")
    sink = make_sink(
        factory, clock, config, NullMetricsRecorder(), provider=primary, fallback=fallback
    )

    await sink.speak(a_planned(), make_context(session_id, factory, clock, config))

    assert primary.requests[-1][1].emotion == EMOTION
    assert fallback.requests[-1][1].emotion == EMOTION


async def test_two_failures_end_the_turn_silent_but_complete(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """INV 14's last row: no ending, no facts, but the record of what was planned survives."""
    sink = make_sink(
        factory,
        clock,
        config,
        NullMetricsRecorder(),
        provider=FakeTTS(fail_on_chunk=0),
        fallback=FakeTTS(provider_name="piper", fail_on_chunk=0),
    )

    await sink.speak(a_planned(), make_context(session_id, factory, clock, config))

    assert types_of(store) == [
        EventType.MODEL_ERROR,
        EventType.MODEL_FALLBACK_USED,
        EventType.MODEL_ERROR,
    ]
    assert EventType.CALLER_TTS_ENDED not in types_of(store)
    assert EventType.FACTS_DELIVERED not in types_of(store)
    assert len(store.transcripts) == 1
    assert store.transcripts[0].text == TEXT_RU
    assert store.caller_outcomes[0].delivered_text == ""
    assert store.caller_outcomes[0].interrupted is False


async def test_without_a_fallback_one_failure_is_already_the_silent_path(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """`SIM_TTS_FALLBACK_PROVIDER=none` — the gate's selection."""
    sink = make_sink(
        factory, clock, config, NullMetricsRecorder(), provider=FakeTTS(fail_on_chunk=0)
    )

    await sink.speak(a_planned(), make_context(session_id, factory, clock, config))

    assert types_of(store) == [EventType.MODEL_ERROR]
    assert store.caller_outcomes[0].delivered_text == ""


async def test_a_warm_up_style_provider_error_is_classified_as_error(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """The `error_code` is the exception's own type name (E12's convention)."""
    sink = make_sink(
        factory, clock, config, NullMetricsRecorder(), provider=FakeTTS(fail_on_chunk=0)
    )

    await sink.speak(a_planned(), make_context(session_id, factory, clock, config))

    assert store.events[0].payload["error_code"] == TtsUnavailableError.__name__


# ---------------------------------------------------------------------------------------------
# Interruption (the pipeline's path, driven directly)
# ---------------------------------------------------------------------------------------------


async def test_an_interrupted_utterance_reveals_nothing_and_records_what_was_heard(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6.3/§6.4 and INV 12, with the barge-in driven through the registered utterance."""
    triggers: list[object] = []

    async def spy(*args: object, **kwargs: object) -> None:
        triggers.append(kwargs.get("trigger_kind"))

    monkeypatch.setattr("app.application.voice.tts_speech_sink.apply_dialogue_emotion_trigger", spy)
    registered: list[ActiveCallerUtterance | None] = []
    provider = FakeTTS()
    sink = make_sink(factory, clock, config, NullMetricsRecorder(), provider=provider)
    planned = a_planned(fact_ids=("incident.address", "incident.floor"))
    context = make_context(session_id, factory, clock, config, registered=registered)

    # Drive the frame stream by hand: one chunk out, then the barge-in.
    stream = sink._frames
    assert stream is not None
    import asyncio

    task = asyncio.create_task(sink.speak(planned, context))
    for _ in range(6):
        await asyncio.sleep(0)
    active = registered[0]
    assert active is not None
    active.mark_interrupted()
    await active.cancel_generation()
    delivered = DeliveredAudio(
        delivered_audio_ms=40,
        total_audio_ms_generated=provider.audio_ms_for(TEXT_RU, max_chunk_ms=config.tts_chunk_ms),
        frames_delivered=1,
        frames_discarded=0,
        cancelled=True,
    )
    interrupting = uuid.uuid4()
    await active.on_interrupted(
        interrupting_turn_id=interrupting, delivered=delivered, cutoff_latency_ms=180
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    kinds = types_of(store)
    assert EventType.CALLER_UTTERANCE_INTERRUPTED in kinds
    assert EventType.CALLER_TTS_ENDED not in kinds
    assert EventType.FACTS_DELIVERED not in kinds
    payload = next(
        event.payload
        for event in store.events
        if event.event_type is EventType.CALLER_UTTERANCE_INTERRUPTED
    )
    assert payload["planned_text"] == TEXT_RU
    assert payload["delivered_text"] == TEXT_RU[: payload["delivered_text"].__len__()]
    assert payload["delivered_audio_ms"] == 40
    assert payload["cutoff_latency_ms"] == 180
    assert payload["interrupting_turn_id"] == str(interrupting)
    assert payload["alignment_is_exact"] is True
    assert payload["fact_ids_not_revealed"] == ["incident.address", "incident.floor"]
    # §6.4: the transcript is what was heard; the turn row keeps both sides.
    assert store.transcripts[0].text == payload["delivered_text"]
    assert store.caller_outcomes[0].interrupted is True
    assert store.caller_outcomes[0].delivered_text == payload["delivered_text"]
    # §10.5: the interruption trigger fires, the fact trigger does not.
    assert triggers == ["INTERRUPTION_COUNT"]


async def test_the_fact_revealed_trigger_fires_once_per_delivered_fact(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§10.5 / R7: E13's helper, called by E14 — the `TODO(E14)` it was left for."""
    seen: list[tuple[str, object]] = []

    async def spy(*args: object, **kwargs: object) -> None:
        seen.append((str(kwargs.get("trigger_kind")), args[2]))

    monkeypatch.setattr("app.application.voice.tts_speech_sink.apply_dialogue_emotion_trigger", spy)
    sink = make_sink(factory, clock, config, NullMetricsRecorder())

    await sink.speak(
        a_planned(fact_ids=("incident.address", "incident.floor")),
        make_context(session_id, factory, clock, config),
    )

    assert [kind for kind, _ in seen] == ["FACT_REVEALED", "FACT_REVEALED"]
    assert [trigger.fact_id for _, trigger in seen] == [  # type: ignore[attr-defined]
        "incident.address",
        "incident.floor",
    ]
