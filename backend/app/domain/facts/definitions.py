"""`FactDefinition`, `AvailableAfter`, the fact catalog, and revealed-fact tracking (HLD
`10-domain-model.md` §10.4, §10.12, D4, SPEC §5, §21, §22).

A `FactDefinition` is not stored in a scenario file; it is joined at load time from three scenario
sections keyed by the same `fact_id` (`world_truth.facts`, `caller_knowledge.facts`,
`disclosure_rules.facts`). The join itself (`build_fact_definitions`) needs `ScenarioVersion` and
is out of scope here — see the module-level TODO below.

`FactCatalogEntry` is the only fact structure the interpreter LLM ever sees (D10): it carries no
value-bearing field at all, so a scenario's world/caller values structurally cannot leak into it.

HLD gap — `RevealedFacts`: `10-domain-model.md` §10.1 lists `RevealedFacts` in this module's
responsibilities but no section assigns it fields (§10.12 defines `FactAccessGate`, which takes a
plain `revealed_fact_ids: frozenset[str]`, not a `RevealedFacts` type). The reading closest to the
spec is SPEC §21's "previously revealed facts" / SPEC §22 and D10's "`ALREADY_REVEALED`" prompt
input: the label + caller value of every fact the caller has already revealed, in scenario
declaration order. Implemented that way below; see the report for this task.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.common.values import FactValue
from app.domain.enums import DisclosurePolicy, KnowledgeState, ValueType
from app.domain.world.conditions import Condition


class AvailableAfter(BaseModel):
    """Exactly one of `sim_time_ms`, `world_event_id`, `condition` (§10.4)."""

    model_config = ConfigDict(extra="forbid")

    sim_time_ms: int | None = None
    world_event_id: str | None = None
    condition: Condition | None = None

    @model_validator(mode="after")
    def _exactly_one_key(self) -> AvailableAfter:
        chosen = (self.sim_time_ms, self.world_event_id, self.condition)
        if sum(1 for value in chosen if value is not None) != 1:
            raise ValueError(
                "AvailableAfter must set exactly one of sim_time_ms, world_event_id, condition"
            )
        return self


class FactDefinition(BaseModel):
    """One fact, joined from the three scenario sections at load time (§10.4)."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str
    world_value: FactValue
    value_type: ValueType
    label_ru: str
    caller_value: FactValue
    knowledge: KnowledgeState
    certainty: float = Field(default=1.0, ge=0.0, le=1.0)
    policy: DisclosurePolicy
    aliases_ru: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    available_after: AvailableAfter | None = None


class FactCatalogEntry(BaseModel):
    """The only fact structure the interpreter LLM ever sees (D10) — no values."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str
    label_ru: str
    aliases_ru: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()


class FactCatalog(tuple[FactCatalogEntry, ...]):
    """`tuple[FactCatalogEntry, ...]` (§10.4), built from a fact-definition mapping.

    A `tuple` subclass rather than a `BaseModel` so the HLD's `FactCatalog = tuple[FactCatalogEntry,
    ...]` type alias is literally true and callers can iterate it like any other tuple; the only
    addition is the `from_definitions` builder the HLD's module map names.
    """

    __slots__ = ()

    @classmethod
    def from_definitions(cls, definitions: Mapping[str, FactDefinition]) -> FactCatalog:
        return cls(
            FactCatalogEntry(
                fact_id=definition.fact_id,
                label_ru=definition.label_ru,
                aliases_ru=definition.aliases_ru,
                categories=definition.categories,
            )
            for definition in definitions.values()
        )


class RevealedFact(BaseModel):
    """One already-revealed fact's label + caller value, for the `ALREADY_REVEALED` prompt block.

    See the HLD-gap note at the top of this module.
    """

    model_config = ConfigDict(extra="forbid")

    fact_id: str
    label_ru: str
    value: FactValue


class RevealedFacts(BaseModel):
    """The facts already revealed to the trainee in this call (see the HLD-gap note above)."""

    model_config = ConfigDict(extra="forbid")

    items: tuple[RevealedFact, ...] = ()

    @classmethod
    def from_definitions(
        cls,
        definitions: Mapping[str, FactDefinition],
        revealed_fact_ids: frozenset[str],
    ) -> RevealedFacts:
        return cls(
            items=tuple(
                RevealedFact(
                    fact_id=definition.fact_id,
                    label_ru=definition.label_ru,
                    value=definition.caller_value,
                )
                for definition in definitions.values()
                if definition.fact_id in revealed_fact_ids
            )
        )


# TODO(E3-B): build_fact_definitions lives in app/domain/scenario/validation.py
