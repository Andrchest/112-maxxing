"""`build_fact_definitions` — the §10.4 three-section join (D4)."""

from __future__ import annotations

import pytest
from app.domain.common.errors import ScenarioValidationError
from app.domain.enums import DisclosurePolicy, KnowledgeState, ValueType
from app.domain.facts.definitions import FactCatalog
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion

from tests.fixtures.scenarios import demo_document


@pytest.fixture
def version() -> ScenarioVersion:
    return ScenarioVersion.model_validate(demo_document())


def test_join_covers_every_world_fact_in_declaration_order(version: ScenarioVersion) -> None:
    definitions = build_fact_definitions(version)

    assert list(definitions) == list(version.world_truth.facts)


def test_join_pulls_each_field_from_its_own_section(version: ScenarioVersion) -> None:
    definition = build_fact_definitions(version)["people.victim_01.inside"]

    assert definition.fact_id == "people.victim_01.inside"
    assert definition.world_value is True
    assert definition.value_type is ValueType.BOOLEAN
    assert definition.label_ru == "Человек в квартире"
    assert definition.caller_value is True
    assert definition.knowledge is KnowledgeState.KNOWN
    assert definition.certainty == pytest.approx(1.0)
    assert definition.policy is DisclosurePolicy.ONLY_IF_EXPLICITLY_ASKED
    assert "кто-то внутри" in definition.aliases_ru
    assert definition.categories == ("people",)
    assert definition.available_after is None


def test_join_keeps_the_never_disclosed_world_value_out_of_the_llm_catalog(
    version: ScenarioVersion,
) -> None:
    definitions = build_fact_definitions(version)
    definition = definitions["incident.fire_source"]

    assert definition.world_value == "KITCHEN"
    assert definition.caller_value is None
    assert definition.policy is DisclosurePolicy.NEVER_DISCLOSE

    catalog = FactCatalog.from_definitions(definitions)
    assert "KITCHEN" not in "".join(entry.model_dump_json() for entry in catalog)


def test_join_carries_available_after(version: ScenarioVersion) -> None:
    definition = build_fact_definitions(version)["hazards.gas_cylinder"]

    assert definition.available_after is not None
    assert definition.available_after.world_event_id == "gas_cylinder_hazard"


def test_join_refuses_an_incomplete_section() -> None:
    document = demo_document()
    del document["disclosure_rules"]["facts"]["address.house"]
    version = ScenarioVersion.model_validate(document)

    with pytest.raises(ScenarioValidationError) as excinfo:
        build_fact_definitions(version)

    assert any(violation.startswith("R04:") for violation in excinfo.value.violations)
