"""`TimingMetricsView` — SPEC §29 item 13 and SPEC §27's critical product metric (E16 R6).

One aggregator, two callers: `getSessionReport.timing_metrics` and
`listInferenceMetrics.timing_metrics` are the same schema and must be the same number, so they
are the same function over the same stored rows rather than two sums that agree by luck.

**Only stored measurements.** SPEC §27 closes with "Do not fake or hard-code benchmark values",
so a metric with no rows to aggregate is `null`, never `0`: zero is a measurement, absence is
not, and a dashboard that reads `0 ms` for a session that never spoke would be reporting a
latency nobody observed. `turn_count` and `fallback_count` are genuine counts and are therefore
`0` when there is nothing to count — the schema types them `integer`, not `number | null`, for
exactly that reason.

**Percentile definition.** Nearest-rank on the sorted sample: `p` of `n` values is the
`ceil(p/100 · n)`-th, 1-indexed. It needs no interpolation, returns a value that was actually
measured, and is stable for the small samples one training session produces (a dozen turns, not a
million requests). p50 of one value is that value; p95 of two is the larger.

**Where each number comes from** (the stored columns, never a re-derivation):

| field | source |
|:--|:--|
| `turn_count` | `dialogue_turns` rows |
| `speech_end_to_first_audio_ms_p50/p95` | `dialogue_turns.speech_end_to_first_audio_ms` (D9) |
| `asr_latency_ms_p50` | `inference_metrics.total_latency_ms` where `component = 'ASR'` |
| `llm_ttft_ms_p50` | `inference_metrics.ttft_ms` of the two `LLM_*` components |
| `tts_first_audio_ms_p50` | `inference_metrics.ttft_ms` where `component = 'TTS'` |
| `barge_in_cutoff_ms_p95` | `CALLER_UTTERANCE_INTERRUPTED.cutoff_latency_ms` (E14) |
| `fallback_count` | `dialogue_turns.fallback_used` plus `inference_metrics.fallback_count` |

`barge_in_cutoff_ms` has no column of its own — E14 records the cut-off latency in the
`CALLER_UTTERANCE_INTERRUPTED` payload — so the aggregator takes the events it needs as a third
input rather than inventing a column. That keeps the event log the record (D5).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.application.ports.dialogue_turn_repository import StoredDialogueTurn
from app.application.ports.inference_metric_repository import StoredInferenceMetric
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

__all__ = ["TimingMetrics", "percentile", "timing_metrics"]

#: The payload key E14 writes the barge-in cut-off latency under (§10.13).
_CUTOFF_KEY = "cutoff_latency_ms"


@dataclass(frozen=True, slots=True)
class TimingMetrics:
    """`openapi.yaml`'s `TimingMetricsView` as application data."""

    turn_count: int
    speech_end_to_first_audio_ms_p50: float | None
    speech_end_to_first_audio_ms_p95: float | None
    asr_latency_ms_p50: float | None
    llm_ttft_ms_p50: float | None
    tts_first_audio_ms_p50: float | None
    barge_in_cutoff_ms_p95: float | None
    fallback_count: int


def percentile(values: Sequence[float], p: float) -> float | None:
    """Nearest-rank percentile, or `None` for an empty sample (SPEC §27: never fake a value)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100.0 * len(ordered)))
    return float(ordered[min(rank, len(ordered)) - 1])


def timing_metrics(
    turns: Sequence[StoredDialogueTurn],
    metrics: Sequence[StoredInferenceMetric],
    events: Sequence[SessionEvent] = (),
) -> TimingMetrics:
    """Aggregate the stored per-turn and per-inference numbers into the §29 item 13 block."""
    speech_end = _numbers(turn.speech_end_to_first_audio_ms for turn in turns)
    asr = _numbers(metric.total_latency_ms for metric in metrics if str(metric.component) == "ASR")
    llm_ttft = _numbers(
        metric.ttft_ms for metric in metrics if str(metric.component).startswith("LLM_")
    )
    tts_ttft = _numbers(metric.ttft_ms for metric in metrics if str(metric.component) == "TTS")
    cutoffs = _numbers(
        event.payload.get(_CUTOFF_KEY)
        for event in events
        if event.event_type is EventType.CALLER_UTTERANCE_INTERRUPTED
    )
    fallbacks = sum(1 for turn in turns if turn.fallback_used) + sum(
        metric.fallback_count for metric in metrics
    )
    return TimingMetrics(
        turn_count=len(turns),
        speech_end_to_first_audio_ms_p50=percentile(speech_end, 50),
        speech_end_to_first_audio_ms_p95=percentile(speech_end, 95),
        asr_latency_ms_p50=percentile(asr, 50),
        llm_ttft_ms_p50=percentile(llm_ttft, 50),
        tts_first_audio_ms_p50=percentile(tts_ttft, 50),
        barge_in_cutoff_ms_p95=percentile(cutoffs, 95),
        fallback_count=fallbacks,
    )


def _numbers(values: Iterable[object]) -> list[float]:
    """The measured values of a column, with the un-measured ones dropped (not defaulted to 0)."""
    sample: list[float] = []
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            sample.append(float(value))
    return sample
