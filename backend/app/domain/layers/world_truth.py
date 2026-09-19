"""`WorldTruth` — what objectively exists in the simulated incident (HLD `10-domain-model.md`
§10.3, D3, SPEC §3).

Written by scenario instantiation and the WorldEvent engine only; trainee commands and the caller
LLM never touch it. This module must not import any other layer module (`caller_belief`,
`operator_card`, `handoff`) — see the structural test in `backend/tests/unit/domain/layers/`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.ids import IncidentId
from app.domain.common.values import FactValue
from app.domain.enums import ValueType


class WorldTruth(BaseModel):
    """One row per incident (`incident_world_states`); `revision` starts at 0, +1 per mutation."""

    model_config = ConfigDict(extra="forbid")

    incident_id: IncidentId
    revision: int = 0
    facts: dict[str, FactValue] = Field(default_factory=dict)
    value_types: dict[str, ValueType] = Field(default_factory=dict)
