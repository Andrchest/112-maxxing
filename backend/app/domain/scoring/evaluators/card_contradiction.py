"""`CARD_CONTRADICTION` evaluator (HLD `10-domain-model.md` §10.14 #4,
`30-scenario-format.md` §30.7 example #4).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.common.values import FactValue
from app.domain.enums import RoleType
from app.domain.scoring import evidence
from app.domain.scoring.comparisons import Comparison, compare, is_present, render_value
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule
from app.domain.scoring.shared import card_cutoff_evidence

EvaluatedAt = Literal["HANDOFF", "SESSION_END"]


class CardContradictionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str
    contradicts_fact_id: str
    comparison: Comparison
    require_fact_delivered: bool = True
    penalty_points: float
    evaluated_at: EvaluatedAt


def evaluate(
    rule: ScoringRule,
    config: CardContradictionConfig,
    ctx: ScoringContext,
) -> ScoreResult:
    """Does the card contradict what the caller actually said? (§10.14 #4)

    The comparison is against the **caller's** value, not the world's: SPEC §3's whole point is
    that the caller may be wrong ("the world says 27, the caller believes 72") and the operator
    who writes down what the caller said has done nothing wrong. A contradiction is the operator
    typing something the caller never told them.

    `require_fact_delivered` is what keeps that fair, and it reads `FACTS_DELIVERED` only (D10):
    the operator cannot contradict a fact the caller never got to deliver. So a fact that was
    never delivered scores `0` with the bounding event as evidence, never the penalty.
    """
    cutoff = ctx.cutoff_seq_no(config.evaluated_at)
    change = ctx.last_card_change(config.field_path, cutoff)
    actual = change.new_value if change is not None else None
    deliveries = [
        delivery
        for delivery in ctx.deliveries_of(config.contradicts_fact_id)
        if delivery.event.seq_no <= cutoff
    ]

    if not is_present(actual):
        note = f"Поле «{config.field_path}» не заполнено — противоречия нет."
        return evidence.result(
            rule,
            points=0.0,
            passed=True,
            evidence=[card_cutoff_evidence(ctx, change, note, RoleType.OPERATOR_112)],
        )

    if config.require_fact_delivered and not deliveries:
        note = (
            f"Факт «{config.contradicts_fact_id}» заявителем не сообщался — "
            f"значение «{render_value(actual)}» противоречить ему не может."
        )
        return evidence.result(
            rule,
            points=0.0,
            passed=True,
            evidence=[card_cutoff_evidence(ctx, change, note, RoleType.OPERATOR_112)],
        )

    told = _caller_value(config, ctx)
    agrees = compare(actual, told, mode=config.comparison)
    if agrees:
        note = (
            f"Поле «{config.field_path}»: {render_value(actual)} — "
            f"совпадает с сообщённым заявителем."
        )
        return evidence.result(
            rule,
            points=0.0,
            passed=True,
            evidence=[card_cutoff_evidence(ctx, change, note, RoleType.OPERATOR_112)],
        )

    note = (
        f"Поле «{config.field_path}»: в карточке {render_value(actual)}, "
        f"заявитель сообщил {render_value(told)}."
    )
    items = [card_cutoff_evidence(ctx, change, note, RoleType.OPERATOR_112)]
    if deliveries:
        items.append(
            evidence.from_event(
                deliveries[0].event,
                f"Факт «{config.contradicts_fact_id}» был доставлен на "
                f"{deliveries[0].at_offset_ms} мс.",
            )
        )
    return evidence.result(rule, points=config.penalty_points, passed=False, evidence=items)


def _caller_value(config: CardContradictionConfig, ctx: ScoringContext) -> FactValue:
    """What the caller believes about `contradicts_fact_id` (SPEC §3, §5)."""
    fact = ctx.scenario_version.caller_knowledge.facts.get(config.contradicts_fact_id)
    return fact.caller_value if fact is not None else None
