"""`CallerBelief` — what the simulated caller believes/knows (HLD `10-domain-model.md` §10.3, D3,
SPEC §3).

Written by scenario instantiation and the WorldEvent engine only. This module must not import any
other layer module (`world_truth`, `operator_card`, `handoff`) — see the structural test in
`backend/tests/unit/domain/layers/`. `EmotionState` (from `app.domain.caller.emotion`) is not a
layer type, so embedding it here does not violate that rule.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.caller.emotion import EmotionState
from app.domain.common.ids import IncidentId
from app.domain.common.values import FactValue
from app.domain.enums import KnowledgeState


class CallerBelief(BaseModel):
    """One row per incident (`incident_caller_beliefs`).

    `revealed_fact_ids` is maintained by `FACTS_DELIVERED` only (D10), never by the fact gate.
    """

    model_config = ConfigDict(extra="forbid")

    incident_id: IncidentId
    revision: int = 0
    facts: dict[str, FactValue] = Field(default_factory=dict)
    knowledge: dict[str, KnowledgeState] = Field(default_factory=dict)
    certainty: dict[str, float] = Field(default_factory=dict)
    emotion: EmotionState
    revealed_fact_ids: frozenset[str] = frozenset()
