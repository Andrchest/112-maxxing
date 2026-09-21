"""`CARD_FIELD_CORRECT` evaluator config (HLD `10-domain-model.md` §10.14 #2,
`30-scenario-format.md` §30.7 example #2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.common.values import FactValue
from app.domain.enums import RoleType
from app.domain.scoring import evidence
from app.domain.scoring.comparisons import Comparison, compare, is_present, render_value
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule
from app.domain.scoring.shared import card_cutoff_evidence

EvaluatedAt = Literal["HANDOFF", "SESSION_END"]


class CardFieldCorrectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str
    expected_from_fact_id: str | None
    expected_literal: FactValue
    comparison: Comparison
    tolerance: float = 0.0
    evaluated_at: EvaluatedAt
    points: float
    penalty_if_wrong: float = 0.0

    @model_validator(mode="after")
    def _exactly_one_expected_source(self) -> CardFieldCorrectConfig:
        chosen = sum(
            1 for value in (self.expected_from_fact_id, self.expected_literal) if value is not None
        )
        if chosen != 1:
            raise ValueError(
                "exactly one of expected_from_fact_id / expected_literal must be set (HLD 10.14 #2)"
            )
        return self


def evaluate(
    rule: ScoringRule,
    config: CardFieldCorrectConfig,
    ctx: ScoringContext,
) -> ScoreResult:
    """Does the card hold the right value for `field_path` at the cutoff? (§10.14 #2)

    The expected value is `world_truth` — the only evaluator that reads it, and the one place a
    human ever sees the truth next to what was typed (D11's truth-vs-card diff). The card value
    is reconstructed from the trainee's own `CARD_FIELD_CHANGED` events (D3: the operator card is
    "written by trainee commands only"), so an instructor's prefab revision never scores here.

    An empty field is *not* wrong — that is `CARD_FIELD_PRESENT`'s business (§10.14 #2) — so it
    yields `0`, not `penalty_if_wrong`.
    """
    cutoff = ctx.cutoff_seq_no(config.evaluated_at)
    change = ctx.last_card_change(config.field_path, cutoff)
    actual = change.new_value if change is not None else None
    expected = _expected(config, ctx)

    if not is_present(actual):
        return evidence.result(
            rule,
            points=0.0,
            passed=False,
            evidence=[
                card_cutoff_evidence(
                    ctx,
                    change,
                    f"Поле «{config.field_path}» не заполнено, сверять нечего.",
                    RoleType.OPERATOR_112,
                )
            ],
        )

    correct = compare(actual, expected, mode=config.comparison, tolerance=config.tolerance)
    note = (
        f"Поле «{config.field_path}»: в карточке {render_value(actual)}, "
        f"в действительности {render_value(expected)} ({config.comparison})."
    )
    return evidence.result(
        rule,
        points=config.points if correct else config.penalty_if_wrong,
        passed=correct,
        evidence=[card_cutoff_evidence(ctx, change, note, RoleType.OPERATOR_112)],
    )


def _expected(config: CardFieldCorrectConfig, ctx: ScoringContext) -> FactValue:
    """The expected value: `world_truth.facts[...].world_value`, or the literal (§10.14 #2)."""
    if config.expected_from_fact_id is None:
        return config.expected_literal
    fact = ctx.scenario_version.world_truth.facts.get(config.expected_from_fact_id)
    return fact.world_value if fact is not None else None
