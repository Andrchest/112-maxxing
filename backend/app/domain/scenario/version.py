"""`Scenario` and `ScenarioVersion` (HLD `10-domain-model.md` §10.15, `30-scenario-format.md`
§30.1, SPEC §4, D4).

`Scenario` (identity: slug, title) and `ScenarioVersion` (content) are separate types and separate
tables (D4). A `schema_version: 1` document has exactly the SPEC §4 top-level keys, in that order;
`schema_version: 2` adds the optional keys `variants` (D14 amends D4, HLD 70 §70.2),
`reference_pack` (I3 E2a, §70.5.4, §70.6) and `timers` (I3 E4a, §70.3.4), and the nested
`expected_response.responders` (I3 E5b, §70.4.5). `extra="forbid"` rejects any other key (§30.8
rule 1), and rule R01 refuses `variants`, `reference_pack`, `timers` and `responders` in a
schema-1 document.

A `ScenarioVersion` becomes immutable as soon as a simulation starts using it (SPEC §4); the model
is frozen here, and the DB trigger enforces the same at rest (D4).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from app.domain.common.ids import ScenarioId, ScenarioVersionId
from app.domain.dds.card_status import DEFAULT_CARD_TIMERS, CardTimers
from app.domain.enums import RoleType
from app.domain.routing.catalog import DEFAULT_PACK_ID
from app.domain.scenario.sections import (
    CallerKnowledgeSection,
    CallerProfileSection,
    DisclosureRulesSection,
    ExpectedResponse,
    ResourceSpec,
    WorldTruthSection,
)
from app.domain.scoring.rules import ScoringRule
from app.domain.session.variants import ScenarioVariants, derive_scenario_variants
from app.domain.world.events import WorldEventDefinition

SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1, 2})
"""Format revisions this loader understands; the loader rejects an unknown value (§30.1)."""


class Scenario(BaseModel):
    """Scenario identity — the owner of one or more `ScenarioVersion`s (§10.15, D4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: ScenarioId
    slug: str
    title_ru: str


class ScenarioVersion(BaseModel):
    """One immutable scenario version: the SPEC §4 top-level keys, plus `variants`,
    `reference_pack` and `timers` from schema 2 (§10.15, §30.1, D14, D15, D18)."""

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
    variants: ScenarioVariants | None = None
    """Schema 2 only (HLD 70 §70.2.2): the declared *supported + default* variants."""
    reference_pack: str | None = None
    """Schema 2 only (HLD 70 §70.5.4, §70.6.1): the `reference/manifest.json` pack the scenario's
    card schema and service catalog come from. Absent ⇒ `DEFAULT_PACK_ID` (`legacy-r1`)."""
    timers: CardTimers | None = None
    """Schema 2 only (HLD 70 §70.3.4): the per-card timers in session ms; every absent key (and
    an absent `timers`) takes its default — `card_timers` resolves them."""

    @model_serializer(mode="wrap")
    def _omit_absent_schema_2_keys(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Leave the schema-2 keys out of a dump when the document has none.

        `canonical_content` is `model_dump(mode="json")` and its SHA-256 is the version's
        identity (D4): a schema-1 document must dump byte-for-byte as it did before the keys
        existed, or re-importing an unchanged, locked version would be refused (P5).
        """
        data = handler(self)
        if isinstance(data, dict):
            for key in ("variants", "reference_pack", "timers"):
                if data.get(key) is None:
                    data.pop(key, None)
        return data

    @property
    def reference_pack_id(self) -> str:
        """The pack this version uses: `reference_pack`, or `legacy-r1` when it names none."""
        return self.reference_pack if self.reference_pack is not None else DEFAULT_PACK_ID

    @property
    def card_timers(self) -> CardTimers:
        """The resolved timers: `timers`, or every default when the document has none (§70.3.4)."""
        return self.timers if self.timers is not None else DEFAULT_CARD_TIMERS

    @property
    def scenario_variants(self) -> ScenarioVariants:
        """The declared `variants`, or the derivation a document without the key gets (P5)."""
        return derive_scenario_variants(
            schema_version=self.schema_version,
            role_chain=self.role_chain,
            has_prefab_handoff=self.expected_response.prefab_handoff is not None,
            declared=self.variants,
        )
