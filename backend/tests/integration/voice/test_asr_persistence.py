"""The `ASR_FINAL` write is one transaction, against real PostgreSQL (§9.1, §20.6, D5).

§9.1's ordering guarantee is what makes `ASR_FINAL.transcript_segment_id` and `.audio_segment_id`
references that always resolve: "the row is inserted in the same transaction as the `ASR_FINAL`
event append". These tests hold the whole path — recorder, responder, real `SqlAlchemyUnitOfWork`,
real PostgreSQL — to it in **both** directions, because a guarantee that only holds when nothing
fails is not a guarantee.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import sqlalchemy as sa
from app.application.ports.dialogue_turn_repository import DialogueTurnUpsert
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.application.testing.fakes import FakeCallTransport, FakeClock, sine_burst_frames
from app.application.voice.asr_responder import AsrTurnResponder, UnitOfWorkSessionStageResolver
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.recorder import RecordingPaths, SessionRecorder
from app.application.voice.turn_detector import DetectedTurn, TurnEndReason
from app.application.voice.turn_pipeline import TurnContext
from app.domain.common.ids import RoleStageId, SessionId
from app.inference.asr import FakeASR
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.recording.wav_writer import InMemoryAudioSink
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

CALL_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")
TEXT_RU = "Горит квартира, улица Ленина пять"


@pytest.fixture
async def role_stage_id(
    migrated_engine: AsyncEngine, seeded: dict[str, uuid.UUID], session_id: SessionId
) -> AsyncIterator[RoleStageId]:
    """One committed incident + `role_stages` row — `dialogue_turns.role_stage_id` is NOT NULL."""
    async with migrated_engine.begin() as connection:
        incident_id = (
            await connection.execute(
                text(
                    "INSERT INTO incidents (session_id, scenario_version_id)"
                    " VALUES (:sid, :svid) RETURNING id"
                ),
                {"sid": str(session_id), "svid": str(seeded["scenario_version"])},
            )
        ).scalar_one()
        stage_id = (
            await connection.execute(
                text(
                    "INSERT INTO role_stages (session_id, incident_id, role_type, order_index,"
                    " state) VALUES (:sid, :iid, 'OPERATOR_112', 0, 'CONNECTED') RETURNING id"
                ),
                {"sid": str(session_id), "iid": incident_id},
            )
        ).scalar_one()
    yield RoleStageId(uuid.UUID(str(stage_id)))


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
        duration_ms=2048, frame_samples=config.frame_samples, sample_rate=config.sample_rate
    ):
        recorder.tee("TRAINEE", frame)
    return recorder


def make_responder(
    asr: FakeASR,
    clock: FakeClock,
    config: VoiceTurnConfig,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> AsrTurnResponder:
    return AsrTurnResponder(
        asr=asr,
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        stage_resolver=UnitOfWorkSessionStageResolver(unit_of_work),
        timeout_ms=4000,
    )


def make_context(
    session_id: SessionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
    audio_segment_ids: dict[uuid.UUID, uuid.UUID],
) -> TurnContext:
    return TurnContext(
        session_id=session_id,
        call_id=CALL_ID,
        config=config,
        transport=FakeCallTransport(clock=clock),
        appender=VoiceEventAppender(
            session_id=session_id, uow_factory=unit_of_work, clock=clock, started_at=clock.now()
        ),
        recorder=None,
        audio_segment_ids=audio_segment_ids,
    )


async def _counts(engine: AsyncEngine, session_id: SessionId) -> dict[str, int]:
    async with engine.connect() as connection:
        result = {}
        for name, statement in (
            ("transcripts", "SELECT count(*) FROM transcript_segments WHERE session_id = :sid"),
            ("turns", "SELECT count(*) FROM dialogue_turns WHERE session_id = :sid"),
            (
                "finals",
                "SELECT count(*) FROM session_events"
                " WHERE session_id = :sid AND event_type = 'ASR_FINAL'",
            ),
            ("audio", "SELECT count(*) FROM audio_segments WHERE session_id = :sid"),
        ):
            result[name] = int(
                (
                    await connection.execute(sa.text(statement), {"sid": str(session_id)})
                ).scalar_one()
            )
    return result


async def test_the_transcript_turn_and_event_commit_together(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """One transaction, three writes, and every reference resolves."""
    config = VoiceTurnConfig()
    recorder = make_recorder(config, clock, session_id)
    turn = a_turn(config)
    segment = recorder.segment_for("TRAINEE", start_ms=turn.start_ms, end_ms=turn.end_ms)
    async with unit_of_work() as uow:
        await uow.audio_segments.add_all([segment])
        await uow.commit()

    responder = make_responder(FakeASR([TEXT_RU]), clock, config, unit_of_work)
    await responder.respond(
        turn,
        make_context(session_id, unit_of_work, clock, config, {turn.turn_id: segment.id}),
    )

    assert await _counts(migrated_engine, session_id) == {
        "transcripts": 1,
        "turns": 1,
        "finals": 1,
        "audio": 1,
    }

    async with migrated_engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    sa.text("SELECT * FROM transcript_segments WHERE session_id = :sid"),
                    {"sid": str(session_id)},
                )
            )
            .mappings()
            .one()
        )
        turn_row = (
            (
                await connection.execute(
                    sa.text("SELECT * FROM dialogue_turns WHERE session_id = :sid"),
                    {"sid": str(session_id)},
                )
            )
            .mappings()
            .one()
        )
        event = (
            (
                await connection.execute(
                    sa.text(
                        "SELECT payload FROM session_events"
                        " WHERE session_id = :sid AND event_type = 'ASR_FINAL'"
                    ),
                    {"sid": str(session_id)},
                )
            )
            .mappings()
            .one()
        )["payload"]

    assert row["text"] == TEXT_RU
    assert row["speaker"] == "TRAINEE"
    assert row["is_final"] is True
    assert row["asr_provider"] == "fake"
    assert row["asr_model"] == "fake-1"
    assert row["turn_index"] == turn.turn_index
    # The recorder's own segment for this turn, not a fresh id (§9.1).
    assert uuid.UUID(str(row["audio_segment_id"])) == segment.id

    assert event["transcript_segment_id"] == str(row["id"])
    assert event["audio_segment_id"] == str(segment.id)

    assert uuid.UUID(str(turn_row["role_stage_id"])) == uuid.UUID(str(role_stage_id))
    assert turn_row["turn_index"] == turn.turn_index
    assert uuid.UUID(str(turn_row["operator_transcript_segment_id"])) == uuid.UUID(str(row["id"]))
    assert uuid.UUID(str(turn_row["correlation_id"])) == turn.turn_id
    # The columns E13 and E14 own are still at their defaults (this is their seam).
    assert turn_row["interpretation"] == {}
    assert turn_row["gate_output"] == {}
    assert turn_row["interrupted"] is False
    assert turn_row["speech_end_to_first_audio_ms"] is None


async def test_a_failing_event_append_leaves_no_transcript_row(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """Direction one: the event append fails ⇒ no transcript row survives."""
    config = VoiceTurnConfig()
    turn = a_turn(config)
    segment = StoredTranscriptSegment(
        id=uuid.uuid4(),
        session_id=session_id,
        audio_segment_id=None,
        speaker="TRAINEE",
        start_ms=turn.start_ms,
        end_ms=turn.end_ms,
        text=TEXT_RU,
        turn_index=turn.turn_index,
    )

    with pytest.raises(RuntimeError, match="the event store fell over"):
        async with unit_of_work() as uow:
            await uow.transcript_segments.add(segment)
            raise RuntimeError("the event store fell over")

    assert (await _counts(migrated_engine, session_id))["transcripts"] == 0


async def test_a_failing_transcript_insert_leaves_no_asr_final(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """Direction two: the transcript insert fails ⇒ no `ASR_FINAL` survives.

    The insert is made to fail the way PostgreSQL would: a `transcript_segments` row pointing at
    an `audio_segments` id that does not exist violates the foreign key.
    """
    config = VoiceTurnConfig()
    turn = a_turn(config)
    appender = VoiceEventAppender(
        session_id=session_id, uow_factory=unit_of_work, clock=clock, started_at=clock.now()
    )
    dangling = StoredTranscriptSegment(
        id=uuid.uuid4(),
        session_id=session_id,
        audio_segment_id=uuid.uuid4(),  # no such audio_segments row
        speaker="TRAINEE",
        start_ms=turn.start_ms,
        end_ms=turn.end_ms,
        text=TEXT_RU,
        turn_index=turn.turn_index,
    )
    from app.application.voice.events import asr_final_event

    with pytest.raises(Exception, match=r"(?i)foreign key"):
        await appender.append(
            [
                asr_final_event(
                    call_id=CALL_ID,
                    turn_id=turn.turn_id,
                    turn_index=turn.turn_index,
                    offset_ms=turn.end_ms,
                    transcript_segment_id=dangling.id,
                    audio_segment_id=dangling.audio_segment_id,
                    text=TEXT_RU,
                    start_ms=turn.start_ms,
                    end_ms=turn.end_ms,
                    confidence=0.9,
                    asr_provider="fake",
                    asr_model="fake-1",
                )
            ],
            transcript_segments=[dangling],
        )

    counts = await _counts(migrated_engine, session_id)
    assert counts["transcripts"] == 0
    assert counts["finals"] == 0


async def test_the_turn_row_is_upserted_by_session_and_index(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """`(session_id, turn_index)` is the key; a second pass updates rather than duplicates."""
    first = DialogueTurnUpsert(
        id=uuid.uuid4(),
        session_id=session_id,
        role_stage_id=role_stage_id,
        turn_index=0,
        user_speech_started_offset_ms=1000,
    )
    async with unit_of_work() as uow:
        row_id = await uow.dialogue_turns.upsert(first)
        await uow.commit()

    second = DialogueTurnUpsert(
        id=uuid.uuid4(),
        session_id=session_id,
        role_stage_id=role_stage_id,
        turn_index=0,
        user_speech_started_offset_ms=1000,
        user_speech_ended_offset_ms=1500,
    )
    async with unit_of_work() as uow:
        again = await uow.dialogue_turns.upsert(second)
        await uow.commit()

    assert again == row_id, "the upsert created a second row instead of updating the first"

    async with unit_of_work() as uow:
        stored = await uow.dialogue_turns.get(session_id, 0)
        listed = await uow.dialogue_turns.list_for_session(session_id)

    assert stored is not None
    assert stored.user_speech_ended_offset_ms == 1500
    assert len(listed) == 1


async def test_the_latency_metric_lands_on_the_turn_row(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """SPEC §27's critical product metric is a column on `dialogue_turns`, not a stage row."""
    async with unit_of_work() as uow:
        await uow.dialogue_turns.upsert(
            DialogueTurnUpsert(
                id=uuid.uuid4(),
                session_id=session_id,
                role_stage_id=role_stage_id,
                turn_index=3,
                user_speech_started_offset_ms=2000,
            )
        )
        await uow.commit()

    async with unit_of_work() as uow:
        await uow.dialogue_turns.set_speech_end_to_first_audio_ms(session_id, 3, 1187)
        await uow.commit()

    async with unit_of_work() as uow:
        stored = await uow.dialogue_turns.get(session_id, 3)

    assert stored is not None
    assert stored.speech_end_to_first_audio_ms == 1187


async def test_the_transcript_repository_round_trips(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
) -> None:
    """The report reads this table; a round trip must preserve every column, in `start_ms` order."""
    late = StoredTranscriptSegment(
        id=uuid.uuid4(),
        session_id=session_id,
        speaker="TRAINEE",
        start_ms=2000,
        end_ms=2500,
        text="второй",
        confidence=0.9,
        asr_provider="fake",
        asr_model="fake-1",
        turn_index=1,
    )
    early = late.model_copy(
        update={
            "id": uuid.uuid4(),
            "start_ms": 100,
            "end_ms": 600,
            "text": "первый",
            "turn_index": 0,
        }
    )

    async with unit_of_work() as uow:
        await uow.transcript_segments.add(late)
        await uow.transcript_segments.add(early)
        # Idempotent by primary key: a retried transaction leaves one row.
        await uow.transcript_segments.add(early)
        await uow.commit()

    async with unit_of_work() as uow:
        listed = await uow.transcript_segments.list_for_session(session_id)

    # `confidence` is a `real` (float4), so it round-trips to the nearest single-precision value;
    # everything else must come back byte-identical.
    assert [segment.id for segment in listed] == [early.id, late.id]
    assert [segment.text for segment in listed] == ["первый", "второй"]
    assert [segment.confidence for segment in listed] == pytest.approx([0.9, 0.9], rel=1e-6)
    assert [segment.model_copy(update={"confidence": None}) for segment in listed] == [
        early.model_copy(update={"confidence": None}),
        late.model_copy(update={"confidence": None}),
    ]


async def test_the_events_are_visible_after_the_commit(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """Two turns in a row: two transcript rows, two turn rows, two `ASR_FINAL`s, in order."""
    config = VoiceTurnConfig()
    responder = make_responder(FakeASR(["первый", "второй"]), clock, config, unit_of_work)
    context_ids: dict[uuid.UUID, uuid.UUID] = {}
    for index in range(2):
        turn = a_turn(config, index=index)
        await responder.respond(
            turn, make_context(session_id, unit_of_work, clock, config, context_ids)
        )

    counts = await _counts(migrated_engine, session_id)
    assert counts["transcripts"] == 2
    assert counts["turns"] == 2
    assert counts["finals"] == 2

    async with unit_of_work() as uow:
        listed = await uow.transcript_segments.list_for_session(session_id)
    assert [segment.text for segment in listed] == ["первый", "второй"]
    assert [segment.audio_segment_id for segment in listed] == [None, None]
