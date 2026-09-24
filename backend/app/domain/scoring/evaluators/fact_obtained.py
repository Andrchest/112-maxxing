"""`FACT_OBTAINED` evaluator (HLD `10-domain-model.md` §10.14 #1, `30-scenario-format.md`
§30.7 example #1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.enums import RoleType
from app.domain.scoring import evidence
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule


class FactObtainedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    within_ms: int | None
    points: float
    penalty_if_missing: float = 0.0
    on_call: Literal["CALLER_112", "DDS_CLAIMANT"] = "CALLER_112"
    """Additive, I3 E6b (HLD 80 §80.6.2): whose delivery counts — the 112 caller's (default; a ДДС
    call-back never moves it) or a claimant call-back's, for ДДС-side claimant rules."""


def evaluate(rule: ScoringRule, config: FactObtainedConfig, ctx: ScoringContext) -> ScoreResult:
    """Did the trainee get the caller to deliver `fact_id`, in time? (§10.14 #1, D10)

    `FACTS_DELIVERED` is the only input, by design: "fact delivery is decided by code, not by
    text" (D10), so rewording the caller's line cannot move this number (§42 test 10). An
    interrupted utterance produced no `FACTS_DELIVERED` and therefore obtained nothing, however
    much of it was audible.
    """
    deliveries = ctx.deliveries_of(config.fact_id, on_call=config.on_call)
    for delivery in deliveries:
        if config.within_ms is not None and delivery.at_offset_ms > config.within_ms:
            continue
        return evidence.result(
            rule,
            points=config.points,
            passed=True,
            evidence=[
                evidence.from_event(
                    delivery.event,
                    f"Факт «{config.fact_id}» получен на {delivery.at_offset_ms} мс.",
                )
            ],
        )

    if deliveries:
        note = (
            f"Факт «{config.fact_id}» получен на {deliveries[0].at_offset_ms} мс — "
            f"позже отведённых {config.within_ms} мс."
        )
        bound = deliveries[0].event
    else:
        note = f"Факт «{config.fact_id}» не был получен за время сессии."
        bound = evidence.bounding_event(ctx, RoleType.OPERATOR_112)
    return evidence.result(
        rule,
        points=config.penalty_if_missing,
        passed=False,
        evidence=[evidence.from_event(bound, note)],
    )
