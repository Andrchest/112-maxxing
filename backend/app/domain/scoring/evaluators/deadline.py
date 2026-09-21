"""`DEADLINE` evaluator (HLD `10-domain-model.md` §10.14 #6, `30-scenario-format.md` §30.7
example #6).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.common.values import FactValue
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring import evidence
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.results import ScoreEvidence, ScoreResult
from app.domain.scoring.rules import ScoringRule
from app.domain.scoring.shared import payload_matches

Scale = Literal["STEP", "LINEAR"]


class DeadlineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    from_event_type: EventType | Literal["SESSION_START"]
    to_event_type: EventType
    to_payload_match: Mapping[str, FactValue] | None
    max_offset_ms: int
    points: float
    penalty_if_late: float = 0.0
    scale: Scale
    linear_zero_ms: int | None


def evaluate(rule: ScoringRule, config: DeadlineConfig, ctx: ScoringContext) -> ScoreResult:
    """How long did it take to get from one event to the other? (§10.14 #6)

    `SESSION_START` is offset `0` by definition — `monotonic_offset_ms` is measured from it
    (§10.13) — so it needs no event to subtract, only one to point at as evidence.

    `LINEAR` awards full `points` up to `max_offset_ms`, then falls straight to `0` at
    `linear_zero_ms`, then drops to `penalty_if_late`. A `LINEAR` rule without `linear_zero_ms`
    has no ramp to walk down and behaves as `STEP`; a `linear_zero_ms` at or below
    `max_offset_ms` is a zero-width ramp and does the same.
    """
    start = _from_event(ctx, config)
    if start is None:
        bound = evidence.bounding_event(ctx)
        note = f"Событие {_from_label(config)} в журнале отсутствует — отсчёт не начался."
        return evidence.result(
            rule,
            points=config.penalty_if_late,
            passed=False,
            evidence=[evidence.from_event(bound, note)],
        )
    start_offset = 0 if config.from_event_type == "SESSION_START" else start.monotonic_offset_ms

    finish = _to_event(ctx, config, start.seq_no)
    if finish is None:
        bound = evidence.bounding_event(ctx)
        items = [
            evidence.from_event(start, f"Отсчёт начат: {_from_label(config)}."),
            evidence.from_event(
                bound,
                f"Событие {config.to_event_type.value} так и не произошло.",
            ),
        ]
        return evidence.result(
            rule, points=config.penalty_if_late, passed=False, evidence=_dedupe(items)
        )

    delta = finish.monotonic_offset_ms - start_offset
    points, passed = _points(config, delta)
    note = (
        f"{_from_label(config)} → {config.to_event_type.value}: {delta} мс "
        f"при норме {config.max_offset_ms} мс."
    )
    items = [
        evidence.from_event(start, f"Отсчёт начат: {_from_label(config)}."),
        evidence.from_event(finish, note),
    ]
    return evidence.result(rule, points=points, passed=passed, evidence=_dedupe(items))


def _points(config: DeadlineConfig, delta: int) -> tuple[float, bool]:
    if delta <= config.max_offset_ms:
        return config.points, True
    if config.scale == "LINEAR" and config.linear_zero_ms is not None:
        zero = config.linear_zero_ms
        if delta >= zero:
            return config.penalty_if_late, False
        if zero > config.max_offset_ms:
            span = zero - config.max_offset_ms
            remaining = zero - delta
            return config.points * (remaining / span), False
    return config.penalty_if_late, False


def _from_event(ctx: ScoringContext, config: DeadlineConfig) -> SessionEvent | None:
    """The event the clock starts at (or the one `SESSION_START` points at as evidence)."""
    if config.from_event_type == "SESSION_START":
        started = ctx.first_of_type(EventType.SESSION_STARTED)
        if started is not None:
            return started
        return ctx.first_of_type(EventType.SESSION_CREATED)
    return ctx.first_of_type(config.from_event_type)


def _to_event(
    ctx: ScoringContext,
    config: DeadlineConfig,
    after_seq_no: int,
) -> SessionEvent | None:
    for event in ctx.of_type(config.to_event_type):
        if event.seq_no < after_seq_no:
            continue
        if payload_matches(event, config.to_payload_match):
            return event
    return None


def _from_label(config: DeadlineConfig) -> str:
    if config.from_event_type == "SESSION_START":
        return "SESSION_START"
    return config.from_event_type.value


def _dedupe(items: list[ScoreEvidence]) -> list[ScoreEvidence]:
    """Both bounds may be the same event; a result still carries at least one evidence item."""
    seen: list[ScoreEvidence] = []
    for item in items:
        if not any(
            other.event_id == item.event_id and other.seq_no == item.seq_no for other in seen
        ):
            seen.append(item)
    return seen
