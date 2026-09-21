"""`forbidden_values` — §7.6's world-value leak set (HLD §7.6, D10, SPEC §43).

The set is what `forbidden_fact_leak_rate` is measured against, so the two exclusions §7.6 names
(booleans, values shorter than two characters) and the two inclusions (world *and* caller values of
facts outside the package) each get a case.
"""

from __future__ import annotations

from app.application.dialogue.forbidden_values import forbidden_values

from tests.unit.application.dialogue._support import demo_definitions, gate_package


def test_a_world_value_of_a_fact_outside_the_package_is_forbidden() -> None:
    definitions = demo_definitions()
    package, _ = gate_package(("address.street",), definitions=definitions)

    values = forbidden_values(definitions, package, frozenset())

    assert "неисправная электропроводка" in values
    assert "Соколова Ирина Петровна" in values


def test_a_released_facts_values_are_not_forbidden() -> None:
    definitions = demo_definitions()
    package, _ = gate_package(("address.street",), definitions=definitions)

    values = forbidden_values(definitions, package, frozenset())

    assert "улица Николаева" not in values


def test_an_already_revealed_facts_values_are_not_forbidden() -> None:
    """§7.6: "not in the current package **and not already revealed**"."""
    definitions = demo_definitions()
    package, _ = gate_package(("incident.type",), definitions=definitions)

    values = forbidden_values(definitions, package, frozenset({"address.street"}))

    assert "улица Николаева" not in values


def test_both_the_world_and_the_caller_value_are_forbidden_when_they_differ() -> None:
    """The demo's `address.floor` is an INCORRECT_BELIEF: world 4, caller 5."""
    definitions = demo_definitions()
    package, _ = gate_package(("incident.type",), definitions=definitions)

    values = forbidden_values(definitions, package, frozenset())

    assert "4" not in values and "5" not in values  # both are one character: §7.6 skips them
    assert definitions["address.floor"].world_value == 4
    assert definitions["address.floor"].caller_value == 5


def test_boolean_values_are_skipped() -> None:
    """§7.6: booleans "carry no information and would false-positive constantly"."""
    definitions = demo_definitions()
    package, _ = gate_package(("address.street",), definitions=definitions)

    values = forbidden_values(definitions, package, frozenset())

    assert "True" not in values
    assert "true" not in values
    assert "False" not in values


def test_values_shorter_than_two_characters_are_skipped() -> None:
    definitions = demo_definitions()
    package, _ = gate_package(("address.street",), definitions=definitions)

    values = forbidden_values(definitions, package, frozenset())

    assert all(len(value) >= 2 for value in values)
    # `address.entrance` is "3" — one character, so it never reaches the validator.
    assert definitions["address.entrance"].world_value == "3"
    assert "3" not in values


def test_the_result_is_deduplicated_and_in_scenario_order() -> None:
    definitions = demo_definitions()
    package, _ = gate_package(("incident.type",), definitions=definitions)

    values = forbidden_values(definitions, package, frozenset())

    assert len(values) == len(set(values))
    assert values.index("Смоленск") < values.index("улица Николаева")


def test_the_function_is_pure() -> None:
    definitions = demo_definitions()
    package, _ = gate_package(("address.street",), definitions=definitions)
    before = {fact_id: item.model_copy(deep=True) for fact_id, item in definitions.items()}

    forbidden_values(definitions, package, frozenset())

    assert definitions == before
