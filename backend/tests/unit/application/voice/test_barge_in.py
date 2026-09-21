"""Outbound barge-in end to end over fakes (§6.1-§6.4; SPEC §18; D9, D10).

`FakeCallTransport` + `EnergyVAD` + `FakeTTS` + `FakeClock` + the in-memory Unit of Work: a whole
call — the caller speaking, the trainee interrupting, the next turn being answered — runs in
milliseconds of real time on a simulated playout clock, which is what makes the §6.2 budget an
assertion instead of a hope.

The `TurnResponder` here is a small one that speaks a scripted utterance through the real
`TtsSpeechSink`: the interpreter, the gate and the generator are E13's and have their own tests,
and putting them in the loop would make a barge-in test fail for reasons that are not about
barge-in.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from app.application.dialogue.speech_sink import PlannedCallerUtterance
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.tts_speech_sink import TtsSpeechSink
from app.application.voice.turn_detector import DetectedTurn, TurnDetector
from app.application.voice.turn_pipeline import (
    BARGE_IN_BUDGET_CLEAR_OUTBOUND_MS,
    BARGE_IN_BUDGET_DETECTOR_HANDOFF_MS,
    BARGE_IN_BUDGET_NETWORK_JITTER_MS,
    TurnContext,
    TurnPipeline,
)
from app.domain.caller.emotion import EmotionLabel, EmotionState
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.inference.tts.fake_tts import FakeTTS

from tests.unit.application.voice.conftest import (
    VoiceStore,
    concat,
    make_vad,
    quiet,
    speech,
    uow_factory,
)

CALL_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")
#: 19 characters × 60 ms = 1 140 ms, rounded up to 1 160 ms of audio: long enough that a trainee
#: who starts speaking 400 ms in interrupts it well before the end.
CALLER_TEXT_RU = "Алло, я вас слушаю."
EMOTION = EmotionState(emotion=EmotionLabel.PANICKED, stress_level=0.6)


class SpeakingResponder:
    """A `TurnResponder` that hands one scripted utterance to the real sink, per turn."""

    def __init__(self, sink: TtsSpeechSink, *, fact_ids: tuple[str, ...]) -> None:
        self._sink = sink
        self._fact_ids = fact_ids
        #: Every turn answered, in arrival order.
        self.answered: list[DetectedTurn] = []
        #: Turns whose `speak()` was cancelled by a barge-in.
        self.cancelled: list[DetectedTurn] = []

    async def respond(self, turn: DetectedTurn, context: TurnContext) -> None:
        self.answered.append(turn)
        planned = PlannedCallerUtterance(
            turn_id=turn.turn_id,
            turn_index=turn.turn_index,
            text=CALLER_TEXT_RU,
            fact_ids=self._fact_ids,
            emotion=EMOTION,
            source="LLM",
        )
        try:
            await self._sink.speak(planned, context)
        except asyncio.CancelledError:
            self.cancelled.append(turn)
            raise


def build(
    config: VoiceTurnConfig,
    *,
    frames: list,
    fact_ids: tuple[str, ...] = ("incident.address", "incident.floor"),
    provider: FakeTTS | None = None,
) -> tuple[TurnPipeline, FakeCallTransport, VoiceStore, SpeakingResponder, FakeClock]:
    clock = FakeClock()
    store = VoiceStore()
    session_id = SessionId(uuid.uuid4())
    transport = FakeCallTransport(
        clock=clock, inbound=frames, outbound_queue_ms=config.outbound_queue_ms
    )
    factory = uow_factory(store, clock)
    sink = TtsSpeechSink(
        provider=provider or FakeTTS(),
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        uow_factory=factory,
    )
    responder = SpeakingResponder(sink, fact_ids=fact_ids)
    pipeline = TurnPipeline(
        session_id=session_id,
        call_id=CALL_ID,
        transport=transport,
        vad=make_vad(config),
        detector=TurnDetector(config),
        appender=VoiceEventAppender(
            session_id=session_id, uow_factory=factory, clock=clock, started_at=clock.now()
        ),
        clock=clock,
        config=config,
        responder=responder,
    )
    return pipeline, transport, store, responder, clock


def two_turns(config: VoiceTurnConfig) -> list:
    """Trainee speaks, falls silent (turn 1 finalizes), then interrupts the caller's answer."""
    return concat(
        quiet(config, 320, 0),
        speech(config, 640, 0),
        quiet(config, 640, 0),
        speech(config, 640, 0),
        quiet(config, 3200, 0),
    )


def types_of(store: VoiceStore) -> list[EventType]:
    return [event.event_type for event in store.events]


def payload_of(store: VoiceStore, event_type: EventType) -> dict:
    return next(event.payload for event in store.events if event.event_type is event_type)


async def test_a_barge_in_mid_utterance_stops_playback_and_records_what_was_heard(
    config: VoiceTurnConfig,
) -> None:
    """§6.1 steps 3-6: the queue is cleared, playback stops, and §6.3's payload is exact."""
    pipeline, transport, store, responder, _ = build(config, frames=two_turns(config))

    await asyncio.wait_for(pipeline.run(), timeout=10)

    kinds = types_of(store)
    assert EventType.CALLER_TTS_STARTED in kinds
    assert EventType.CALLER_UTTERANCE_INTERRUPTED in kinds
    # INV 12, structurally: the interrupted utterance has no natural end, so no facts. (The
    # *second* turn runs to completion and does have both — it is the one that was not cut off.)
    interrupted_turn = payload_of(store, EventType.CALLER_UTTERANCE_INTERRUPTED)["turn_id"]
    assert not [
        event
        for event in store.events
        if event.event_type in {EventType.CALLER_TTS_ENDED, EventType.FACTS_DELIVERED}
        and event.payload["turn_id"] == interrupted_turn
    ]

    payload = payload_of(store, EventType.CALLER_UTTERANCE_INTERRUPTED)
    assert payload["planned_text"] == CALLER_TEXT_RU
    assert payload["delivered_text"] == CALLER_TEXT_RU[: len(payload["delivered_text"])]
    assert payload["delivered_text"] != CALLER_TEXT_RU
    assert 0 <= payload["delivered_audio_ms"] <= payload["total_audio_ms_generated"]
    assert payload["alignment_is_exact"] is True
    assert payload["fact_ids_not_revealed"] == ["incident.address", "incident.floor"]
    assert payload["cutoff_latency_ms"] >= 0
    assert payload["interrupting_turn_id"] != payload["turn_id"]

    # §6.1 step 3 really happened, and the queue really is empty (SPEC §42 test 12).
    assert transport.clear_outbound_calls
    assert transport.queue.queued_duration_ms() == 0
    assert responder.cancelled, "the in-flight response must be cancelled, not awaited"


async def test_the_interrupted_utterance_persists_the_documented_rows(
    config: VoiceTurnConfig,
) -> None:
    """§6.4's table: one transcript row of what was *heard*, one truncated caller segment."""
    _pipeline, _transport, store, _responder, _clock = build(config, frames=two_turns(config))
    await asyncio.wait_for(_pipeline.run(), timeout=10)

    payload = payload_of(store, EventType.CALLER_UTTERANCE_INTERRUPTED)
    turn_index = payload["turn_index"]
    caller_rows = [
        row for row in store.transcripts if row.speaker == "CALLER" and row.turn_index == turn_index
    ]
    assert len(caller_rows) == 1
    assert caller_rows[0].text == payload["delivered_text"]
    assert caller_rows[0].asr_provider is None
    assert caller_rows[0].end_ms - caller_rows[0].start_ms == payload["delivered_audio_ms"]

    outcome = next(row for row in store.caller_outcomes if row.turn_index == turn_index)
    assert outcome.interrupted is True
    assert outcome.delivered_text == payload["delivered_text"]
    assert outcome.caller_transcript_segment_id == caller_rows[0].id


async def test_the_next_turn_is_answered_normally_after_a_barge_in(
    config: VoiceTurnConfig,
) -> None:
    """§6.1 step 7: nothing special happens downstream — the trainee's turn is just a turn."""
    pipeline, _transport, store, responder, _ = build(config, frames=two_turns(config))

    await asyncio.wait_for(pipeline.run(), timeout=10)

    assert len(responder.answered) == 2
    # The second turn ran to a natural end: it has both an ending and its facts.
    assert EventType.CALLER_TTS_ENDED in types_of(store)
    assert EventType.FACTS_DELIVERED in types_of(store)
    assert types_of(store).index(EventType.CALLER_UTTERANCE_INTERRUPTED) < types_of(store).index(
        EventType.CALLER_TTS_ENDED
    )


async def test_the_interrupted_facts_are_offerable_again_on_the_next_turn(
    config: VoiceTurnConfig,
) -> None:
    """D10 / INV 12: the log's only record of revelation is `FACTS_DELIVERED`.

    The gate's own `ALREADY_REVEALED` reading is `fold_revealed(events)` (E13-A), so "the facts
    stay unrevealed" is the same statement as "the interrupted turn appended no
    `FACTS_DELIVERED`" — asserted here over the real event log the pipeline wrote.
    """
    pipeline, _transport, store, _responder, _ = build(config, frames=two_turns(config))

    await asyncio.wait_for(pipeline.run(), timeout=10)

    interrupted_at = next(
        index
        for index, event in enumerate(store.events)
        if event.event_type is EventType.CALLER_UTTERANCE_INTERRUPTED
    )
    before = store.events[: interrupted_at + 1]
    assert not [event for event in before if event.event_type is EventType.FACTS_DELIVERED], (
        "the interrupted utterance revealed a fact"
    )


async def test_playback_is_stopped_inside_the_documented_budget(
    config: VoiceTurnConfig,
) -> None:
    """§6.2: onset → cutoff under 250 ms of simulated time, at the effective defaults.

    "Onset" is `USER_SPEECH_STARTED.at_offset_ms` of the interrupting turn — the first sample of
    trainee speech the detector accepted — and "cutoff" is `cutoff_latency_ms`, which the pipeline
    measures from `clear_outbound()` completing. Both come off the `FakeClock`, so the number is
    the pipeline's own and not an arithmetic restatement of the config.
    """
    _pipeline, _transport, store, _responder, _ = build(config, frames=two_turns(config))
    await asyncio.wait_for(_pipeline.run(), timeout=10)

    payload = payload_of(store, EventType.CALLER_UTTERANCE_INTERRUPTED)
    assert payload["cutoff_latency_ms"] < 250, (
        f"onset→cutoff was {payload['cutoff_latency_ms']} ms (SPEC §18, §6.2)"
    )


def test_the_documented_budget_arithmetic_is_under_250_ms_at_stock_defaults(
    config: VoiceTurnConfig,
) -> None:
    """§6.2's table, recomputed from the config itself — this task's close-out (item 3).

    Rows 1 and 2 are `VoiceTurnConfig` fields (row 2 already arrives rounded to a whole
    `vad_frame_ms`, per §4.1's `_round_sustain_windows_up`); row 5 is `tts_chunk_ms`; rows 3, 4 and
    6 are the fixed budget constants beside `_barge_in` (`turn_pipeline.py`) since they are not
    config fields. `test_playback_is_stopped_inside_the_documented_budget` above asserts the real,
    measured `cutoff_latency_ms`; this test asserts the *documented* arithmetic never drifts back
    to the "no margin" 250 ms total the old `tts_chunk_ms = 40` default produced.
    """
    total_ms = (
        config.vad_frame_ms
        + config.barge_in_min_speech_ms
        + BARGE_IN_BUDGET_DETECTOR_HANDOFF_MS
        + BARGE_IN_BUDGET_CLEAR_OUTBOUND_MS
        + config.tts_chunk_ms
        + BARGE_IN_BUDGET_NETWORK_JITTER_MS
    )
    assert total_ms < 250, f"§6.2 budget total is {total_ms} ms, not under SPEC §18's 250 ms"
    assert total_ms == 230, f"§6.2's documented total is 230 ms at stock defaults, got {total_ms}"


async def test_a_barge_in_before_any_audio_appends_no_interrupted_event(
    config: VoiceTurnConfig,
) -> None:
    """§6.1: nothing was spoken, so there is nothing to have interrupted (the brief's case).

    The responder is one that never produces audio — a generation still in flight when the
    trainee starts talking. The barge-in cancels it, and the log gains no
    `CALLER_UTTERANCE_INTERRUPTED`: an empty one would claim the trainee cut the caller off
    mid-word when the caller had not opened their mouth.
    """

    class SlowResponder:
        def __init__(self) -> None:
            self.cancelled = 0

        async def respond(self, turn: DetectedTurn, context: TurnContext) -> None:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise

    clock = FakeClock()
    store = VoiceStore()
    session_id = SessionId(uuid.uuid4())
    frames = two_turns(config)
    transport = FakeCallTransport(
        clock=clock, inbound=frames, outbound_queue_ms=config.outbound_queue_ms
    )
    responder = SlowResponder()
    pipeline = TurnPipeline(
        session_id=session_id,
        call_id=CALL_ID,
        transport=transport,
        vad=make_vad(config),
        detector=TurnDetector(config),
        appender=VoiceEventAppender(
            session_id=session_id,
            uow_factory=uow_factory(store, clock),
            clock=clock,
            started_at=clock.now(),
        ),
        clock=clock,
        config=config,
        responder=responder,
    )

    await asyncio.wait_for(pipeline.run(), timeout=10)

    assert EventType.CALLER_UTTERANCE_INTERRUPTED not in types_of(store)
    assert EventType.FACTS_DELIVERED not in types_of(store)


@pytest.mark.parametrize("fact_ids", [(), ("incident.address",)])
async def test_an_uninterrupted_turn_always_ends_before_it_reveals(
    config: VoiceTurnConfig, fact_ids: tuple[str, ...]
) -> None:
    """The ordering D10 rests on: `CALLER_TTS_ENDED` strictly before `FACTS_DELIVERED`."""
    frames = concat(quiet(config, 320, 0), speech(config, 640, 0), quiet(config, 3000, 0))
    pipeline, _transport, store, _responder, _ = build(config, frames=frames, fact_ids=fact_ids)

    await asyncio.wait_for(pipeline.run(), timeout=10)

    kinds = types_of(store)
    assert EventType.CALLER_TTS_ENDED in kinds
    if fact_ids:
        assert kinds.index(EventType.CALLER_TTS_ENDED) < kinds.index(EventType.FACTS_DELIVERED)
    else:
        assert EventType.FACTS_DELIVERED not in kinds
