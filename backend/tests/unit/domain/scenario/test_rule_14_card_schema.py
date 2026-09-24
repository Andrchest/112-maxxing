"""Rule 14 against the card schema of the version's own pack (I3 E3a; HLD 70 §70.2.3 R38).

A schema-1 document keeps today's behaviour (pack `legacy-r1`, card `v1` = `CARD_FIELDS`); a
schema-2 document on `v046_24-r1` is checked against `v2`: its `HANDOFF_COMPLETENESS` paths, its
`CARD_FIELD_*` paths and its prefab `card_values` — type *and* option code.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from app.domain.scenario.validation import validate_scenario_document
from app.infrastructure.reference.file_catalog import FileReferenceCatalog

from tests.fixtures.scenarios import demo_document

EXAMPLE = Path(__file__).resolve().parents[5] / "scenarios" / "examples" / "street-rubbish-fire"
CATALOG = FileReferenceCatalog().catalog()


def _example() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load((EXAMPLE / "v1.yaml").read_text(encoding="utf-8"))
    return document


def _r14(document: dict[str, Any]) -> list[str]:
    violations = validate_scenario_document(document, reference=CATALOG)
    return [violation for violation in violations if violation.startswith("R14")]


def test_the_schema_2_example_validates_against_v2() -> None:
    assert validate_scenario_document(_example(), reference=CATALOG) == []


def test_the_schema_1_demo_still_validates_against_v1() -> None:
    assert validate_scenario_document(demo_document(), reference=CATALOG) == []


def test_a_v2_path_is_unknown_to_a_schema_1_document() -> None:
    document = copy.deepcopy(demo_document())
    document["expected_response"]["prefab_handoff"]["card_values"]["incident.types"] = ["1"]
    assert _r14(document) == [
        "R14: expected_response.prefab_handoff.card_values['incident.types'] is not a "
        "CARD_FIELDS field_path"
    ]


def test_a_v1_only_path_is_unknown_to_a_v2_document() -> None:
    document = _example()
    document["expected_response"]["prefab_handoff"]["card_values"]["incident.type"] = "FIRE"
    document["scoring_rules"].append(
        {
            **copy.deepcopy(demo_document()["scoring_rules"][-1]),
            "applies_to_roles": ["DDS"],
        }
    )  # HANDOFF_COMPLETENESS naming `incident.type` among v1 paths
    violations = _r14(document)
    assert (
        "R14: expected_response.prefab_handoff.card_values['incident.type'] is not a "
        "field_path of card schema v2"
    ) in violations
    assert (
        "R14: scoring_rules['handoff_minimum_fields'] references unknown card field_path "
        "'incident.type' of card schema v2"
    ) in violations


def test_a_prefab_value_outside_the_options_is_refused() -> None:
    document = _example()
    document["expected_response"]["prefab_handoff"]["card_values"]["q.fire.where"] = ["на крыше"]
    assert _r14(document) == [
        "R14: expected_response.prefab_handoff.card_values['q.fire.where'] value ['на крыше'] "
        "is not an option of the field (card schema v2)"
    ]


def test_an_unknown_pack_is_r38s_alone() -> None:
    document = _example()
    document["reference_pack"] = "gone-r1"
    violations = validate_scenario_document(document, reference=CATALOG)
    assert any(violation.startswith("R38") for violation in violations)
    assert not any(violation.startswith("R14") for violation in violations)
