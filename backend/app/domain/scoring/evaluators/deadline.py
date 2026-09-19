"""`DEADLINE` evaluator config (HLD `10-domain-model.md` §10.14 #6, `30-scenario-format.md` §30.7
example #6).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.common.values import FactValue
from app.domain.events.types import EventType

Scale = Literal["STEP", "LINEAR"]


class DeadlineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    from_event_type: EventType | Literal["SESSION_START"]
    to_event_type: EventType
    to_payload_match: Mapping[str, FactValue] | None
    max_offset_ms: int
    points: float
    penalty_if_late: float = 0.0
    scale: Scale
    linear_zero_ms: int | None


# TODO(E15): evaluate(...) for DEADLINE (HLD 10.14)
