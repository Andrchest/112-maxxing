"""One failing fixture per §30.8 rule R01-R31 (`docs/hld/30-scenario-format.md`).

Every fixture is produced at test time by applying ONE minimal mutation to the committed demo
document (`scenarios/examples/apartment-fire/v1.yaml`). The test asserts that the resulting
violations contain that rule's `R<nn>:` prefix and — to prove the fixture is minimal — no other
rule number, unless a second rule is logically implied, in which case the pair is listed
explicitly in `ALSO_ALLOWED` below.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from app.domain.common.errors import ScenarioValidationError
from app.domain.scenario.validation import (
    scenario_version_violations,
    validate_scenario_document,
    validate_scenario_version,
)
from app.domain.scenario.version import ScenarioVersion

from tests.fixtures.scenarios import demo_document

Document = dict[str, Any]
Mutation = Callable[[Document], None]

RULE_RE = re.compile(r"\bR(\d{2}):")

GHOST_FACT = "ghost.fact"
GHOST_CONDITION = {"fact": {"fact_id": GHOST_FACT, "layer": "WORLD", "op": "IS_NOT_NULL"}}
#: The same unknown fact, on the CALLER layer. An `available_after` fixture has to use this one:
#: a WORLD-layer leaf there is R31's own violation (E17 R3), which would stop R13's fixture being
#: minimal.
GHOST_CALLER_CONDITION = {"fact": {"fact_id": GHOST_FACT, "layer": "CALLER", "op": "IS_NOT_NULL"}}


def _facts(document: Document, section: str) -> dict[str, Any]:
    return document[section]["facts"]


def _rule(document: Document, rule_id: str) -> dict[str, Any]:
    for rule in document["scoring_rules"]:
        if rule["rule_id"] == rule_id:
            return rule
    raise AssertionError(f"demo scenario has no scoring rule {rule_id!r}")


def _event(document: Document, world_event_id: str) -> dict[str, Any]:
    for event in document["world_events"]:
        if event["world_event_id"] == world_event_id:
            return event
    raise AssertionError(f"demo scenario has no world event {world_event_id!r}")


def _effect(document: Document, world_event_id: str, kind: str) -> dict[str, Any]:
    for effect in _event(document, world_event_id)["effects"]:
        if effect["kind"] == kind:
            return effect
    raise AssertionError(f"world event {world_event_id!r} has no {kind} effect")


# ---------------------------------------------------------------------------------------------
# The mutation table: exactly one minimal mutation per rule.
# ---------------------------------------------------------------------------------------------


def _r01_unknown_top_level_key(document: Document) -> None:
    document["unexpected_key"] = 1


def _r02_caller_fact_without_world_fact(document: Document) -> None:
    _facts(document, "caller_knowledge")[GHOST_FACT] = {
        "caller_value": None,
        "knowledge": "UNKNOWN",
    }


def _r03_disclosure_fact_without_world_fact(document: Document) -> None:
    _facts(document, "disclosure_rules")[GHOST_FACT] = {"policy": "ON_ASK"}


def _r04_world_fact_without_caller_entry(document: Document) -> None:
    del _facts(document, "caller_knowledge")["incident.cause"]


def _r05_known_disagrees_with_world(document: Document) -> None:
    _facts(document, "caller_knowledge")["address.house"]["caller_value"] = "72"


def _r06_unknown_has_a_value(document: Document) -> None:
    _facts(document, "caller_knowledge")["incident.fire_source"]["caller_value"] = "KITCHEN"


def _r07_incorrect_belief_equals_world(document: Document) -> None:
    _facts(document, "caller_knowledge")["address.floor"]["caller_value"] = 4


def _r08_uncertain_is_fully_certain(document: Document) -> None:
    _facts(document, "caller_knowledge")["people.victim_01.age"]["certainty"] = 1.0


def _r09_certainty_out_of_range(document: Document) -> None:
    _facts(document, "caller_knowledge")["address.house"]["certainty"] = -0.5


def _r10_world_value_type_mismatch(document: Document) -> None:
    _facts(document, "world_truth")["incident.cause"]["world_value"] = 123


def _r11_scoring_rule_unknown_fact_id(document: Document) -> None:
    _rule(document, "fact_victim_inside")["config"]["fact_id"] = GHOST_FACT


def _r12_world_event_unknown_fact_id(document: Document) -> None:
    effect = _effect(document, "fire_spreads", "MUTATE_WORLD_TRUTH")
    effect["changes"] = {GHOST_FACT: True}


def _r13_available_after_condition_unknown_fact_id(document: Document) -> None:
    _facts(document, "disclosure_rules")["hazards.gas_cylinder"]["available_after"] = {
        "condition": GHOST_CALLER_CONDITION
    }


def _r14_scoring_rule_unknown_card_field_path(document: Document) -> None:
    _rule(document, "card_house_correct")["config"]["field_path"] = "address.unknown_field"


def _r15_duplicate_callsign(document: Document) -> None:
    document["available_resources"][1]["callsign"] = document["available_resources"][0]["callsign"]


def _r16_effect_unknown_resource_id(document: Document) -> None:
    _effect(document, "ac2_breakdown", "ALTER_RESOURCE_AVAILABILITY")["resource_id"] = "ghost_unit"


def _r17_required_capability_not_covered(document: Document) -> None:
    document["expected_response"]["required_resource_capabilities"].append("POWER_SHUTOFF")


def _r18_role_chain_contains_unimplemented_role(document: Document) -> None:
    document["role_chain"] = ["OPERATOR_112", "EDDS"]


def _r19_duplicate_scoring_rule_id(document: Document) -> None:
    document["scoring_rules"][1]["rule_id"] = document["scoring_rules"][0]["rule_id"]


def _r20_config_does_not_match_evaluator(document: Document) -> None:
    _rule(document, "fact_victim_inside")["config"]["bogus_key"] = 1


def _r21_duplicate_world_event_id(document: Document) -> None:
    _event(document, "ac2_breakdown")["world_event_id"] = "fire_spreads"


def _r22_unconditional_zero_delay_cycle(document: Document) -> None:
    _event(document, "fire_spreads")["effects"].append(
        {"kind": "TRIGGER_EVENT", "world_event_id": "fire_spreads", "delay_ms": 0}
    )


def _r23_available_after_unknown_world_event_id(document: Document) -> None:
    _facts(document, "disclosure_rules")["hazards.gas_cylinder"]["available_after"] = {
        "world_event_id": "ghost_event"
    }


def _r24_probability_out_of_range(document: Document) -> None:
    _event(document, "ac2_breakdown")["probability"] = 1.5


def _r25_negative_at_ms(document: Document) -> None:
    _event(document, "fire_spreads")["at_ms"] = -1


def _r26_condition_is_a_string_expression(document: Document) -> None:
    document["expected_response"]["resolution_condition"] = "sim_time > 540000"


def _r27_duplicate_emotion_rule_id(document: Document) -> None:
    rules = document["caller_profile"]["emotion_rules"]
    rules[1]["rule_id"] = rules[0]["rule_id"]


def _r28_missing_resolution_condition(document: Document) -> None:
    del document["expected_response"]["resolution_condition"]


def _r29_dds_chain_without_prefab_handoff(document: Document) -> None:
    # One logical change: the chain starts at DDS, which is exactly what makes the (now absent)
    # prefab handoff mandatory (D6). Removing the prefab alone is legal for this chain.
    document["role_chain"] = ["DDS"]
    del document["expected_response"]["prefab_handoff"]


def _r30_empty_deterministic_seed(document: Document) -> None:
    document["deterministic_seed"] = ""


def _r31_available_after_condition_needs_world_truth(document: Document) -> None:
    """E17 R3: the fact gate has no `WorldTruth`, so a WORLD-layer leaf never opens the fact."""
    _facts(document, "disclosure_rules")["hazards.gas_cylinder"]["available_after"] = {
        "condition": {
            "fact": {"fact_id": "hazards.gas_cylinder", "layer": "WORLD", "op": "EQ", "value": True}
        }
    }


MUTATIONS: dict[int, Mutation] = {
    1: _r01_unknown_top_level_key,
    2: _r02_caller_fact_without_world_fact,
    3: _r03_disclosure_fact_without_world_fact,
    4: _r04_world_fact_without_caller_entry,
    5: _r05_known_disagrees_with_world,
    6: _r06_unknown_has_a_value,
    7: _r07_incorrect_belief_equals_world,
    8: _r08_uncertain_is_fully_certain,
    9: _r09_certainty_out_of_range,
    10: _r10_world_value_type_mismatch,
    11: _r11_scoring_rule_unknown_fact_id,
    12: _r12_world_event_unknown_fact_id,
    13: _r13_available_after_condition_unknown_fact_id,
    14: _r14_scoring_rule_unknown_card_field_path,
    15: _r15_duplicate_callsign,
    16: _r16_effect_unknown_resource_id,
    17: _r17_required_capability_not_covered,
    18: _r18_role_chain_contains_unimplemented_role,
    19: _r19_duplicate_scoring_rule_id,
    20: _r20_config_does_not_match_evaluator,
    21: _r21_duplicate_world_event_id,
    22: _r22_unconditional_zero_delay_cycle,
    23: _r23_available_after_unknown_world_event_id,
    24: _r24_probability_out_of_range,
    25: _r25_negative_at_ms,
    26: _r26_condition_is_a_string_expression,
    27: _r27_duplicate_emotion_rule_id,
    28: _r28_missing_resolution_condition,
    29: _r29_dds_chain_without_prefab_handoff,
    30: _r30_empty_deterministic_seed,
    31: _r31_available_after_condition_needs_world_truth,
}

# Rule numbers a fixture may additionally report because the second rule is logically implied by
# the first. Every mutation in `MUTATIONS` is currently isolated enough that this table is empty;
# a new fixture that needs an entry must state the implication here rather than widen the check.
ALSO_ALLOWED: dict[int, frozenset[int]] = {}


def _rule_numbers(violations: list[str]) -> set[int]:
    numbers: set[int] = set()
    for violation in violations:
        match = RULE_RE.search(violation)
        assert match is not None, f"violation does not start with R<nn>: {violation!r}"
        numbers.add(int(match.group(1)))
    return numbers


@pytest.mark.parametrize("rule_no", sorted(MUTATIONS))
def test_each_rule_has_a_failing_fixture(rule_no: int) -> None:
    document = demo_document()
    MUTATIONS[rule_no](document)

    violations = validate_scenario_document(document)

    assert violations, f"R{rule_no:02d} fixture produced no violation at all"
    for violation in violations:
        assert violation.startswith("R"), violation
    reported = _rule_numbers(violations)
    assert rule_no in reported, f"expected R{rule_no:02d} in {violations}"
    unexpected = reported - {rule_no} - ALSO_ALLOWED.get(rule_no, frozenset())
    assert not unexpected, f"R{rule_no:02d} fixture is not minimal, also reported {unexpected}"


def test_mutation_table_covers_exactly_rules_1_to_31() -> None:
    assert sorted(MUTATIONS) == list(range(1, 32))


def test_demo_scenario_has_no_violations() -> None:
    assert validate_scenario_document(demo_document()) == []


def test_validate_scenario_version_accepts_the_demo_scenario() -> None:
    version = ScenarioVersion.model_validate(demo_document())
    assert validate_scenario_version(version) is None
    assert scenario_version_violations(version) == []


def test_validate_scenario_version_raises_one_error_listing_every_violation() -> None:
    document = demo_document()
    _r05_known_disagrees_with_world(document)
    _r30_empty_deterministic_seed(document)
    version = ScenarioVersion.model_validate(document)

    with pytest.raises(ScenarioValidationError) as excinfo:
        validate_scenario_version(version)

    assert _rule_numbers(excinfo.value.violations) == {5, 30}
