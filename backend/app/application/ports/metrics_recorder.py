"""`MetricsRecorder` port and `InferenceMetric` (HLD `50-voice-pipeline.md` §2.6, SPEC §27).

Every ASR / LLM / TTS call is timed through this port so that SPEC §27's "do not fake or hard-code
benchmark values" has one place to be true. E11 ships the port and the null recorder only; the
`inference_metrics` adapter belongs to E12, which is the epic that first produces a metric.

HLD §2.6 names the target file `ports/metrics.py`; this task's brief names
`ports/metrics_recorder.py` and the brief wins (see this task's report, "HLD gaps").
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "InferenceMetric",
    "InferenceStage",
    "MetricsRecorder",
    "NullMetricsRecorder",
]

MetricStatus = Literal["OK", "TIMEOUT", "ERROR", "CANCELLED"]


class InferenceStage(enum.StrEnum):
    """Which model call a metric row measures (§2.6)."""

    ASR = "ASR"
    LLM_INTERPRET = "LLM_INTERPRET"
    LLM_GENERATE = "LLM_GENERATE"
    TTS = "TTS"


@dataclass(frozen=True, slots=True)
class InferenceMetric:
    """Every SPEC §27 field. Persisted to `inference_metrics`; column names are the field names."""

    id: uuid.UUID
    session_id: uuid.UUID
    turn_id: uuid.UUID | None
    request_id: str
    stage: InferenceStage
    provider: str
    model_version: str
    input_tokens: int | None
    input_audio_ms: int | None
    output_tokens: int | None
    output_audio_ms: int | None
    started_at: datetime
    first_output_at: datetime | None
    finished_at: datetime | None
    ttft_ms: int | None
    total_latency_ms: int | None
    tokens_per_second: float | None
    realtime_factor: float | None
    gpu_memory_used_mb: int | None
    fallback_count: int
    retry_count: int
    status: MetricStatus
    error_kind: str | None


@runtime_checkable
class MetricsRecorder(Protocol):
    """Where a timed model call reports itself (§2.6)."""

    async def record(self, metric: InferenceMetric) -> None:
        """Persist one stage metric."""
        ...

    async def record_turn_latency(
        self, session_id: uuid.UUID, turn_id: uuid.UUID, speech_end_to_first_audio_ms: int
    ) -> None:
        """The SPEC §27 critical product metric, stored on the turn row, not on a stage row."""
        ...


class NullMetricsRecorder:
    """A `MetricsRecorder` that keeps what it was given in memory and writes nothing.

    E11 has no model call to time — ASR, the LLM and TTS arrive with E12–E14 — but the
    `TurnPipeline` already takes the port, so the seam is typed rather than absent. The recorded
    lists also make the pipeline's wiring assertable without a database.
    """

    def __init__(self) -> None:
        #: Every stage metric handed over, in call order.
        self.metrics: list[InferenceMetric] = []
        #: Every `(session_id, turn_id, speech_end_to_first_audio_ms)`, in call order.
        self.turn_latencies: list[tuple[uuid.UUID, uuid.UUID, int]] = []

    async def record(self, metric: InferenceMetric) -> None:
        """Remember the metric."""
        self.metrics.append(metric)

    async def record_turn_latency(
        self, session_id: uuid.UUID, turn_id: uuid.UUID, speech_end_to_first_audio_ms: int
    ) -> None:
        """Remember the turn latency."""
        self.turn_latencies.append((session_id, turn_id, speech_end_to_first_audio_ms))
