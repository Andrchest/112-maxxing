"""INV 14 — "A model failure does not erase simulation data" (SPEC §42 item 14, §19, §27; D9).

The failure mode this guards against is the tempting one: an ASR call raises, and the handler
"cleans up" — rolls the turn back, drops the recording row, resets the stage, aborts the session.
`60-inference-ops.md` forbids every one of those in as many words: a failing model "never calls a
session use case, aborts a session, rolls back an incident or clears a card".

So the invariant is a **conservation** property, and it is asserted as one: a full snapshot of the
session is taken before the failing turn and compared with the snapshot after it. Everything must
be identical except for exactly one new `MODEL_ERROR` event — and the very next turn must
transcribe normally, because a failure that poisoned the pipeline would be the same bug wearing a
different hat.

It runs against real PostgreSQL through the real `SqlAlchemyUnitOfWork`: "nothing was rolled back"
is a statement about a database, and an in-memory double could only repeat what the responder
already believes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import sqlalchemy as sa
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeCallTransport, FakeClock, sine_burst_frames
from app.application.voice.asr_responder import AsrTurnResponder, UnitOfWorkSessionStageResolver
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender, user_speech_ended_event
from app.application.voice.recorder import RecordingPaths, SessionRecorder
from app.application.voice.turn_detector import DetectedTurn, TurnEndReason
from app.application.voice.turn_pipeline import TurnContext
from app.domain.common.ids import RoleStageId, SessionId
from app.domain.events.types import EventType
from app.inference.asr import FakeASR
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.recording.wav_writer import InMemoryAudioSink
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# The persistence fixtures, re-exported by assignment rather than by `import`, exactly as
# `test_inv_04_asr_never_mutates_card.py` does: a conftest that is already loaded cannot be
# registered a second time through `pytest_plugins`, and an `import` here would collide with the
# identically named test parameters below.
from tests.integration.persistence import conftest as _persistence_fixtures

clean_database = _persistence_fixtures.clean_database
clock = _persistence_fixtures.clock
publisher = _persistence_fixtures.publisher
seeded = _persistence_fixtures.seeded
session_factory = _persistence_fixtures.session_factory
session_id = _persistence_fixtures.session_id
unit_of_work = _persistence_fixtures.unit_of_work

pytestmark = pytest.mark.integration

CALL_ID = uuid.UUID("77777777-7777-4777-8777-777777777777")
TEXT_RU = "Второй ход: машина сбила человека"


@pytest.fixture
async def stage(
    migrated_engine: AsyncEngine, seeded: dict[str, uuid.UUID], session_id: SessionId
) -> AsyncIterator[RoleStageId]:
    """One committed incident + `role_stages` row in `CONNECTED`."""
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


def a_turn(config: VoiceTurnConfig, *, index: int) -> DetectedTurn:
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


async def snapshot(engine: AsyncEngine, session_id: SessionId) -> dict[str, object]:
    """Everything the invariant says a model failure may not touch."""
    async with engine.connect() as connection:

        async def rows(statement: str) -> list[tuple[object, ...]]:
            result = await connection.execute(sa.text(statement), {"sid": str(session_id)})
            return [tuple(row) for row in result.all()]

        return {
            "session": await rows(
                "SELECT state, abort_reason, completed_at FROM simulation_sessions WHERE id = :sid"
            ),
            "stages": await rows(
                "SELECT role_type, state, started_at_offset_ms, completed_at_offset_ms"
                " FROM role_stages WHERE session_id = :sid ORDER BY order_index"
            ),
            "events": await rows(
                "SELECT seq_no, event_type FROM session_events WHERE session_id = :sid"
                " ORDER BY seq_no"
            ),
            "audio": await rows(
                "SELECT id, file_path, start_ms, end_ms, byte_offset, byte_length, purged_at"
                " FROM audio_segments WHERE session_id = :sid ORDER BY start_ms"
            ),
            "transcripts": await rows(
                "SELECT id, text, turn_index FROM transcript_segments WHERE session_id = :sid"
                " ORDER BY start_ms"
            ),
            "cards": await rows(
                "SELECT c.values, c.revision_counter FROM incident_cards c"
                " JOIN incidents i ON i.id = c.incident_id WHERE i.session_id = :sid"
            ),
            "card_revisions": await rows(
                "SELECT count(*) FROM incident_card_revisions r"
                " JOIN incident_cards c ON c.id = r.card_id"
                " JOIN incidents i ON i.id = c.incident_id WHERE i.session_id = :sid"
            ),
            "turns": await rows(
                "SELECT turn_index, operator_transcript_segment_id FROM dialogue_turns"
                " WHERE session_id = :sid ORDER BY turn_index"
            ),
        }


def build_responder(
    asr: FakeASR,
    clock: FakeClock,
    config: VoiceTurnConfig,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    metrics: NullMetricsRecorder,
) -> AsrTurnResponder:
    return AsrTurnResponder(
        asr=asr,
        metrics=metrics,
        clock=clock,
        config=config,
        stage_resolver=UnitOfWorkSessionStageResolver(unit_of_work),
        timeout_ms=4000,
    )


def build_context(
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


async def test_an_asr_failure_leaves_every_other_fact_untouched(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
    stage: RoleStageId,
) -> None:
    """SPEC §42 item 14: `MODEL_ERROR` is appended and *nothing else changes*."""
    config = VoiceTurnConfig()
    metrics = NullMetricsRecorder()
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

    failing = a_turn(config, index=0)
    segment = recorder.segment_for("TRAINEE", start_ms=failing.start_ms, end_ms=failing.end_ms)
    appender = VoiceEventAppender(
        session_id=session_id, uow_factory=unit_of_work, clock=clock, started_at=clock.now()
    )
    # The recording of the failing turn is committed *before* the model is called, exactly as the
    # pipeline does it (§9.1): that row is what the invariant says must survive the failure.
    await appender.append(
        [
            user_speech_ended_event(
                failing,
                call_id=CALL_ID,
                offset_ms=failing.end_ms,
                endpoint_silence_ms=config.endpoint_silence_ms,
            )
        ],
        segments=[segment],
    )

    before = await snapshot(migrated_engine, session_id)

    asr = FakeASR([RuntimeError("CUDA error: out of memory"), TEXT_RU])
    responder = build_responder(asr, clock, config, unit_of_work, metrics)
    audio_segment_ids = {failing.turn_id: segment.id}
    await responder.respond(
        failing, build_context(session_id, unit_of_work, clock, config, audio_segment_ids)
    )

    after = await snapshot(migrated_engine, session_id)

    # Exactly one new event, and it is the `MODEL_ERROR`.
    new_events = after["events"][len(before["events"]) :]  # type: ignore[index]
    assert [kind for _, kind in new_events] == [EventType.MODEL_ERROR.value]
    # …and every earlier event is byte-identical, in the same order, with the same `seq_no`.
    assert after["events"][: len(before["events"])] == before["events"]  # type: ignore[index]

    for key in ("session", "stages", "audio", "transcripts", "cards", "card_revisions", "turns"):
        assert after[key] == before[key], f"the ASR failure changed {key}"

    # The metric records the failure rather than hiding it (SPEC §27).
    assert [metric.status for metric in metrics.metrics] == ["ERROR"]
    assert metrics.metrics[0].error_kind == "RuntimeError"

    # The next turn is transcribed normally: the failure poisoned nothing.
    healthy = a_turn(config, index=1)
    await responder.respond(
        healthy, build_context(session_id, unit_of_work, clock, config, audio_segment_ids)
    )

    recovered = await snapshot(migrated_engine, session_id)
    assert [text for _, text, _ in recovered["transcripts"]] == [TEXT_RU]  # type: ignore[index]
    assert [kind for _, kind in recovered["events"]][-1] == EventType.ASR_FINAL.value
    assert len(recovered["turns"]) == 1  # type: ignore[arg-type]


async def test_the_model_error_payload_is_the_catalogued_one(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
    stage: RoleStageId,
) -> None:
    """§10.13's `MODEL_ERROR` row, so an instructor can see which component failed and why."""
    config = VoiceTurnConfig()
    responder = build_responder(
        FakeASR([ValueError("the weights are missing")]),
        clock,
        config,
        unit_of_work,
        NullMetricsRecorder(),
    )
    turn = a_turn(config, index=0)

    await responder.respond(turn, build_context(session_id, unit_of_work, clock, config, {}))

    async with migrated_engine.connect() as connection:
        payload = (
            (
                await connection.execute(
                    sa.text(
                        "SELECT payload, actor_type FROM session_events"
                        " WHERE session_id = :sid AND event_type = 'MODEL_ERROR'"
                    ),
                    {"sid": str(session_id)},
                )
            )
            .mappings()
            .one()
        )

    assert payload["actor_type"] == "SYSTEM"
    assert payload["payload"]["component"] == "ASR"
    assert payload["payload"]["provider"] == "fake"
    assert payload["payload"]["model"] == "fake-1"
    assert payload["payload"]["error_code"] == "ValueError"
    assert payload["payload"]["message"] == "the weights are missing"
    assert payload["payload"]["recoverable"] is True
    assert payload["payload"]["turn_index"] == turn.turn_index


async def test_the_responder_swallows_the_failure_rather_than_raising(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    session_id: SessionId,
    stage: RoleStageId,
) -> None:
    """A raising responder would take the `_respond` task with it; it must not raise.

    This is the assertion that makes the invariant's proof-of-bite meaningful: flipping the
    responder's `except Exception` branch to `raise` turns this test red, and turns the
    conservation test above red too (the `MODEL_ERROR` is never appended).
    """
    config = VoiceTurnConfig()
    responder = build_responder(
        FakeASR([RuntimeError("boom")]), clock, config, unit_of_work, NullMetricsRecorder()
    )

    # No `pytest.raises`: returning normally is the whole assertion.
    await responder.respond(
        a_turn(config, index=0), build_context(session_id, unit_of_work, clock, config, {})
    )
