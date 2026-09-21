"""`PgMetricsRecorder` — `MetricsRecorder` over `inference_metrics` (§2.6, §20.6, SPEC §27).

Two rules shape this class, and both come from the same place — telemetry must never become a
second way for a turn to fail:

1. **Its own Unit of Work, and a short one.** `record` does not join the caller's transaction. A
   metric written into the turn's transaction would either roll back with a failed turn (losing
   the measurement of the very call that is most interesting) or, worse, abort the turn when the
   metric insert is the thing that fails.
2. **Every failure is logged and swallowed.** SPEC §27 asks for measurement; SPEC §42 item 14
   forbids a model-adjacent failure from costing simulation data. A `record` that raised would
   turn a successful, already-committed turn into an exception in the responder.

Two mappings the port and the table do not share:

* `InferenceStage` → `inference_metrics.component`. The port's stage names are the pipeline's
  (`LLM_INTERPRET`, `LLM_GENERATE`); the column's CHECK values are §20.6's (`LLM_INTERPRETER`,
  `LLM_GENERATOR`). `_COMPONENT_OF_STAGE` is the whole of the difference.
* `turn_id` (uuid, what the port carries) → `turn_index` (int, what the column is). E11-A flagged
  this duality as an HLD gap and resolved it by carrying both on every event; the metric row has
  only the int, so the recorder is told the pairing by whoever opened the turn — see
  `register_turn`.
"""

from __future__ import annotations

import logging
import uuid
from collections import OrderedDict

from app.application.ports.inference_metric_repository import (
    InferenceComponent,
    StoredInferenceMetric,
)
from app.application.ports.metrics_recorder import InferenceMetric, InferenceStage
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.ids import SessionId

__all__ = ["PgMetricsRecorder"]

logger = logging.getLogger(__name__)

#: §2.6's stage names to §20.6's `component` CHECK values.
_COMPONENT_OF_STAGE: dict[InferenceStage, InferenceComponent] = {
    InferenceStage.ASR: "ASR",
    InferenceStage.LLM_INTERPRET: "LLM_INTERPRETER",
    InferenceStage.LLM_GENERATE: "LLM_GENERATOR",
    InferenceStage.TTS: "TTS",
}

#: How many `turn_id → turn_index` pairings one process keeps. A call is a few hundred turns at
#: the very most, and the registry is per voice-agent process, so this is generous by an order of
#: magnitude and still bounded — a long-running agent cannot leak one entry per turn forever.
_TURN_REGISTRY_MAX = 4096


class PgMetricsRecorder:
    """`MetricsRecorder` that writes `inference_metrics` in a transaction of its own."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory
        self._turn_index: OrderedDict[uuid.UUID, int] = OrderedDict()

    def register_turn(self, turn_id: uuid.UUID, turn_index: int) -> None:
        """Pair a turn's uuid with its index, so a metric for it can be joined to the report.

        Called by whoever opens the turn (the ASR responder). Re-registering the same turn is a
        no-op beyond refreshing its position in the bounded registry.
        """
        self._turn_index[turn_id] = turn_index
        self._turn_index.move_to_end(turn_id)
        while len(self._turn_index) > _TURN_REGISTRY_MAX:
            self._turn_index.popitem(last=False)

    def turn_index_of(self, turn_id: uuid.UUID | None) -> int | None:
        """The registered index for `turn_id`, or `None` when the pairing is unknown."""
        if turn_id is None:
            return None
        return self._turn_index.get(turn_id)

    async def record(self, metric: InferenceMetric) -> None:
        """Persist one stage metric. A failure here is logged and never re-raised."""
        try:
            row = self.to_row(metric)
        except Exception:
            logger.exception("could not map inference metric %s; dropping it", metric.request_id)
            return
        try:
            async with self._uow_factory() as uow:
                await uow.inference_metrics.add(row)
                await uow.commit()
        except Exception:
            logger.exception(
                "recording the %s metric for request %s failed; the turn is unaffected",
                metric.stage,
                metric.request_id,
            )

    async def record_turn_latency(
        self, session_id: uuid.UUID, turn_id: uuid.UUID, speech_end_to_first_audio_ms: int
    ) -> None:
        """SPEC §27's critical product metric onto `dialogue_turns` (§2.6)."""
        turn_index = self.turn_index_of(turn_id)
        if turn_index is None:
            logger.warning(
                "no turn_index is registered for turn %s; the speech-end-to-first-audio metric "
                "has no row to land on",
                turn_id,
            )
            return
        try:
            async with self._uow_factory() as uow:
                await uow.dialogue_turns.set_speech_end_to_first_audio_ms(
                    SessionId(session_id), turn_index, speech_end_to_first_audio_ms
                )
                await uow.commit()
        except Exception:
            logger.exception(
                "recording the turn latency of turn %s failed; the turn is unaffected", turn_id
            )

    def to_row(self, metric: InferenceMetric) -> StoredInferenceMetric:
        """Map the port's `InferenceMetric` onto the `inference_metrics` columns (§20.6)."""
        component = _COMPONENT_OF_STAGE.get(metric.stage)
        if component is None:  # pragma: no cover - the mapping covers every enum member
            raise ValueError(f"no inference_metrics.component for stage {metric.stage!r}")
        return StoredInferenceMetric(
            id=metric.id,
            session_id=SessionId(metric.session_id),
            request_id=metric.request_id,
            component=component,
            provider=metric.provider,
            # §20.6 splits the port's one `model_version` into `model` + `model_version`; the
            # provider is the only thing that knows the weights' name, so both carry it and the
            # report renders `provider/model_version`.
            model=metric.model_version,
            model_version=metric.model_version,
            turn_index=self.turn_index_of(metric.turn_id),
            input_tokens=metric.input_tokens,
            input_duration_ms=metric.input_audio_ms,
            output_tokens=metric.output_tokens,
            output_audio_ms=metric.output_audio_ms,
            started_at=metric.started_at,
            first_output_at=metric.first_output_at,
            finished_at=metric.finished_at,
            ttft_ms=metric.ttft_ms,
            total_latency_ms=metric.total_latency_ms,
            tokens_per_second=metric.tokens_per_second,
            realtime_factor=metric.realtime_factor,
            gpu_memory_mb=metric.gpu_memory_used_mb,
            fallback_count=metric.fallback_count,
            retry_count=metric.retry_count,
            status=metric.status,
            error_kind=metric.error_kind,
        )
