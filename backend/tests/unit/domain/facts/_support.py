"""Builders shared by the Fact Access Gate tests (HLD `10-domain-model.md` §10.12).

Deliberately tiny: a `FactDefinition` with every §10.4 field defaulted, and the `CallerBelief`
that a set of definitions instantiates to. Nothing here decides anything the gate decides.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from app.domain.caller.emotion import EmotionState
from app.domain.common.ids import IncidentId
from app.domain.common.values import FactValue
from app.domain.enums import DisclosurePolicy, EmotionLabel, KnowledgeState, ValueType
from app.domain.facts.definitions import AvailableAfter, FactDefinition
from app.domain.layers.caller_belief import CallerBelief

INCIDENT_ID = IncidentId(UUID("11111111-2222-3333-4444-555555555555"))


def definition(
    fact_id: str,
    *,
    policy: DisclosurePolicy = DisclosurePolicy.ON_ASK,
    knowledge: KnowledgeState = KnowledgeState.KNOWN,
    world_value: FactValue = "world",
    caller_value: FactValue = "world",
    certainty: float = 1.0,
    label_ru: str = "Метка",
    available_after: AvailableAfter | None = None,
    aliases_ru: tuple[str, ...] = (),
    categories: tuple[str, ...] = (),
    value_type: ValueType = ValueType.STRING,
    enum_name: str | None = None,
) -> FactDefinition:
    """One `FactDefinition`; `KNOWN` defaults to `caller_value == world_value` as D4 requires."""
    return FactDefinition(
        fact_id=fact_id,
        world_value=world_value,
        value_type=value_type,
        label_ru=label_ru,
        caller_value=caller_value,
        knowledge=knowledge,
        certainty=certainty,
        policy=policy,
        aliases_ru=aliases_ru,
        categories=categories,
        available_after=available_after,
        enum_name=enum_name,
    )


def definitions(*defs: FactDefinition) -> dict[str, FactDefinition]:
    """A `fact_id -> FactDefinition` mapping in declaration order (the scenario's order)."""
    return {item.fact_id: item for item in defs}


def belief(
    defs: Mapping[str, FactDefinition],
    *,
    revealed: frozenset[str] = frozenset(),
) -> CallerBelief:
    """What `instantiate_caller_belief` would produce for `defs` — caller values only."""
    return CallerBelief(
        incident_id=INCIDENT_ID,
        revision=0,
        facts={fact_id: item.caller_value for fact_id, item in defs.items()},
        knowledge={fact_id: item.knowledge for fact_id, item in defs.items()},
        certainty={fact_id: item.certainty for fact_id, item in defs.items()},
        emotion=EmotionState(emotion=EmotionLabel.WORRIED, stress_level=0.5),
        revealed_fact_ids=revealed,
    )
