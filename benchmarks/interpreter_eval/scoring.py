"""Pure scoring functions for the interpreter eval set (this task's brief, CHANGE item 6).

No LLM, no network, no `app.*` import — every function takes and returns plain, JSON-shaped
`dict`/`set` values (the same shape `InterpretedUtterance.model_dump(mode="json")` produces), so
this module is usable two ways with identical code:

* `run_eval.py` feeds it the real interpreter's output against a real llama-server.
* `backend/tests/unit/application/dialogue/test_eval_scoring.py` (a gate-side test, no server)
  feeds it `FakeLLM`-driven `DialogueInterpreter` output.

Kept dependency-free on purpose (stdlib only) so it never needs `uv sync` extras and can be loaded
by the gate-side test via a plain file-path import (see that test file for why).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["ScoredCall", "aggregate", "aggregate_by_uncertainty", "percentile", "score_call"]


@dataclass(frozen=True)
class ScoredCall:
    """One eval item's outcome, scored against its label."""

    item_id: str
    speech_act_expected: str
    speech_act_actual: str
    speech_act_correct: bool
    requested_expected: frozenset[str]
    requested_actual: frozenset[str]
    requested_precision: float
    requested_recall: float
    requested_exact_match: bool
    explicit_correct: int
    explicit_total: int
    assertions_exact_match: bool
    confirmations_exact_match: bool
    fallback_used: bool
    repair_retry_used: bool
    think_leak: bool
    latency_ms: float | None
    prompt_tokens: int | None
    completion_tokens: int | None


def _fact_ids(items: list[dict[str, Any]]) -> frozenset[str]:
    return frozenset(item["fact_id"] for item in items)


def score_call(
    *,
    item_id: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
    fallback_used: bool = False,
    repair_retry_used: bool = False,
    think_leak: bool = False,
    latency_ms: float | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> ScoredCall:
    """Score one `actual` interpretation (as `InterpretedUtterance.model_dump(mode="json")` would
    shape it, or a `fallback_used` stand-in with the same shape) against one eval item's
    `expected` block (the same shape, from `ru_operator_utterances.yaml`)."""
    expected_requested = _fact_ids(expected.get("requested_facts", []))
    actual_requested = _fact_ids(actual.get("requested_facts", []))
    true_positive = len(expected_requested & actual_requested)
    precision = (
        true_positive / len(actual_requested)
        if actual_requested
        else (1.0 if not expected_requested else 0.0)
    )
    recall = (
        true_positive / len(expected_requested)
        if expected_requested
        else (1.0 if not actual_requested else 0.0)
    )

    expected_explicit = {
        item["fact_id"]: item["explicit"] for item in expected.get("requested_facts", [])
    }
    actual_explicit = {
        item["fact_id"]: item["explicit"] for item in actual.get("requested_facts", [])
    }
    shared = expected_requested & actual_requested
    explicit_correct = sum(
        1 for fact_id in shared if expected_explicit.get(fact_id) == actual_explicit.get(fact_id)
    )

    expected_assertions = _fact_ids(expected.get("operator_assertions", []))
    actual_assertions = _fact_ids(actual.get("operator_assertions", []))
    expected_confirmations = frozenset(expected.get("confirmation_targets", []))
    actual_confirmations = frozenset(actual.get("confirmation_targets", []))

    return ScoredCall(
        item_id=item_id,
        speech_act_expected=expected["speech_act"],
        speech_act_actual=actual.get("speech_act", ""),
        speech_act_correct=expected["speech_act"] == actual.get("speech_act"),
        requested_expected=expected_requested,
        requested_actual=actual_requested,
        requested_precision=precision,
        requested_recall=recall,
        requested_exact_match=expected_requested == actual_requested,
        explicit_correct=explicit_correct,
        explicit_total=len(shared),
        assertions_exact_match=expected_assertions == actual_assertions,
        confirmations_exact_match=expected_confirmations == actual_confirmations,
        fallback_used=fallback_used,
        repair_retry_used=repair_retry_used,
        think_leak=think_leak,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile (`pct` in `[0, 1]`); `None` for an empty input."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def aggregate(scored: list[ScoredCall]) -> dict[str, Any]:
    """Per-model summary: every metric CHANGE item 6 asks `run_eval.py` to report."""
    n = len(scored)
    if n == 0:
        return {"n": 0}
    latencies = [s.latency_ms for s in scored if s.latency_ms is not None]
    completion_tokens = [
        float(s.completion_tokens) for s in scored if s.completion_tokens is not None
    ]
    explicit_total = sum(s.explicit_total for s in scored)
    return {
        "n": n,
        "speech_act_accuracy": sum(s.speech_act_correct for s in scored) / n,
        "requested_facts_precision_mean": sum(s.requested_precision for s in scored) / n,
        "requested_facts_recall_mean": sum(s.requested_recall for s in scored) / n,
        "requested_facts_exact_match_rate": sum(s.requested_exact_match for s in scored) / n,
        "explicit_flag_accuracy": (
            sum(s.explicit_correct for s in scored) / explicit_total if explicit_total else None
        ),
        "assertions_exact_match_rate": sum(s.assertions_exact_match for s in scored) / n,
        "confirmations_exact_match_rate": sum(s.confirmations_exact_match for s in scored) / n,
        "fallback_rate": sum(s.fallback_used for s in scored) / n,
        "repair_rate": sum(s.repair_retry_used for s in scored) / n,
        "think_leak_count": sum(s.think_leak for s in scored),
        "latency_ms_p50": percentile(latencies, 0.50),
        "latency_ms_p95": percentile(latencies, 0.95),
        "latency_ms_max": max(latencies) if latencies else None,
        "completion_tokens_p50": percentile(completion_tokens, 0.50),
        "completion_tokens_p99": percentile(completion_tokens, 0.99),
    }


def aggregate_by_uncertainty(
    scored: list[ScoredCall], uncertain_ids: frozenset[str]
) -> dict[str, dict[str, Any]]:
    """Every `aggregate()` metric, reported TWICE (E13-B4 item 1, MANAGER RULING).

    `"all"` over every scored item, `"excluding_uncertain"` over the same items minus
    `uncertain_ids` (the eval set's own `uncertain: true` labels — MANAGER RULING: those five
    labels stay as labelled and stay flagged; this function never changes a label, it only
    reports the aggregate twice). Pure: takes the already-scored calls and an id set, nothing else.
    """
    excluding = [call for call in scored if call.item_id not in uncertain_ids]
    return {"all": aggregate(scored), "excluding_uncertain": aggregate(excluding)}
