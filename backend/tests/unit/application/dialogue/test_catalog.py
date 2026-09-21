"""`build_fact_catalog` gives the interpreter names, never values (D10, SPEC §20, §21).

The catalog is the one fact structure that reaches the interpreter prompt. Two properties are
asserted here, and the second one is the invariant: the catalog carries `fact_id`, `label_ru`,
`aliases_ru` and `categories` and nothing else, and no caller or world value of the demo scenario
survives into its serialisation.

The leak check excludes identifier-typed fields (`fact_id`, `aliases_ru`, `categories`) from the
haystack and compares whole *values*, never substrings of a rendered number: `reports/e11-0.md`
records what a bare `"27" in dump` check costs when an unrelated id happens to contain the digits.
"""

from __future__ import annotations

import json

from app.application.dialogue.catalog import build_fact_catalog
from app.domain.enums import DisclosurePolicy, KnowledgeState
from app.domain.facts.definitions import FactCatalog, FactCatalogEntry, FactDefinition
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion

from tests.fixtures.scenarios import demo_document


def _demo_definitions() -> dict[str, FactDefinition]:
    version = ScenarioVersion.model_validate(demo_document())
    return dict(build_fact_definitions(version))


def test_the_catalog_has_one_entry_per_definition_in_scenario_order() -> None:
    definitions = _demo_definitions()

    catalog = build_fact_catalog(definitions)

    assert isinstance(catalog, FactCatalog)
    assert [entry.fact_id for entry in catalog] == list(definitions)


def test_a_never_disclose_fact_stays_in_the_catalog() -> None:
    """The interpreter must be able to recognise the question; the gate is what refuses it."""
    definitions = _demo_definitions()
    never = [
        fact_id
        for fact_id, item in definitions.items()
        if item.policy is DisclosurePolicy.NEVER_DISCLOSE
    ]

    catalog = build_fact_catalog(definitions)

    assert never, "the demo scenario is supposed to hide the fire source and the cause"
    assert set(never) <= {entry.fact_id for entry in catalog}


def test_an_unknown_fact_stays_in_the_catalog_too() -> None:
    definitions = _demo_definitions()
    unknown = [
        fact_id for fact_id, item in definitions.items() if item.knowledge is KnowledgeState.UNKNOWN
    ]

    catalog = build_fact_catalog(definitions)

    assert unknown
    assert set(unknown) <= {entry.fact_id for entry in catalog}


def test_the_entry_type_has_no_value_knowledge_or_policy_field_at_all() -> None:
    """Structural: the catalog cannot leak a value because it has nowhere to put one."""
    fields = set(FactCatalogEntry.model_fields)

    assert fields == {"fact_id", "label_ru", "aliases_ru", "categories"}
    assert not fields & {
        "value",
        "world_value",
        "caller_value",
        "knowledge",
        "certainty",
        "policy",
        "available_after",
        "value_type",
    }


def test_no_demo_value_of_either_layer_survives_into_the_catalog() -> None:
    """SPEC §5/§21 at the interpreter boundary, over the real scenario."""
    definitions = _demo_definitions()
    catalog = build_fact_catalog(definitions)

    # The haystack: only the free-text fields the catalog really carries a value-shaped string in.
    # `fact_id`, `aliases_ru` and `categories` are identifiers written by the scenario author and
    # are deliberately excluded — they are names, not data.
    haystack = [entry.label_ru for entry in catalog]

    values: set[str] = set()
    for item in definitions.values():
        for value in (item.world_value, item.caller_value):
            if isinstance(value, str) and value:
                values.add(value)

    assert values, "the demo scenario has string-valued facts on both layers"
    leaked = sorted(value for value in values if any(value in text for text in haystack))
    assert not leaked, f"the catalog's labels carry scenario values: {leaked}"


def test_the_serialised_catalog_has_exactly_the_documented_keys() -> None:
    catalog = build_fact_catalog(_demo_definitions())

    dumped = json.loads(json.dumps([entry.model_dump() for entry in catalog], ensure_ascii=False))

    assert dumped
    for entry in dumped:
        assert set(entry) == {"fact_id", "label_ru", "aliases_ru", "categories"}
