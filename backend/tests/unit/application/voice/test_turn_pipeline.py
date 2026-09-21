"""`TurnPipeline` end to end over fakes (§3.7; SPEC §16, §18, §42 item 14; D13).

`FakeCallTransport` + `EnergyVAD` + `FakeClock` + an in-memory Unit of Work: a whole call runs in
milliseconds of real time, with no LiveKit, no model and no PostgreSQL, which is exactly what
ruling 1 of this task asks for.
"""

from __future__ import annotations

import asyncio
import uuid

from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.recorder import RecordingPaths, SessionRecorder
from app.application.voice.turn_detector import DetectedTurn, TurnDetector
from app.application.voice.turn_pipeline import (
    NullTurnResponder,
    TurnContext,
    TurnPipeline,
    TurnResponder,
)
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType
from app.domain.events.types import EventType
from app.infrastructure.recording.wav_writer import InMemoryAudioSink

from tests.unit.application.voice.conftest import (
    VoiceStore,
    concat,
    make_vad,
    quiet,
    speech,
    uow_factory,
)

CALL_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")


def build(
    config: VoiceTurnConfig,
    *,
    frames: list,
    responder: TurnResponder | None = None,
    record: bool = False,
) -> tuple[TurnPipeline, FakeCallTransport, VoiceStore, FakeClock]:
    clock = FakeClock()
    store = VoiceStore()
    session_id = SessionId(uuid.uuid4())
    transport = FakeCallTransport(
        clock=clock, inbound=frames, outbound_queue_ms=config.outbound_queue_ms
    )
    recorder = None
    if record:
        paths = RecordingPaths.for_call(session_id, CALL_ID)
        recorder = SessionRecorder(
            session_id=session_id,
            call_id=CALL_ID,
            config=config,
            clock=clock,
            trainee_sink=InMemoryAudioSink(paths.trainee),
            caller_sink=InMemoryAudioSink(paths.caller),
        )
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
        recorder=recorder,
        responder=responder,
    )
    return pipeline, transport, store, clock


async def test_one_turn_produces_the_documented_event_order_and_actor_types(
    config: VoiceTurnConfig,
) -> None:
    """§3.7's per-turn order for the events E11 owns, then `CALL_ENDED` on transport close."""
    frames = concat(quiet(config, 400, 0), speech(config, 900, 0), quiet(config, 900, 0))
    responder = NullTurnResponder()
    pipeline, transport, store, _ = build(config, frames=frames, responder=responder)

    await asyncio.wait_for(pipeline.run(), timeout=10)

    assert [event.event_type for event in store.events] == [
        EventType.USER_SPEECH_STARTED,
        EventType.USER_SPEECH_ENDED,
        EventType.CALL_ENDED,
    ]
    started, ended, call_ended = store.events
    assert started.actor_type is ActorType.TRAINEE
    assert ended.actor_type is ActorType.TRAINEE
    assert call_ended.actor_type is ActorType.SIMULATION
    assert started.payload["vad_provider"] == "energy"
    assert started.payload["turn_id"] == ended.payload["turn_id"]
    assert ended.payload["discarded_short"] is False
    assert [event.seq_no for event in store.events] == [1, 2, 3]
    assert len(responder.responded) == 1
    assert transport.connected is False or not transport.yielded[len(frames) :]


async def test_a_discarded_short_turn_is_logged_but_never_reaches_the_responder() -> None:
    """§4.4: below `min_turn_ms` there is no ASR and no response (SPEC §17)."""
    config = VoiceTurnConfig(min_turn_ms=2000)
    frames = concat(quiet(config, 400, 0), speech(config, 300, 0), quiet(config, 900, 0))
    responder = NullTurnResponder()
    pipeline, _, store, _ = build(config, frames=frames, responder=responder)

    await asyncio.wait_for(pipeline.run(), timeout=10)

    ended = next(e for e in store.events if e.event_type is EventType.USER_SPEECH_ENDED)
    assert ended.payload["discarded_short"] is True
    assert responder.responded == []
    assert store.segments == [], "a discarded turn writes no audio_segments row"


async def test_a_second_turn_cancels_the_in_flight_response(config: VoiceTurnConfig) -> None:
    """§3.7: the respond queue is depth 1; a newer turn wins."""

    class SlowResponder:
        def __init__(self) -> None:
            self.started: list[DetectedTurn] = []
            self.finished: list[DetectedTurn] = []
            self.cancelled: list[DetectedTurn] = []

        async def respond(self, turn: DetectedTurn, context: TurnContext) -> None:
            self.started.append(turn)
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.cancelled.append(turn)
                raise
            self.finished.append(turn)

    responder = SlowResponder()
    frames = concat(
        quiet(config, 400, 0),
        speech(config, 700, 0),
        quiet(config, 900, 0),
        speech(config, 700, 0),
        quiet(config, 900, 0),
    )
    pipeline, _, store, _ = build(config, frames=frames, responder=responder)

    await asyncio.wait_for(pipeline.run(), timeout=10)

    assert len(responder.started) == 2, "both turns must have reached the responder"
    assert responder.cancelled, "the first response must have been cancelled by the second turn"
    assert responder.finished == []
    assert [e.event_type for e in store.events].count(EventType.USER_SPEECH_STARTED) == 2


async def test_a_responder_exception_never_kills_the_ingest(config: VoiceTurnConfig) -> None:
    """SPEC §42 item 14: a model failure must not erase simulation data.

    The responder raises on the first turn; the second turn is still detected, still logged and
    still handed over, and the call still ends with `CALL_ENDED`.
    """

    class ExplodingResponder:
        def __init__(self) -> None:
            self.calls = 0

        async def respond(self, turn: DetectedTurn, context: TurnContext) -> None:
            self.calls += 1
            raise RuntimeError("the model fell over")

    responder = ExplodingResponder()
    frames = concat(
        quiet(config, 400, 0),
        speech(config, 700, 0),
        quiet(config, 900, 0),
        speech(config, 700, 0),
        quiet(config, 900, 0),
    )
    pipeline, _, store, _ = build(config, frames=frames, responder=responder)

    await asyncio.wait_for(pipeline.run(), timeout=10)

    assert responder.calls == 2
    assert len(pipeline.responder_failures) == 2
    assert all(isinstance(exc, RuntimeError) for exc in pipeline.responder_failures)
    types = [e.event_type for e in store.events]
    assert types.count(EventType.USER_SPEECH_STARTED) == 2
    assert types.count(EventType.USER_SPEECH_ENDED) == 2
    assert types[-1] is EventType.CALL_ENDED


async def test_the_trainee_recording_is_teed_and_indexed(config: VoiceTurnConfig) -> None:
    """§9.1: `_ingest` tees every resampled frame, and a finalized turn gets one row."""
    frames = concat(quiet(config, 400, 0), speech(config, 900, 0), quiet(config, 900, 0))
    pipeline, _, store, _ = build(config, frames=frames, record=True)

    await asyncio.wait_for(pipeline.run(), timeout=10)

    assert len(store.segments) == 1
    segment = store.segments[0]
    assert segment.speaker == "TRAINEE"
    assert segment.file_path is not None and segment.file_path.endswith(".wav")
    assert segment.byte_length > 0
    ended = next(e for e in store.events if e.event_type is EventType.USER_SPEECH_ENDED)
    assert ended.payload["audio_segment_id"] == str(segment.id)


async def test_an_open_turn_is_finalized_when_the_transport_closes(
    config: VoiceTurnConfig,
) -> None:
    """§4.4's last row, driven through the pipeline rather than the detector alone."""
    frames = concat(quiet(config, 400, 0), speech(config, 900, 0))
    pipeline, _, store, _ = build(config, frames=frames)

    await asyncio.wait_for(pipeline.run(), timeout=10)

    ended = next(e for e in store.events if e.event_type is EventType.USER_SPEECH_ENDED)
    assert ended.payload["end_reason"] == "TRANSPORT_CLOSED"
    assert store.events[-1].event_type is EventType.CALL_ENDED
