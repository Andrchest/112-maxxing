"""`ScoringRule` (HLD `10-domain-model.md` §10.14, `30-scenario-format.md` §30.7).

`config` is an opaque mapping here — validated against the evaluator-specific config model by
`app.domain.scoring.evaluators.registry.parse_rule_config`, not by this model. Field names and
defaults are copied literally from the HLD table.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EvaluatorType, RoleType, ScoringCategory


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
    applies_to_roles: tuple[RoleType, ...] = ()
    """Roles this rule scores; empty (the default) means the rule always applies.

    A rule with a non-empty list applies only when at least one listed role is in the session's
    role chain as recorded in the event log (`SESSION_CREATED.role_chain`). A non-applicable rule
    yields a zero/zero `ScoreResult` that changes neither totals nor critical errors — it never
    silently drags a DDS-only session's total down with 112-stage rules it never had a chance to
    satisfy (§10.14 "Applicability", §30.7).
    """
