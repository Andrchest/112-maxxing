"""`HANDOFF_COMPLETENESS` evaluator config (HLD `10-domain-model.md` §10.14 #10,
`30-scenario-format.md` §30.7 example #10).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HandoffCompletenessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_field_paths: tuple[str, ...]
    points_per_field: float
    all_or_nothing: bool = False
    penalty_per_missing: float = 0.0
    treat_false_as_present: bool = True


# TODO(E15): evaluate(...) for HANDOFF_COMPLETENESS (HLD 10.14)
