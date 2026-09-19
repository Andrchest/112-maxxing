"""`Scenario` and `ScenarioVersion` (HLD `10-domain-model.md` §10.15, `30-scenario-format.md`
§30.1, SPEC §4, D4).

`Scenario` (identity: slug, title) and `ScenarioVersion` (content) are separate types and separate
tables (D4). The top-level keys of `ScenarioVersion` are exactly the SPEC §4 list, in that order;
`extra="forbid"` rejects any additional key (§30.8 rule 1).

A `ScenarioVersion` becomes immutable as soon as a simulation starts using it (SPEC §4); the model
is frozen here, and the DB trigger enforces the same at rest (D4).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.ids import ScenarioId, ScenarioVersionId
from app.domain.enums import RoleType
from app.domain.scenario.sections import (
    CallerKnowledgeSection,
    CallerProfileSection,
    DisclosureRulesSection,
    ExpectedResponse,
    ResourceSpec,
    WorldTruthSection,
)
from app.domain.scoring.rules import ScoringRule
from app.domain.world.events import WorldEventDefinition

SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})
"""Format revisions this loader understands; the loader rejects an unknown value (§30.1)."""


class Scenario(BaseModel):
    """Scenario identity — the owner of one or more `ScenarioVersion`s (§10.15, D4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: ScenarioId
    slug: str
    title_ru: str


class ScenarioVersion(BaseModel):
    """One immutable scenario version: exactly the SPEC §4 top-level keys (§10.15, §30.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: ScenarioVersionId
    schema_version: int
    scenario_id: ScenarioId
    version: int = Field(ge=1)
    title: str
    description: str
    difficulty: int = Field(ge=1, le=5)
    deterministic_seed: str
    role_chain: tuple[RoleType, ...]
    world_truth: WorldTruthSection
    caller_profile: CallerProfileSection
    caller_knowledge: CallerKnowledgeSection
    disclosure_rules: DisclosureRulesSection
    expected_response: ExpectedResponse
    available_resources: tuple[ResourceSpec, ...]
    world_events: tuple[WorldEventDefinition, ...]
    scoring_rules: tuple[ScoringRule, ...]
