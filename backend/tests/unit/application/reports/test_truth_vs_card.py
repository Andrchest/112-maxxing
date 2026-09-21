"""`SessionReport.truth_vs_card_diff` — the one place `WorldTruth` reaches a human (SPEC §29
item 9, D11, D3).

Two things are pinned here:

1. **the mapping is the scenario's own** (E16 R4) — the diff's rows are the demo scenario's
   `CARD_FIELD_CORRECT` rules, with their own `field_path`, `expected_from_fact_id`, `comparison`
   and `tolerance`, so a diff row can never disagree with the rule that graded the same field;
2. **the four verdicts** of `openapi.yaml`'s enum, including the two that are easy to conflate:
   an empty card field is `MISSING` (not `MISMATCH`), and a field with no truth behind it is
   `NOT_COMPARABLE` (not `MATCH`).

The scenario is the committed demo document, not an invented one.
"""

from __future__ import annotations

import pytest
from app.application.reports.truth_vs_card import truth_vs_card_diff
from app.domain.common.ids import CardId, IncidentId
from app.domain.enums import EvaluatorType
from app.domain.layers.operator_card import OperatorCard
from app.domain.layers.world_truth import WorldTruth
from app.domain.scoring.evaluators.card_field_correct import CardFieldCorrectConfig

from tests.unit.domain.session._builders import det_uuid, scenario_version

INCIDENT = IncidentId(det_uuid("incident"))
CARD = CardId(det_uuid("card"))


@pytest.fixture
def version():
    return scenario_version()


def _card(values: dict[str, object]) -> OperatorCard:
    return OperatorCard(card_id=CARD, incident_id=INCIDENT, values=dict(values))  # type: ignore[arg-type]


def _configs(version) -> dict[str, CardFieldCorrectConfig]:
    return {
        CardFieldCorrectConfig.model_validate(dict(rule.config)).field_path: (
            CardFieldCorrectConfig.model_validate(dict(rule.config))
        )
        for rule in version.scoring_rules
        if rule.evaluator_type is EvaluatorType.CARD_FIELD_CORRECT
    }


def test_the_demo_scenario_maps_at_least_one_field_to_a_fact(version) -> None:
    """Guard on the fixture: an empty mapping would make every assertion below vacuous."""
    configs = _configs(version)
    assert configs, "the demo scenario must have CARD_FIELD_CORRECT rules for this file to matter"


def test_the_diff_rows_are_exactly_the_scenario_s_card_field_correct_fields(version) -> None:
    """R4: the scenario's existing fact↔card-field mapping, not a new one."""
    entries = truth_vs_card_diff(version, None, None)
    assert [entry.field_path for entry in entries] == list(_configs(version))


def test_every_row_carries_the_russian_label_from_the_card_catalog(version) -> None:
    for entry in truth_vs_card_diff(version, None, None):
        assert entry.label_ru
        assert entry.label_ru != entry.field_path, entry.field_path


def test_an_empty_card_is_missing_everywhere_there_was_a_truth(version) -> None:
    """The sharpest case: "the operator filled nothing in" is the most important diff there is."""
    entries = truth_vs_card_diff(version, _card({}), None)
    assert {entry.verdict for entry in entries} <= {"MISSING", "NOT_COMPARABLE"}
    assert "MISSING" in {entry.verdict for entry in entries}


def test_the_right_value_matches_and_the_wrong_one_mismatches(version) -> None:
    configs = _configs(version)
    field_path, config = next(
        (path, cfg) for path, cfg in configs.items() if cfg.expected_from_fact_id is not None
    )
    truth = version.world_truth.facts[config.expected_from_fact_id].world_value

    matched = {
        entry.field_path: entry
        for entry in truth_vs_card_diff(version, _card({field_path: truth}), None)
    }[field_path]
    assert matched.verdict == "MATCH"
    assert matched.world_value == truth
    assert matched.card_value == truth
    assert matched.world_fact_id == config.expected_from_fact_id

    wrong = "совершенно другое значение" if isinstance(truth, str) else 999999
    mismatched = {
        entry.field_path: entry
        for entry in truth_vs_card_diff(version, _card({field_path: wrong}), None)
    }[field_path]
    assert mismatched.verdict == "MISMATCH"
    assert mismatched.card_value == wrong


def test_the_live_world_truth_wins_over_the_scenario_s_opening_value(version) -> None:
    """The world-event engine may mutate the truth mid-session (`WORLD_TRUTH_MUTATED`); a review
    that showed the opening value would be showing something that stopped being true."""
    configs = _configs(version)
    field_path, config = next(
        (path, cfg) for path, cfg in configs.items() if cfg.expected_from_fact_id is not None
    )
    original = version.world_truth.facts[config.expected_from_fact_id].world_value
    mutated = "изменившаяся обстановка"
    assert mutated != original
    live = WorldTruth(
        incident_id=INCIDENT, revision=3, facts={config.expected_from_fact_id: mutated}
    )

    # The card still holds what was true when the operator typed it.
    entry = {
        entry.field_path: entry
        for entry in truth_vs_card_diff(version, _card({field_path: original}), live)
    }[field_path]
    assert entry.world_value == mutated, "the live row, not the scenario's opening value"
    assert entry.card_value == original
    assert entry.verdict == "MISMATCH"


def test_a_fact_that_exists_nowhere_is_not_comparable(version) -> None:
    """Reported rather than hidden: "nothing to check here" is a fact about the scenario."""
    configs = _configs(version)
    field_path, config = next(
        (path, cfg) for path, cfg in configs.items() if cfg.expected_from_fact_id is not None
    )
    stripped = version.model_copy(
        update={
            "world_truth": version.world_truth.model_copy(
                update={
                    "facts": {
                        key: value
                        for key, value in version.world_truth.facts.items()
                        if key != config.expected_from_fact_id
                    }
                }
            )
        }
    )
    entry = {
        entry.field_path: entry
        for entry in truth_vs_card_diff(stripped, _card({field_path: "что-нибудь"}), None)
    }[field_path]
    assert entry.verdict == "NOT_COMPARABLE"
    assert entry.world_value is None


def test_the_diff_never_awards_anything(version) -> None:
    """It is a display projection (D11): the entry has no points, no `passed`, no rule id."""
    (entry, *_) = truth_vs_card_diff(version, _card({}), None)
    assert not hasattr(entry, "points_awarded")
    assert not hasattr(entry, "passed")
    assert not hasattr(entry, "rule_id")
