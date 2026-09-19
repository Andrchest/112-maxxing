"""`SERVICE_SELECTION` evaluator config (HLD `10-domain-model.md` §10.14 #5, `30-scenario-format.md`
§30.7 example #5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.enums import ServiceType

EvaluatedAt = Literal["HANDOFF", "SESSION_END"]


class ServiceSelectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_services: tuple[ServiceType, ...]
    forbidden_services: tuple[ServiceType, ...] = ()
    points_per_required: float
    penalty_per_forbidden: float = 0.0
    all_or_nothing: bool = False
    evaluated_at: EvaluatedAt


# TODO(E15): evaluate(...) for SERVICE_SELECTION (HLD 10.14)
