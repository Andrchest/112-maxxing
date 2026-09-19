"""Tests for `app.domain.facts.definitions` (HLD `10-domain-model.md` §10.4, D4).

Covers `AvailableAfter`'s exactly-one-key rule, that `FactCatalogEntry`/`FactCatalog` carry no
value-bearing field (a scenario's world value must not survive serialisation into the catalog the
interpreter LLM sees — SPEC §5), and `RevealedFacts.from_definitions`.
"""

from __future__ import annotations

import json

import pytest
from app.domain.enums import DisclosurePolicy, KnowledgeState, ValueType
from app.domain.facts.definitions import (
    AvailableAfter,
    FactCatalog,
    FactCatalogEntry,
    FactDefinition,
    RevealedFacts,
)
from app.domain.world.conditions import Condition
from pydantic import ValidationError


def _definition(fact_id: str, **overrides: object) -> FactDefinition:
    defaults: dict[str, object] = {
        "fact_id": fact_id,
        "world_value": "KITCHEN",
        "value_type": ValueType.STRING,
        "label_ru": "Источник возгорания",
        "caller_value": None,
        "knowledge": KnowledgeState.UNKNOWN,
        "policy": DisclosurePolicy.NEVER_DISCLOSE,
    }
    defaults.update(overrides)
    return FactDefinition(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# AvailableAfter
# ---------------------------------------------------------------------------------------------


def test_available_after_accepts_sim_time_ms() -> None:
    AvailableAfter(sim_time_ms=180_000)


def test_available_after_accepts_world_event_id() -> None:
    AvailableAfter(world_event_id="fire_spreads")


def test_available_after_accepts_condition() -> None:
    AvailableAfter(condition=Condition.model_validate({"sim_time": {"op": "GTE", "ms": 1000}}))


def test_available_after_rejects_no_key() -> None:
    with pytest.raises(ValidationError):
        AvailableAfter()


def test_available_after_rejects_two_keys() -> None:
    with pytest.raises(ValidationError):
        AvailableAfter(sim_time_ms=1000, world_event_id="fire_spreads")


# ---------------------------------------------------------------------------------------------
# FactCatalogEntry / FactCatalog — no value-bearing field
# ---------------------------------------------------------------------------------------------


def test_fact_catalog_entry_has_no_value_field() -> None:
    entry = FactCatalogEntry(fact_id="incident.fire_source", label_ru="Источник возгорания")
    assert "value" not in type(entry).model_fields
    assert not hasattr(entry, "value")
    assert not hasattr(entry, "world_value")
    assert not hasattr(entry, "caller_value")


def test_fact_catalog_from_definitions_never_leaks_the_world_value() -> None:
    definitions = {
        "incident.fire_source": _definition(
            "incident.fire_source",
            world_value="KITCHEN",
            label_ru="Источник возгорания",
            policy=DisclosurePolicy.NEVER_DISCLOSE,
        )
    }

    catalog = FactCatalog.from_definitions(definitions)

    assert isinstance(catalog, tuple)
    assert len(catalog) == 1
    serialized = json.dumps([entry.model_dump(mode="json") for entry in catalog])
    assert "KITCHEN" not in serialized


def test_fact_catalog_entry_fields_match_the_definition() -> None:
    definitions = {
        "people.total_affected": _definition(
            "people.total_affected",
            label_ru="Всего людей в опасности",
            aliases_ru=("сколько людей",),
            categories=("people",),
        )
    }

    catalog = FactCatalog.from_definitions(definitions)

    entry = catalog[0]
    assert entry.fact_id == "people.total_affected"
    assert entry.label_ru == "Всего людей в опасности"
    assert entry.aliases_ru == ("сколько людей",)
    assert entry.categories == ("people",)


# ---------------------------------------------------------------------------------------------
# RevealedFacts
# ---------------------------------------------------------------------------------------------


def test_revealed_facts_includes_only_revealed_ids() -> None:
    definitions = {
        "incident.fire_source": _definition(
            "incident.fire_source", caller_value=None, knowledge=KnowledgeState.UNKNOWN
        ),
        "address.street": _definition(
            "address.street",
            world_value="Ленина",
            caller_value="Ленина",
            knowledge=KnowledgeState.KNOWN,
            policy=DisclosurePolicy.SPONTANEOUS,
        ),
    }

    revealed = RevealedFacts.from_definitions(definitions, frozenset({"address.street"}))

    assert len(revealed.items) == 1
    assert revealed.items[0].fact_id == "address.street"
    assert revealed.items[0].value == "Ленина"


def test_revealed_facts_empty_when_nothing_revealed() -> None:
    definitions = {"incident.fire_source": _definition("incident.fire_source")}

    revealed = RevealedFacts.from_definitions(definitions, frozenset())

    assert revealed.items == ()
