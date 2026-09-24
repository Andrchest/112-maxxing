"""`ScoringRule` (HLD `10-domain-model.md` §10.14, `30-scenario-format.md` §30.7).

`config` is an opaque mapping here — validated against the evaluator-specific config model by
`app.domain.scoring.evaluators.registry.parse_rule_config`, not by this model. Field names and
defaults are copied literally from the HLD table.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

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
    applies_to_variants: Mapping[str, tuple[str, ...]] = Field(default_factory=dict)
    """Variant values this rule scores (HLD 70 §70.2.5, D14); empty (the default) always applies.

    The semantics of `applies_to_roles`: the rule applies iff, for every named switch, the
    session's value (`SESSION_CREATED.variants`, or the schema-1 derivation for a log that
    predates it) is listed. Keys and values are plain strings here; rule R40 checks that every key
    is a `SessionVariants` field and every value a member of that switch's enum.
    """

    @model_serializer(mode="wrap")
    def _omit_empty_applies_to_variants(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Leave an empty `applies_to_variants` out of a dump, so a rule written before the key
        existed dumps exactly as it did (the scenario content hash is its identity, D4)."""
        data = handler(self)
        if isinstance(data, dict) and not data.get("applies_to_variants"):
            data.pop("applies_to_variants", None)
        return data
