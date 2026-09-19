"""`ScoringRule` (HLD `10-domain-model.md` §10.14, `30-scenario-format.md` §30.7).

`config` is an opaque mapping here — validated against the evaluator-specific config model by
`app.domain.scoring.evaluators.registry.parse_rule_config`, not by this model. Field names and
defaults are copied literally from the HLD table.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EvaluatorType, ScoringCategory


class ScoringRule(BaseModel):
    """One scenario-defined scoring rule (§10.14, §30.7)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    name_ru: str
    description_ru: str
    category: ScoringCategory
    max_points: float = Field(gt=0)
    critical: bool
    evaluator_type: EvaluatorType
    config: Mapping[str, Any]
    min_evidence: int = Field(default=1, ge=1)
