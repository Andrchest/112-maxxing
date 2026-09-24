"""One failing fixture per §30.8 rule R01-R31 and I3's R32-R38, R40
(`docs/hld/30-scenario-format.md`, `docs/hld/70-i3-alignment.md` §70.2.3).

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
    VALIDATION_RULE_NUMBERS,
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


def _schema_2(document: Document, **overrides: Any) -> dict[str, Any]:
    """Turn the demo into a clean schema-2 document with an explicit `variants` key.

    The support is the demo's own (a caller *and* a prefab; the picker, which the demo's
    resources and resolution condition satisfy), the default is the product default;
    `overrides` replaces `supported.<switch>` (`supported_<switch>=`) or `default.<switch>`
    (`default_<switch>=`). Returns the `variants` mapping so a mutation can adjust it further.
    """
    variants: dict[str, Any] = {
        "supported": {
            "card_source": ["CALLER_VOICE", "GENERATED_CARD"],
            "dds_mode": ["RESOURCE_PICKER"],
            "dds_card_check": ["OFF"],
            "dds_brigade_call": ["OFF"],
        },
        "default": {
            "card_source": "GENERATED_CARD",
            "dds_mode": "RESOURCE_PICKER",
            "dds_card_check": "OFF",
            "dds_brigade_call": "OFF",
        },
    }
    for key, value in overrides.items():
        section, switch = key.split("_", 1)
        variants[section][switch] = value
    document["schema_version"] = 2
    document["variants"] = variants
    return variants


def _r32_default_outside_supported(document: Document) -> None:
    _schema_2(
        document, supported_card_source=["GENERATED_CARD"], default_card_source="CALLER_VOICE"
    )


def _r33_caller_voice_without_a_112_stage(document: Document) -> None:
    # The chain starts at DDS and the demo's prefab exists, so rule 29 holds; only the caller
    # variant has no 112 stage to talk to.
    _schema_2(document)
    document["role_chain"] = ["DDS"]


def _r34_generated_card_without_a_prefab(document: Document) -> None:
    _schema_2(document)
    del document["expected_response"]["prefab_handoff"]


def _r35_picker_without_a_resolution_condition(document: Document) -> None:
    _schema_2(document)
    del document["expected_response"]["resolution_condition"]


def _r36_memo_statuses_without_responders(document: Document) -> None:
    _schema_2(document, supported_dds_mode=["RESOURCE_PICKER", "MEMO_STATUSES"])


def _r37_unknown_service_id(document: Document) -> None:
    # A catalog id, not an enum member (D18): parsing accepts any string, R37 checks the catalog.
    document["expected_response"]["required_services"].append("NOT_A_SERVICE")


def _r38_unknown_reference_pack(document: Document) -> None:
    document["schema_version"] = 2
    document["reference_pack"] = "no-such-pack-r1"


def _r39_accept_deadline_not_before_not_completed(document: Document) -> None:
    # Both positive (the parse-time half), but the accept window is not shorter than the
    # not-completed one — the cross-field half only `validate_scenario_version` can see.
    document["schema_version"] = 2
    document["timers"] = {"accept_within_ms": 60_000, "not_completed_after_ms": 60_000}


def _r40_applies_to_variants_names_an_unknown_value(document: Document) -> None:
    _rule(document, "fact_victim_inside")["applies_to_variants"] = {"dds_mode": ["BOGUS_MODE"]}


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
    32: _r32_default_outside_supported,
    33: _r33_caller_voice_without_a_112_stage,
    34: _r34_generated_card_without_a_prefab,
    35: _r35_picker_without_a_resolution_condition,
    36: _r36_memo_statuses_without_responders,
    37: _r37_unknown_service_id,
    38: _r38_unknown_reference_pack,
    39: _r39_accept_deadline_not_before_not_completed,
    40: _r40_applies_to_variants_names_an_unknown_value,
}

# Rule numbers a fixture may additionally report because the second rule is logically implied by
# the first. A new fixture that needs an entry must state the implication here rather than widen
# the check.
ALSO_ALLOWED: dict[int, frozenset[int]] = {
    # R35's picker needs `resolution_condition`, whose absence is R28's own violation too.
    35: frozenset({28}),
}


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


def test_mutation_table_covers_exactly_the_rule_registry() -> None:
    """Every rule the validator runs has a failing fixture, and no fixture names a rule it does
    not run (R39 arrives with E4 and registers itself then, HLD 70 §70.2.3)."""
    assert sorted(MUTATIONS) == list(VALIDATION_RULE_NUMBERS)


def test_the_rule_registry_after_e4a() -> None:
    assert list(VALIDATION_RULE_NUMBERS) == [*range(1, 41)]


def test_a_schema_2_document_with_variants_loads_clean() -> None:
    document = demo_document()
    _schema_2(document)
    assert validate_scenario_document(document) == []
    version = ScenarioVersion.model_validate(document)
    assert version.variants is not None
    assert version.scenario_variants == version.variants


def test_a_schema_2_document_without_variants_derives_them_with_the_product_default() -> None:
    document = demo_document()
    document["schema_version"] = 2
    assert validate_scenario_document(document) == []
    derived = ScenarioVersion.model_validate(document).scenario_variants
    assert derived.default.card_source.value == "GENERATED_CARD"
    assert derived.default.dds_mode.value == "RESOURCE_PICKER"


def test_r01_refuses_the_variants_key_in_a_schema_1_document() -> None:
    document = demo_document()
    _schema_2(document)
    document["schema_version"] = 1
    violations = validate_scenario_document(document)
    assert _rule_numbers(violations) == {1}
    assert any("variants" in violation for violation in violations)


def test_r01_refuses_timers_in_a_schema_1_document() -> None:
    """`timers` is a schema-2 key (E4a): R01 refuses it in a schema-1 document."""
    document = demo_document()
    document["timers"] = {}
    violations = validate_scenario_document(document)
    assert _rule_numbers(violations) == {1}
    assert any("timers" in violation for violation in violations)


def test_a_schema_2_document_with_timers_loads_clean_and_resolves_the_defaults() -> None:
    """R39's happy path, and §70.3.4's defaults for every key the document leaves out."""
    document = demo_document()
    document["schema_version"] = 2
    document["timers"] = {"not_completed_after_ms": 600_000}
    assert validate_scenario_document(document) == []
    timers = ScenarioVersion.model_validate(document).card_timers
    assert (timers.accept_within_ms, timers.fill_within_ms, timers.not_completed_after_ms) == (
        30_000,
        180_000,
        600_000,
    )


def test_a_document_without_timers_gets_every_default_and_dumps_without_the_key() -> None:
    version = ScenarioVersion.model_validate(demo_document())
    assert version.card_timers.model_dump() == {
        "accept_within_ms": 30_000,
        "fill_within_ms": 180_000,
        "not_completed_after_ms": 172_800_000,
    }
    assert "timers" not in version.model_dump(mode="json")


@pytest.mark.parametrize("value", [0, -1])
def test_r39_refuses_a_timer_that_is_not_positive(value: int) -> None:
    document = demo_document()
    document["schema_version"] = 2
    document["timers"] = {"fill_within_ms": value}
    assert _rule_numbers(validate_scenario_document(document)) == {39}


def test_an_unknown_key_under_timers_is_rule_1() -> None:
    document = demo_document()
    document["schema_version"] = 2
    document["timers"] = {"answer_within_ms": 10_000}
    assert _rule_numbers(validate_scenario_document(document)) == {1}


def test_r01_refuses_the_reference_pack_key_in_a_schema_1_document() -> None:
    document = demo_document()
    document["reference_pack"] = "legacy-r1"
    violations = validate_scenario_document(document)
    assert _rule_numbers(violations) == {1}
    assert any("reference_pack" in violation for violation in violations)


def test_a_schema_2_document_naming_the_legacy_pack_loads_clean() -> None:
    document = demo_document()
    document["schema_version"] = 2
    document["reference_pack"] = "legacy-r1"
    assert validate_scenario_document(document) == []
    assert ScenarioVersion.model_validate(document).reference_pack_id == "legacy-r1"


def test_a_document_without_reference_pack_uses_legacy_r1_and_dumps_without_the_key() -> None:
    """P5: a schema-1 document's canonical dump (its identity, D4) gains no key."""
    version = ScenarioVersion.model_validate(demo_document())
    assert version.reference_pack is None
    assert version.reference_pack_id == "legacy-r1"
    assert "reference_pack" not in version.model_dump(mode="json")


def test_r37_names_every_place_a_service_id_can_hide() -> None:
    """R37 replaces the enum check everywhere the closed `ServiceType` guarded (D18)."""
    document = demo_document()
    expected = document["expected_response"]
    expected["optional_services"] = ["GHOST_OPTIONAL"]
    expected["min_units_by_service"] = {"GHOST_UNITS": 1}
    expected["prefab_handoff"]["recipient_services"] = ["GHOST_PREFAB"]
    document["available_resources"][0]["service_type"] = "GHOST_RESOURCE"
    violations = validate_scenario_document(document)
    assert _rule_numbers(violations) - {16, 17} == {37}
    for ghost in ("GHOST_OPTIONAL", "GHOST_UNITS", "GHOST_PREFAB", "GHOST_RESOURCE"):
        assert any(ghost in violation and violation.startswith("R37") for violation in violations)


def test_r37_accepts_a_catalog_service_beyond_the_six_legacy_ids() -> None:
    """With a catalog that has it, a new UPPER_SNAKE id is valid; without, it is R37."""
    from app.domain.routing.catalog import (
        DEFAULT_PACK_ID,
        LEGACY_REFERENCE,
        ReferenceCatalog,
        ReferencePack,
        ServiceCatalog,
    )

    legacy = LEGACY_REFERENCE.services(DEFAULT_PACK_ID)
    assert legacy is not None
    mosvodokanal = legacy.services[0].model_copy(update={"id": "MOSVODOKANAL"})
    reference = ReferenceCatalog(
        packs=[
            ReferencePack(pack_id="legacy-r1", card_schema="v1", services="v1", classifier=None)
        ],
        service_catalogs=[
            ServiceCatalog(catalog_id="v1", services=(*legacy.services, mosvodokanal))
        ],
    )
    document = demo_document()
    document["expected_response"]["optional_services"] = ["MOSVODOKANAL"]
    assert _rule_numbers(validate_scenario_document(document)) == {37}
    assert validate_scenario_document(document, reference=reference) == []


def test_r01_refuses_expected_response_responders_in_schema_1() -> None:
    """`expected_response.responders` is a schema-2 key (I3 E5b, R01 extended)."""
    document = demo_document()
    document["expected_response"]["responders"] = "DEFAULT"
    violations = validate_scenario_document(document)
    assert _rule_numbers(violations) == {1}
    assert any("expected_response.responders" in violation for violation in violations)


@pytest.mark.parametrize(
    "responders",
    [
        "DEFAULT",
        {
            "FIRE_RESCUE": [
                {"after_ms": 0, "status": "RECEIVED"},
                {"after_ms": 5_000, "status": "ACCEPTED", "order_number": "Н-1"},
                {"after_ms": 9_000, "status": "REFUSED", "comment_ru": "Нет расчётов"},
            ],
            "AMBULANCE": [{"after_ms": 3_000, "status": "COMPLETED"}],
            "POLICE": [{"after_ms": 1_000, "status": "NOT_ACCEPTED", "comment_ru": "Не наше"}],
        },
    ],
    ids=["DEFAULT", "per-service"],
)
def test_r36_is_satisfied_by_responders(responders: Any) -> None:
    """R36 active (I3 E5b): `MEMO_STATUSES` supported with `responders` — `DEFAULT` or a playable
    script per service (AMBULANCE's `COMPLETED` straight away is the 103 `NO_REFUSAL` shortcut)."""
    document = demo_document()
    _schema_2(document, supported_dds_mode=["RESOURCE_PICKER", "MEMO_STATUSES"])
    document["expected_response"]["responders"] = responders
    assert validate_scenario_document(document) == []


@pytest.mark.parametrize(
    ("script", "fragment"),
    [
        ([{"after_ms": 0, "status": "ARRIVED"}], "not one scripted step from ADDED"),
        (
            [{"after_ms": 0, "status": "RECEIVED"}, {"after_ms": 0, "status": "WORKING"}],
            "not one scripted step from RECEIVED",
        ),
        ([{"after_ms": 0, "status": "NOT_ACCEPTED"}], "needs a non-blank comment_ru"),
        (
            [{"after_ms": 9_000, "status": "RECEIVED"}, {"after_ms": 1_000, "status": "ACCEPTED"}],
            "earlier than the step before",
        ),
        ([], "is empty"),
    ],
    ids=["skips", "skips-later", "no-comment", "backwards", "empty"],
)
def test_r36_refuses_a_script_that_cannot_be_played(script: Any, fragment: str) -> None:
    document = demo_document()
    _schema_2(document, supported_dds_mode=["RESOURCE_PICKER", "MEMO_STATUSES"])
    document["expected_response"]["responders"] = {"FIRE_RESCUE": script}
    violations = validate_scenario_document(document)
    assert _rule_numbers(violations) == {36}
    assert any(fragment in violation for violation in violations), violations


def test_r36_applies_the_service_policy_to_a_script() -> None:
    """103 (`NO_REFUSAL`) cannot decline; a `DEFAULT` service cannot skip to «Работы завершены»."""
    document = demo_document()
    _schema_2(document, supported_dds_mode=["RESOURCE_PICKER", "MEMO_STATUSES"])
    document["expected_response"]["responders"] = {
        "AMBULANCE": [{"after_ms": 0, "status": "NOT_ACCEPTED", "comment_ru": "Нет"}],
        "FIRE_RESCUE": [{"after_ms": 0, "status": "COMPLETED"}],
    }
    violations = validate_scenario_document(document)
    assert _rule_numbers(violations) == {36}
    assert sum("policy NO_REFUSAL" in violation for violation in violations) == 1
    assert sum("policy DEFAULT" in violation for violation in violations) == 1


def test_r37_checks_the_responders_service_ids() -> None:
    document = demo_document()
    _schema_2(document, supported_dds_mode=["RESOURCE_PICKER", "MEMO_STATUSES"])
    document["expected_response"]["responders"] = {
        "NO_SUCH_SERVICE": [{"after_ms": 0, "status": "RECEIVED"}]
    }
    violations = validate_scenario_document(document)
    assert _rule_numbers(violations) == {37}
    assert any("expected_response.responders['NO_SUCH_SERVICE']" in v for v in violations)


def test_r32_reports_an_empty_and_a_duplicated_support_list() -> None:
    document = demo_document()
    _schema_2(document, supported_dds_card_check=[], supported_dds_brigade_call=["OFF", "OFF"])
    violations = validate_scenario_document(document)
    assert _rule_numbers(violations) == {32}
    assert any("dds_card_check is empty" in violation for violation in violations)
    assert any("dds_brigade_call lists 'OFF' twice" in violation for violation in violations)


def test_r40_refuses_an_unknown_switch() -> None:
    document = demo_document()
    _rule(document, "fact_victim_inside")["applies_to_variants"] = {"colour": ["RED"]}
    violations = validate_scenario_document(document)
    assert _rule_numbers(violations) == {40}


def test_a_known_applies_to_variants_passes() -> None:
    document = demo_document()
    _rule(document, "fact_victim_inside")["applies_to_variants"] = {
        "card_source": ["CALLER_VOICE"],
        "dds_mode": ["RESOURCE_PICKER", "MEMO_STATUSES"],
    }
    assert validate_scenario_document(document) == []


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
