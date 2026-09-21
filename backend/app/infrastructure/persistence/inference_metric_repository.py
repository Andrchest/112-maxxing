"""`SqlAlchemyInferenceMetricRepository` over `inference_metrics` (§20.6, SPEC §27).

`request_id` is unique, so `add` inserts `ON CONFLICT (request_id) DO NOTHING`: a stage that
retried its own write must leave one row, and losing the second copy of a measurement costs
nothing (§20.6: telemetry, never read by scoring).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.inference_metric_repository import StoredInferenceMetric
from app.db.models.events import InferenceMetric as InferenceMetricRow
from app.domain.common.ids import SessionId

__all__ = ["SqlAlchemyInferenceMetricRepository"]

_INFERENCE_METRICS = InferenceMetricRow.__table__


def _row_values(metric: StoredInferenceMetric) -> dict[str, Any]:
    return {
        "id": metric.id,
        "session_id": None if metric.session_id is None else UUID(str(metric.session_id)),
        "request_id": metric.request_id,
        "component": metric.component,
        "provider": metric.provider,
        "model": metric.model,
        "model_version": metric.model_version,
        "turn_index": metric.turn_index,
        "input_tokens": metric.input_tokens,
        "input_duration_ms": metric.input_duration_ms,
        "output_tokens": metric.output_tokens,
        "output_audio_ms": metric.output_audio_ms,
        "started_at": metric.started_at,
        "first_output_at": metric.first_output_at,
        "finished_at": metric.finished_at,
        "ttft_ms": metric.ttft_ms,
        "total_latency_ms": metric.total_latency_ms,
        "tokens_per_second": metric.tokens_per_second,
        "realtime_factor": metric.realtime_factor,
        "gpu_memory_mb": metric.gpu_memory_mb,
        "fallback_count": metric.fallback_count,
        "retry_count": metric.retry_count,
        "status": metric.status,
        "error_kind": metric.error_kind,
    }


def _from_row(row: Mapping[str, Any]) -> StoredInferenceMetric:
    session_id = row["session_id"]
    return StoredInferenceMetric(
        id=row["id"],
        session_id=None if session_id is None else SessionId(session_id),
        request_id=row["request_id"],
        component=row["component"],
        provider=row["provider"],
        model=row["model"],
        model_version=row["model_version"],
        turn_index=row["turn_index"],
        input_tokens=row["input_tokens"],
        input_duration_ms=row["input_duration_ms"],
        output_tokens=row["output_tokens"],
        output_audio_ms=row["output_audio_ms"],
        started_at=row["started_at"],
        first_output_at=row["first_output_at"],
        finished_at=row["finished_at"],
        ttft_ms=row["ttft_ms"],
        total_latency_ms=row["total_latency_ms"],
        tokens_per_second=row["tokens_per_second"],
        realtime_factor=row["realtime_factor"],
        gpu_memory_mb=row["gpu_memory_mb"],
        fallback_count=row["fallback_count"],
        retry_count=row["retry_count"],
        status=row["status"],
        error_kind=row["error_kind"],
    )


class SqlAlchemyInferenceMetricRepository:
    """`InferenceMetricRepository` over PostgreSQL, bound to one `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, metric: StoredInferenceMetric) -> None:
        """Insert the metric; a `request_id` already present is left alone."""
        statement = pg_insert(_INFERENCE_METRICS).on_conflict_do_nothing(
            index_elements=["request_id"]
        )
        await self._session.execute(statement, _row_values(metric))

    async def list_for_session(self, session_id: SessionId) -> list[StoredInferenceMetric]:
        """Every metric of one session in `started_at` order."""
        result = await self._session.execute(
            sa.select(_INFERENCE_METRICS)
            .where(_INFERENCE_METRICS.c.session_id == UUID(str(session_id)))
            .order_by(_INFERENCE_METRICS.c.started_at, _INFERENCE_METRICS.c.id)
        )
        return [_from_row(row._mapping) for row in result.all()]
