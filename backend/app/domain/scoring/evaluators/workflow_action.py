"""`WORKFLOW_ACTION` evaluator config (HLD `10-domain-model.md` §10.14 #7, `30-scenario-format.md`
§30.7 example #7).
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from app.domain.common.values import FactValue
from app.domain.events.types import EventType


class WorkflowActionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: EventType
    payload_match: Mapping[str, FactValue] | None
    min_count: int = 1
    max_count: int | None
    required_stage_state: str | None
    must_occur_after: EventType | None
    points: float
    penalty_if_missing: float = 0.0
    penalty_per_excess: float = 0.0


# TODO(E15): evaluate(...) for WORKFLOW_ACTION (HLD 10.14)
