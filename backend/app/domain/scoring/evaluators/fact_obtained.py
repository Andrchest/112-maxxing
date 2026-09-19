"""`FACT_OBTAINED` evaluator config (HLD `10-domain-model.md` §10.14 #1, `30-scenario-format.md`
§30.7 example #1).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FactObtainedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    within_ms: int | None
    points: float
    penalty_if_missing: float = 0.0


# TODO(E15): evaluate(...) for FACT_OBTAINED (HLD 10.14)
