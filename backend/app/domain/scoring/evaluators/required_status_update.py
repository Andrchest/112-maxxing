"""`REQUIRED_STATUS_UPDATE` evaluator config (HLD `10-domain-model.md` §10.14 #9,
`30-scenario-format.md` §30.7 example #9).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.enums import StatusUpdateKind
from app.domain.events.types import EventType


class RequiredStatusUpdateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    update_kind: StatusUpdateKind
    min_count: int = 1
    within_ms_of_event: EventType | None
    within_ms: int | None
    points: float
    penalty_if_missing: float = 0.0


# TODO(E15): evaluate(...) for REQUIRED_STATUS_UPDATE (HLD 10.14)
