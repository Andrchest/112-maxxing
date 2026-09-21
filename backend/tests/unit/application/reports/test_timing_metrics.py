"""The timing-metrics aggregator (SPEC §29 item 13, SPEC §27, E16 R6).

The rule the suite exists to hold: **a metric with no measurement is `null`, never `0`**. SPEC
§27 closes with "Do not fake or hard-code benchmark values", and a dashboard reading `0 ms` for a
session that never spoke would be reporting a latency nobody observed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.application.ports.dialogue_turn_repository import StoredDialogueTurn
from app.application.ports.inference_metric_repository import StoredInferenceMetric
from app.application.reports.timing_metrics import percentile, timing_metrics
from app.domain.common.ids import RoleStageId, SessionId
from app.domain.enums import ActorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

from tests.unit.domain.session._builders import det_uuid

SESSION = SessionId(det_uuid("session"))
STAGE = RoleStageId(det_uuid("stage"))
STARTED = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


def _turn(index: int, *, speech_end_ms: int | None, fallback: bool = False) -> StoredDialogueTurn:
    return StoredDialogueTurn(
        id=det_uuid(f"turn-{index}"),
        session_id=SESSION,
        role_stage_id=STAGE,
        turn_index=index,
        user_speech_started_offset_ms=index * 1000,
        speech_end_to_first_audio_ms=speech_end_ms,
        fallback_used=fallback,
    )


def _metric(
    name: str,
    *,
    component: str,
    ttft_ms: int | None = None,
    total_latency_ms: int | None = None,
    fallback_count: int = 0,
) -> StoredInferenceMetric:
    return StoredInferenceMetric(
        id=det_uuid(name),
        session_id=SESSION,
        request_id=name,
        component=component,  # type: ignore[arg-type]
        provider="fake",
        model="fake",
        started_at=STARTED,
        ttft_ms=ttft_ms,
        total_latency_ms=total_latency_ms,
        fallback_count=fallback_count,
    )


def _interrupted(seq_no: int, cutoff_ms: int) -> SessionEvent:
    return SessionEvent(
        id=det_uuid(f"event-{seq_no}"),
        session_id=SESSION,
        seq_no=seq_no,
        event_type=EventType.CALLER_UTTERANCE_INTERRUPTED,
        timestamp_utc=STARTED,
        monotonic_offset_ms=seq_no * 100,
        actor_type=ActorType.TRAINEE,
        payload={"cutoff_latency_ms": cutoff_ms},
    )


# -- the percentile itself ---------------------------------------------------------------------


def test_an_empty_sample_has_no_percentile() -> None:
    assert percentile([], 50) is None
    assert percentile([], 95) is None


@pytest.mark.parametrize(
    ("values", "p", "expected"),
    [
        ([7.0], 50, 7.0),
        ([7.0], 95, 7.0),
        ([1.0, 2.0], 50, 1.0),
        ([1.0, 2.0], 95, 2.0),
        ([10.0, 20.0, 30.0, 40.0], 50, 20.0),
        ([10.0, 20.0, 30.0, 40.0], 95, 40.0),
        ([5.0, 1.0, 3.0], 50, 3.0),
    ],
)
def test_nearest_rank(values: list[float], p: float, expected: float) -> None:
    """Nearest rank: `ceil(p/100 * n)`-th of the sorted sample, so the answer was measured."""
    assert percentile(values, p) == expected


# -- the aggregate ----------------------------------------------------------------------------


def test_a_session_with_nothing_measured_reports_null_not_zero() -> None:
    """SPEC §27's "do not fake" rule, in its sharpest form."""
    metrics = timing_metrics([], [], [])
    assert metrics.turn_count == 0
    assert metrics.fallback_count == 0
    assert metrics.speech_end_to_first_audio_ms_p50 is None
    assert metrics.speech_end_to_first_audio_ms_p95 is None
    assert metrics.asr_latency_ms_p50 is None
    assert metrics.llm_ttft_ms_p50 is None
    assert metrics.tts_first_audio_ms_p50 is None
    assert metrics.barge_in_cutoff_ms_p95 is None


def test_a_turn_without_the_product_metric_is_dropped_from_the_sample() -> None:
    """Two turns, one measured: the p50 is that one value, not half of it."""
    metrics = timing_metrics([_turn(0, speech_end_ms=None), _turn(1, speech_end_ms=900)], [], [])
    assert metrics.turn_count == 2
    assert metrics.speech_end_to_first_audio_ms_p50 == 900.0


def test_each_metric_reads_its_own_column_and_component() -> None:
    metrics = timing_metrics(
        [_turn(0, speech_end_ms=1000), _turn(1, speech_end_ms=2000)],
        [
            _metric("asr", component="ASR", total_latency_ms=300, ttft_ms=999),
            _metric("interp", component="LLM_INTERPRETER", ttft_ms=120),
            _metric("gen", component="LLM_GENERATOR", ttft_ms=180),
            _metric("tts", component="TTS", ttft_ms=60),
        ],
        [],
    )
    assert metrics.speech_end_to_first_audio_ms_p50 == 1000.0
    assert metrics.speech_end_to_first_audio_ms_p95 == 2000.0
    # ASR reads `total_latency_ms`, not the `ttft_ms` that happens to sit beside it.
    assert metrics.asr_latency_ms_p50 == 300.0
    # Both LLM components feed one TTFT sample.
    assert metrics.llm_ttft_ms_p50 == 120.0
    assert metrics.tts_first_audio_ms_p50 == 60.0


def test_the_barge_in_cutoff_comes_from_the_event_log() -> None:
    """It has no column: E14 records it in `CALLER_UTTERANCE_INTERRUPTED`, and the log is the
    record (D5) — so the aggregator reads events rather than inventing a column."""
    metrics = timing_metrics([], [], [_interrupted(1, 180), _interrupted(2, 240)])
    assert metrics.barge_in_cutoff_ms_p95 == 240.0


def test_fallbacks_are_counted_from_both_sources() -> None:
    metrics = timing_metrics(
        [_turn(0, speech_end_ms=100, fallback=True), _turn(1, speech_end_ms=100)],
        [_metric("tts", component="TTS", fallback_count=2)],
        [],
    )
    assert metrics.fallback_count == 3


def test_a_boolean_is_never_mistaken_for_a_measurement() -> None:
    """`bool` is an `int` in Python; a `True` leaking into a latency sample would become `1.0`."""
    metrics = timing_metrics([_turn(0, speech_end_ms=None, fallback=True)], [], [])
    assert metrics.speech_end_to_first_audio_ms_p50 is None
