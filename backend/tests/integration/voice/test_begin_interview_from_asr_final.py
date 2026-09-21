"""The first `ASR_FINAL` moves the operator stage CONNECTED → INTERVIEW (§10.8, D5, D7, SPEC §7).

The point of the test is *who* moves it. `AsrTurnResponder` appends an event and stops; the
transition is fired by the simulation's own `ring` / `begin_interview` pass, whose guard
(`guard_first_finalized_turn`) reads the appended log through `build_guard_runtime`. That
indirection is not ceremony — it is what keeps "a fact was recorded" and "a state changed" two
different decisions, so that replaying the log reproduces the same stage (SPEC §28) and so that a
voice agent running in another process can never move a session by itself (D9).

The two halves are asserted separately: the responder alone changes no state, and the simulation
pass afterwards changes exactly the one it is supposed to.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.asr_responder import AsrTurnResponder, UnitOfWorkSessionStageResolver
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.turn_detector import DetectedTurn, TurnEndReason
from app.application.voice.turn_pipeline import TurnContext
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.inference.asr import FakeASR
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

CALL_ID = uuid.UUID("88888888-8888-4888-8888-888888888888")
TEXT_RU = "Здравствуйте, у нас пожар"

# The API fixtures, re-exported by name as `test_inv_04_asr_never_mutates_card.py` does: a
# conftest that is already loaded cannot be registered a second time through `pytest_plugins`.
from tests.api import conftest as _api_fixtures  # noqa: E402
from tests.api.operator import conftest as _operator_fixtures  # noqa: E402

api_settings = _api_fixtures.api_settings
client = _api_fixtures.client
demo_version_id = _api_fixtures.demo_version_id
hasher = _api_fixtures.hasher
inference = _api_fixtures.inference
publisher = _api_fixtures.publisher
redis_client = _api_fixtures.redis_client
tokens = _api_fixtures.tokens
unit_of_work = _api_fixtures.unit_of_work
users = _api_fixtures.users

clean_database = _api_fixtures.clean_database
connected = _operator_fixtures.connected
container = _operator_fixtures.container
flow = _operator_fixtures.flow
idempotency = _operator_fixtures.idempotency
ringing = _operator_fixtures.ringing
uow_factory = _operator_fixtures.uow_factory

OperatorFlow = _operator_fixtures.OperatorFlow


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def a_turn(config: VoiceTurnConfig) -> DetectedTurn:
    return DetectedTurn(
        turn_id=uuid.uuid4(),
        turn_index=0,
        audio=b"\x10\x27" * (config.sample_rate // 2),
        start_ms=1000,
        end_ms=1500,
        is_barge_in=False,
        pre_roll_ms=config.pre_roll_ms,
        end_reason=TurnEndReason.ENDPOINT_SILENCE,
        discarded_short=False,
    )


async def stage_states(engine: AsyncEngine, session_id: uuid.UUID) -> list[str]:
    async with engine.connect() as connection:
        result = await connection.execute(
            sa.text("SELECT state FROM role_stages WHERE session_id = :sid ORDER BY order_index"),
            {"sid": str(session_id)},
        )
    return [str(row[0]) for row in result.all()]


async def run_one_turn(flow: OperatorFlow, clock: FakeClock) -> DetectedTurn:
    """Transcribe one turn with the real responder, through the API container's Unit of Work."""
    config = VoiceTurnConfig()
    session_id = SessionId(flow.session_id)
    responder = AsrTurnResponder(
        asr=FakeASR([TEXT_RU]),
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        stage_resolver=UnitOfWorkSessionStageResolver(flow.container.unit_of_work),
        timeout_ms=4000,
    )
    turn = a_turn(config)
    await responder.respond(
        turn,
        TurnContext(
            session_id=session_id,
            call_id=CALL_ID,
            config=config,
            transport=FakeCallTransport(clock=clock),
            appender=VoiceEventAppender(
                session_id=session_id,
                uow_factory=flow.container.unit_of_work,
                clock=clock,
                started_at=clock.now(),
            ),
            recorder=None,
            audio_segment_ids={},
        ),
    )
    return turn


async def test_the_responder_alone_moves_no_stage(
    migrated_engine: AsyncEngine, connected: OperatorFlow, clock: FakeClock
) -> None:
    """Appending `ASR_FINAL` is not firing `begin_interview` (SPEC §2, D5)."""
    before = await stage_states(migrated_engine, connected.session_id)
    assert before[0] == "CONNECTED"

    await run_one_turn(connected, clock)

    assert EventType.ASR_FINAL.value in await connected.event_types()
    assert await stage_states(migrated_engine, connected.session_id) == before, (
        "the ASR responder moved a workflow state by itself"
    )


async def test_the_simulation_pass_then_begins_the_interview(
    migrated_engine: AsyncEngine, connected: OperatorFlow, clock: FakeClock
) -> None:
    """§10.8: the existing `after_tick` hook reads the log and fires the transition."""
    await run_one_turn(connected, clock)

    fired = await connected.advance_call_flow()

    assert fired is True
    assert (await stage_states(migrated_engine, connected.session_id))[0] == "INTERVIEW"
    types = await connected.event_types()
    assert types.index(EventType.ASR_FINAL.value) < len(types) - 1, (
        "the stage event did not follow the ASR_FINAL that unlocked it"
    )


async def test_without_an_asr_final_the_guard_refuses(
    migrated_engine: AsyncEngine, connected: OperatorFlow
) -> None:
    """The other half of the guard: no finalized turn, no interview."""
    assert await connected.advance_call_flow() is False
    assert (await stage_states(migrated_engine, connected.session_id))[0] == "CONNECTED"
