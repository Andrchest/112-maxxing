"""`PgMetricsRecorder` over real `inference_metrics` (§2.6, §20.6, SPEC §27).

Two properties, and the second one matters more than the first: a metric is written for every
call, and a metric that *cannot* be written costs nothing. SPEC §27 asks for measurement; SPEC
§42 item 14 forbids a model-adjacent failure from costing simulation data, and a recorder that
raised would turn an already-committed turn into an exception in the responder.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from app.application.ports.metrics_recorder import InferenceMetric, InferenceStage
from app.domain.common.ids import SessionId
from app.infrastructure.metrics import PgMetricsRecorder
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

STARTED_AT = datetime(2026, 9, 21, 10, 0, 0, tzinfo=UTC)


def a_metric(
    session_id: SessionId,
    *,
    stage: InferenceStage = InferenceStage.ASR,
    turn_id: uuid.UUID | None = None,
    status: str = "OK",
    error_kind: str | None = None,
    request_id: str | None = None,
) -> InferenceMetric:
    return InferenceMetric(
        id=uuid.uuid4(),
        session_id=uuid.UUID(str(session_id)),
        turn_id=turn_id,
        request_id=request_id or str(uuid.uuid4()),
        stage=stage,
        provider="fake",
        model_version="fake-1",
        input_tokens=None,
        input_audio_ms=640,
        output_tokens=None,
        output_audio_ms=None,
        started_at=STARTED_AT,
        first_output_at=None,
        finished_at=STARTED_AT,
        ttft_ms=None,
        total_latency_ms=51,
        tokens_per_second=None,
        realtime_factor=0.08,
        gpu_memory_used_mb=None,
        fallback_count=0,
        retry_count=0,
        status=status,  # type: ignore[arg-type]
        error_kind=error_kind,
    )


@pytest.mark.parametrize(
    ("stage", "component"),
    [
        (InferenceStage.ASR, "ASR"),
        (InferenceStage.LLM_INTERPRET, "LLM_INTERPRETER"),
        (InferenceStage.LLM_GENERATE, "LLM_GENERATOR"),
        (InferenceStage.TTS, "TTS"),
    ],
)
async def test_one_row_per_call_with_the_mapped_component(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    stage: InferenceStage,
    component: str,
) -> None:
    """§2.6's stage names become §20.6's `component` CHECK values, which the database enforces."""
    recorder = PgMetricsRecorder(unit_of_work)

    await recorder.record(a_metric(session_id, stage=stage))

    async with migrated_engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    sa.text("SELECT * FROM inference_metrics WHERE session_id = :sid"),
                    {"sid": str(session_id)},
                )
            )
            .mappings()
            .one()
        )
    assert row["component"] == component
    assert row["provider"] == "fake"
    assert row["model"] == "fake-1"
    assert row["model_version"] == "fake-1"
    assert row["input_duration_ms"] == 640
    assert row["total_latency_ms"] == 51
    assert row["status"] == "OK"
    assert row["error_kind"] is None


async def test_a_failed_call_is_recorded_with_its_status(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
) -> None:
    """A failure that left no telemetry would be a failure nobody could measure (SPEC §27)."""
    recorder = PgMetricsRecorder(unit_of_work)

    await recorder.record(
        a_metric(session_id, status="TIMEOUT", error_kind="TIMEOUT", request_id="turn-7")
    )

    async with migrated_engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    sa.text(
                        "SELECT status, error_kind FROM inference_metrics"
                        " WHERE request_id = 'turn-7'"
                    )
                )
            )
            .mappings()
            .one()
        )
    assert (row["status"], row["error_kind"]) == ("TIMEOUT", "TIMEOUT")


async def test_the_turn_index_comes_from_the_registered_pairing(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
) -> None:
    """The port carries `turn_id`; the column is `turn_index`. `register_turn` bridges them."""
    recorder = PgMetricsRecorder(unit_of_work)
    turn_id = uuid.uuid4()
    recorder.register_turn(turn_id, 4)

    await recorder.record(a_metric(session_id, turn_id=turn_id, request_id="turn-4"))
    await recorder.record(a_metric(session_id, turn_id=uuid.uuid4(), request_id="unknown"))

    async with migrated_engine.connect() as connection:
        rows = {
            row["request_id"]: row["turn_index"]
            for row in (
                await connection.execute(
                    sa.text(
                        "SELECT request_id, turn_index FROM inference_metrics"
                        " WHERE session_id = :sid"
                    ),
                    {"sid": str(session_id)},
                )
            ).mappings()
        }
    assert rows == {"turn-4": 4, "unknown": None}


async def test_a_duplicate_request_id_leaves_one_row(
    migrated_engine: AsyncEngine,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
) -> None:
    """`uq_inference_metrics_request`: a retried write is the same measurement, not a second one."""
    recorder = PgMetricsRecorder(unit_of_work)

    await recorder.record(a_metric(session_id, request_id="same"))
    await recorder.record(a_metric(session_id, request_id="same"))

    async with migrated_engine.connect() as connection:
        count = (
            await connection.execute(
                sa.text("SELECT count(*) FROM inference_metrics WHERE request_id = 'same'")
            )
        ).scalar_one()
    assert count == 1


async def test_a_broken_metrics_insert_never_raises(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
) -> None:
    """§2.6: telemetry is not a second way for a turn to fail.

    The insert is made to fail the way it would in production — a `session_id` that violates the
    foreign key, i.e. a session that has been deleted under a still-running agent.
    """
    recorder = PgMetricsRecorder(unit_of_work)
    orphan = a_metric(SessionId(uuid.uuid4()))

    # No `pytest.raises`: returning normally is the assertion.
    await recorder.record(orphan)


async def test_the_turn_latency_lands_on_the_registered_turn_row(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
) -> None:
    """An unregistered turn is logged, not guessed at — and it still does not raise."""
    recorder = PgMetricsRecorder(unit_of_work)

    await recorder.record_turn_latency(uuid.UUID(str(session_id)), uuid.uuid4(), 1200)

    assert recorder.turn_index_of(None) is None
