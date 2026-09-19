"""`CARD_FIELD_PRESENT` evaluator config (HLD `10-domain-model.md` §10.14 #3,
`30-scenario-format.md` §30.7 example #3).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

EvaluatedAt = Literal["HANDOFF", "SESSION_END"]


class CardFieldPresentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str
    evaluated_at: EvaluatedAt
    points: float
    penalty_if_missing: float = 0.0
    treat_false_as_present: bool = True


# TODO(E15): evaluate(...) for CARD_FIELD_PRESENT (HLD 10.14)
