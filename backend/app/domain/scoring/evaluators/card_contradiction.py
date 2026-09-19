"""`CARD_CONTRADICTION` evaluator config (HLD `10-domain-model.md` §10.14 #4,
`30-scenario-format.md` §30.7 example #4).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Comparison = Literal[
    "EXACT", "CASE_INSENSITIVE", "NUMERIC_TOLERANCE", "SET_EQUAL", "NORMALIZED_DIGITS"
]
EvaluatedAt = Literal["HANDOFF", "SESSION_END"]


class CardContradictionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str
    contradicts_fact_id: str
    comparison: Comparison
    require_fact_delivered: bool = True
    penalty_points: float
    evaluated_at: EvaluatedAt


# TODO(E15): evaluate(...) for CARD_CONTRADICTION (HLD 10.14)
