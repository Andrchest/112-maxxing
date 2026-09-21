"""`InferenceMetricRepository` port — the `inference_metrics` table (HLD `20-db-schema.md` §20.6,
`50-voice-pipeline.md` §2.6, SPEC §27).

Telemetry, and *only* telemetry: §20.6 says "never read by scoring", so nothing in this project
may branch on a row of this table. That is why the port is separate from `MetricsRecorder` — the
recorder is the seam every stage calls and is free to swallow its own failures (SPEC §27 asks for
measurement, not for a second way to fail a turn), while this is the plain table writer the
PostgreSQL recorder uses inside its own short transaction.

`StoredInferenceMetric` mirrors the **columns**, not the port's `InferenceMetric`: the table keys
a turn by `turn_index` (an int, so the report timeline can join it) while the port carries
`turn_id` (a uuid, so a cross-process response can be correlated), and the table calls the model
`model` + `model_version` where the port has one `model_version`. The mapping between the two
lives in `app.infrastructure.metrics.pg_metrics_recorder`, which is its only consumer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import SessionId

__all__ = [
    "INFERENCE_COMPONENTS",
    "InferenceComponent",
    "InferenceMetricRepository",
    "MetricStatus",
    "StoredInferenceMetric",
]

InferenceComponent = Literal["ASR", "LLM_INTERPRETER", "LLM_GENERATOR", "TTS", "VAD"]
"""`inference_metrics.component`'s CHECK values (§20.6), literal as the HLD gives them."""

INFERENCE_COMPONENTS: tuple[InferenceComponent, ...] = (
    "ASR",
    "LLM_INTERPRETER",
    "LLM_GENERATOR",
    "TTS",
    "VAD",
)

MetricStatus = Literal["OK", "TIMEOUT", "ERROR", "CANCELLED"]
"""`inference_metrics.status`; `50-voice-pipeline.md` §2.6's four values."""


class StoredInferenceMetric(BaseModel):
    """One `inference_metrics` row (§20.6). Field names are the column names."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    session_id: SessionId | None
    """`NULL` for a warm-up metric, which belongs to no session (`60-inference-ops.md` §4.2)."""

    request_id: str
    """Unique; a retried write of the same call is the same row."""

    component: InferenceComponent
    provider: str
    model: str
    model_version: str | None = None
    turn_index: int | None = None
    input_tokens: int | None = None
    input_duration_ms: int | None = None
    output_tokens: int | None = None
    output_audio_ms: int | None = None
    started_at: datetime
    first_output_at: datetime | None = None
    finished_at: datetime | None = None
    ttft_ms: int | None = None
    total_latency_ms: int | None = None
    tokens_per_second: float | None = None
    realtime_factor: float | None = None
    gpu_memory_mb: int | None = None
    fallback_count: int = 0
    retry_count: int = 0
    status: MetricStatus = "OK"
    error_kind: str | None = None


@runtime_checkable
class InferenceMetricRepository(Protocol):
    """`inference_metrics`, bound to the caller's Unit of Work transaction."""

    async def add(self, metric: StoredInferenceMetric) -> None:
        """Insert one metric row; a `request_id` already present is left alone."""
        ...

    async def list_for_session(self, session_id: SessionId) -> list[StoredInferenceMetric]:
        """Every metric of one session in `started_at` order — for a report, never for scoring."""
        ...
