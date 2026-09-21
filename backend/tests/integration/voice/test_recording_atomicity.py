"""The `audio_segments` row and its event commit together, or neither does (§9.1, D5).

§9.1's ordering guarantee is not a convention a caller may forget: "the `audio_segments` row is
inserted in the same transaction as the `ASR_FINAL` / `CALLER_TTS_ENDED` event append, so
`transcript_segments.audio_segment_id` is never dangling and the report's
click-transcript-to-seek always resolves". These tests hold the whole path — recorder, appender,
real `SqlAlchemyUnitOfWork`, real PostgreSQL — to it in both directions.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
import sqlalchemy as sa
from app.application.testing.fakes import FakeClock, sine_burst_frames
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender, user_speech_ended_event
from app.application.voice.recorder import RecordingPaths, SessionRecorder
from app.application.voice.turn_detector import DetectedTurn, TurnEndReason
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.recording.wav_writer import InMemoryAudioSink
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

CALL_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")


def make_recorder(
    config: VoiceTurnConfig, clock: FakeClock, session_id: SessionId
) -> SessionRecorder:
    paths = RecordingPaths.for_call(session_id, CALL_ID)
    recorder = SessionRecorder(
        session_id=session_id,
        call_id=CALL_ID,
        config=config,
        clock=clock,
        trainee_sink=InMemoryAudioSink(paths.trainee),
        caller_sink=InMemoryAudioSink(paths.caller),
    )
    for frame in sine_burst_frames(
        duration_ms=1024, frame_samples=config.frame_samples, sample_rate=config.sample_rate
    ):
        recorder.tee("TRAINEE", frame)
    return recorder


def a_turn(config: VoiceTurnConfig) -> DetectedTurn:
    return DetectedTurn(
        turn_id=uuid.uuid4(),
        turn_index=0,
        audio=b"\x00\x00" * 1600,
        start_ms=0,
        end_ms=640,
        is_barge_in=False,
        pre_roll_ms=config.pre_roll_ms,
        end_reason=TurnEndReason.ENDPOINT_SILENCE,
        discarded_short=False,
    )


async def _counts(engine: AsyncEngine, session_id: SessionId) -> tuple[int, int]:
    async with engine.connect() as connection:
        segments = (
            await connection.execute(
                sa.text("SELECT count(*) FROM audio_segments WHERE session_id = :sid"),
                {"sid": str(session_id)},
            )
        ).scalar_one()
        events = (
            await connection.execute(
                sa.text(
                    "SELECT count(*) FROM session_events"
                    " WHERE session_id = :sid AND event_type = :etype"
                ),
                {"sid": str(session_id), "etype": EventType.USER_SPEECH_ENDED.value},
            )
        ).scalar_one()
    return int(segments), int(events)


async def test_the_row_and_the_event_are_committed_together(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
) -> None:
    """One transaction: the `audio_segments` row and `USER_SPEECH_ENDED` land together."""
    config = VoiceTurnConfig()
    recorder = make_recorder(config, clock, session_id)
    turn = a_turn(config)
    segment = recorder.segment_for("TRAINEE", start_ms=turn.start_ms, end_ms=turn.end_ms)
    appender = VoiceEventAppender(
        session_id=session_id, uow_factory=unit_of_work, clock=clock, started_at=clock.now()
    )

    appended = await appender.append(
        [
            user_speech_ended_event(
                turn,
                call_id=CALL_ID,
                offset_ms=640,
                endpoint_silence_ms=config.endpoint_silence_ms,
            )
        ],
        segments=[segment],
    )

    assert [event.event_type for event in appended] == [EventType.USER_SPEECH_ENDED]
    assert await _counts(migrated_engine, session_id) == (1, 1)

    async with migrated_engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    sa.text("SELECT * FROM audio_segments WHERE id = :id"), {"id": str(segment.id)}
                )
            )
            .mappings()
            .one()
        )
    assert row["speaker"] == "TRAINEE"
    assert row["sample_rate"] == config.sample_rate
    assert row["num_channels"] == 1
    assert row["format"] == "wav"
    assert row["purged_at"] is None
    # Session-relative offsets (D9), and a path relative to `data_dir` (SPEC §41).
    assert row["start_ms"] == turn.start_ms
    assert row["end_ms"] == turn.end_ms
    assert not row["file_path"].startswith("/")


async def test_killing_the_transaction_leaves_neither_the_row_nor_the_event(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
) -> None:
    """The other direction: no commit ⇒ no row *and* no event, never one of the two."""
    config = VoiceTurnConfig()
    recorder = make_recorder(config, clock, session_id)
    turn = a_turn(config)
    segment = recorder.segment_for("TRAINEE", start_ms=turn.start_ms, end_ms=turn.end_ms)
    event = user_speech_ended_event(
        turn, call_id=CALL_ID, offset_ms=640, endpoint_silence_ms=config.endpoint_silence_ms
    )

    with pytest.raises(RuntimeError, match="the recorder fell over"):
        async with unit_of_work() as uow:
            await uow.audio_segments.add_all([segment])
            await uow.events.append(session_id, [event])
            raise RuntimeError("the recorder fell over")

    assert await _counts(migrated_engine, session_id) == (0, 0)


async def test_the_segment_is_readable_back_through_the_repository(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
) -> None:
    """The Range endpoint of §9.1 reads this row; a round trip must preserve every column."""
    config = VoiceTurnConfig()
    recorder = make_recorder(config, clock, session_id)
    segment = recorder.segment_for("TRAINEE", start_ms=320, end_ms=960)

    async with unit_of_work() as uow:
        await uow.audio_segments.add_all([segment])
        await uow.commit()

    async with unit_of_work() as uow:
        loaded = await uow.audio_segments.get(segment.id)
        listed = await uow.audio_segments.list_for_session(session_id, speaker="TRAINEE")
        other = await uow.audio_segments.list_for_session(session_id, speaker="CALLER")

    assert loaded == segment
    assert listed == [segment]
    assert other == []


async def test_add_all_is_idempotent_by_primary_key(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
) -> None:
    """A retried transaction must not leave a second row for the same segment."""
    config = VoiceTurnConfig()
    recorder = make_recorder(config, clock, session_id)
    segment = recorder.segment_for("TRAINEE", start_ms=0, end_ms=640)

    for _ in range(2):
        async with unit_of_work() as uow:
            await uow.audio_segments.add_all([segment])
            await uow.commit()

    segments, _ = await _counts(migrated_engine, session_id)
    assert segments == 1
