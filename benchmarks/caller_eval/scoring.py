"""Pure scoring/aggregation functions for the caller-generator eval (E13-B4, CHANGE item 2).

No LLM, no network, no `app.*` import — stdlib only, exactly like `benchmarks/interpreter_eval/
scoring.py` (which this module mirrors in shape). `run_eval.py` feeds it what it measured from the
REAL chain (real gate, real `CallerPromptBuilder`, real `CallerResponseGenerator`, real
`ResponseValidator`, real `FallbackTemplates`) against a real `LlamaCppClient`; the gate-side test
(`backend/tests/unit/application/dialogue/test_caller_eval_scoring.py`) feeds it hand-built rows
with no server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["CaseOutcome", "aggregate", "percentile"]


@dataclass(frozen=True)
class CaseOutcome:
    """One eval case's measured outcome against one model (E13-B4 item 2's per-case record)."""

    case_id: str
    category: str
    attempt1_ok: bool
    attempt1_codes: tuple[str, ...]
    attempt2_ok: bool | None
    """`None` when there was no second attempt (attempt 1 already validated, or the model itself
    never answered)."""
    fallback_row: int | None
    """The §7.8 row number that answered, or `None` when a validated model answer was used."""
    final_text: str
    latency_ms: float | None
    """Attempt-1 total latency, milliseconds (§2.6's non-streaming call; no TTFT — see the module
    docstring of `run_eval.py`)."""
    prompt_tokens: int | None
    completion_tokens: int | None
    final_text_has_forbidden_value: bool
    """Must be `False` for every case — the deterministic boundary (§43's
    `forbidden_fact_leak_rate`, target 0). `run_eval.py` computes this the same way
    `forbidden_values.py` + the validator do."""
    raw_attempt1_has_forbidden_value: bool
    """The MODEL's own leak rate before validation — may be `True`; the validator exists for it."""


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


def aggregate(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    """Per-model summary: every metric CHANGE item 2 asks `run_eval.py` to report."""
    n = len(outcomes)
    if n == 0:
        return {"n": 0}

    validated_first_try = sum(1 for o in outcomes if o.attempt1_ok)
    regenerated = sum(1 for o in outcomes if o.attempt2_ok is not None)
    used_fallback = sum(1 for o in outcomes if o.fallback_row is not None)
    raw_leaked = sum(1 for o in outcomes if o.raw_attempt1_has_forbidden_value)
    final_leaked = sum(1 for o in outcomes if o.final_text_has_forbidden_value)

    latencies = [o.latency_ms for o in outcomes if o.latency_ms is not None]
    completion_tokens = [
        float(o.completion_tokens) for o in outcomes if o.completion_tokens is not None
    ]
    tok_s_values = [
        o.completion_tokens / (o.latency_ms / 1000)
        for o in outcomes
        if o.completion_tokens and o.latency_ms and o.latency_ms > 0
    ]

    return {
        "n": n,
        "validated_first_try_rate": validated_first_try / n,
        "regeneration_rate": regenerated / n,
        "fallback_rate": used_fallback / n,
        "raw_model_leak_rate": raw_leaked / n,
        "forbidden_fact_leak_rate": final_leaked / n,
        "latency_ms_p50": percentile(latencies, 0.50),
        "latency_ms_p95": percentile(latencies, 0.95),
        "latency_ms_max": max(latencies) if latencies else None,
        "completion_tokens_p50": percentile(completion_tokens, 0.50),
        "completion_tokens_p99": percentile(completion_tokens, 0.99),
        "tokens_per_second_mean": (
            round(sum(tok_s_values) / len(tok_s_values), 2) if tok_s_values else None
        ),
    }
