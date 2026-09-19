"""`CARD_FIELD_CORRECT` evaluator config (HLD `10-domain-model.md` §10.14 #2,
`30-scenario-format.md` §30.7 example #2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.common.values import FactValue

Comparison = Literal[
    "EXACT", "CASE_INSENSITIVE", "NUMERIC_TOLERANCE", "SET_EQUAL", "NORMALIZED_DIGITS"
]
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


# TODO(E15): evaluate(...) for CARD_FIELD_CORRECT (HLD 10.14)
