"""`CARD_FIELD_PRESENT` evaluator (HLD `10-domain-model.md` §10.14 #3,
`30-scenario-format.md` §30.7 example #3).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.enums import RoleType
from app.domain.scoring import evidence
from app.domain.scoring.comparisons import is_present, render_value
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule
from app.domain.scoring.shared import card_cutoff_evidence

EvaluatedAt = Literal["HANDOFF", "SESSION_END"]


class CardFieldPresentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str
    evaluated_at: EvaluatedAt
    points: float
    penalty_if_missing: float = 0.0
    treat_false_as_present: bool = True


def evaluate(
    rule: ScoringRule,
    config: CardFieldPresentConfig,
    ctx: ScoringContext,
) -> ScoreResult:
    """Is `field_path` filled in at the cutoff? (§10.14 #3)

    "Filled in" is `is_present`: non-null, and non-empty for strings and lists. Evidence is the
    *first* change to the path (§10.14 #3) — the moment the trainee entered something — and, for
    a field never filled, the `HANDOFF_CREATED` that went out without it (D11).
    """
    cutoff = ctx.cutoff_seq_no(config.evaluated_at)
    first = ctx.first_card_change(config.field_path, cutoff)
    last = ctx.last_card_change(config.field_path, cutoff)
    value = last.new_value if last is not None else None
    present = is_present(value, treat_false_as_present=config.treat_false_as_present)

    if present:
        note = f"Поле «{config.field_path}» заполнено: {render_value(value)}."
        return evidence.result(
            rule,
            points=config.points,
            passed=True,
            evidence=[card_cutoff_evidence(ctx, first, note, RoleType.OPERATOR_112)],
        )

    note = f"Поле «{config.field_path}» осталось незаполненным."
    return evidence.result(
        rule,
        points=config.penalty_if_missing,
        passed=False,
        evidence=[card_cutoff_evidence(ctx, first, note, RoleType.OPERATOR_112)],
    )
