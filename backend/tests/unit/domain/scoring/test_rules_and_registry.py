"""Tests for `app.domain.scoring.rules.ScoringRule` and
`app.domain.scoring.evaluators.registry` (HLD `10-domain-model.md` §10.14, `30-scenario-format.md`
§30.7).

`30-scenario-format.md` §30.7 has two fenced yaml blocks: a generic shape template (placeholder
field values such as `rule_id: <string, unique>`, not concrete data) and "one example per
evaluator type" (ten fully concrete rules). Both are extracted from the markdown at test time;
this file keeps only the items whose `evaluator_type` names a real `EvaluatorType` member, which
selects exactly the ten concrete examples and skips the placeholder template row without
hand-retyping either block (mirrors the placeholder-vs-concrete distinction documented in
`tests/unit/domain/world/test_effects_model.py`).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.enums import EvaluatorType
from app.domain.scoring.evaluators.registry import EVALUATOR_CONFIG_MODELS, parse_rule_config
from app.domain.scoring.rules import ScoringRule
from pydantic import ValidationError

from tests.unit.domain.scoring._yaml_examples import extract_yaml_blocks

EVALUATOR_TYPE_VALUES = {member.value for member in EvaluatorType}


def _concrete_rule_examples() -> list[dict[str, Any]]:
    blocks = extract_yaml_blocks("## 30.7 `scoring_rules`")
    candidates: list[dict[str, Any]] = []
    for block in blocks:
        items = block["scoring_rules"] if isinstance(block, dict) else block
        candidates.extend(items)
    return [item for item in candidates if item.get("evaluator_type") in EVALUATOR_TYPE_VALUES]


RULE_EXAMPLES = _concrete_rule_examples()


def test_doc_has_exactly_one_example_per_evaluator_type() -> None:
    assert {item["evaluator_type"] for item in RULE_EXAMPLES} == EVALUATOR_TYPE_VALUES
    assert len(RULE_EXAMPLES) == len(EvaluatorType)


@pytest.mark.parametrize(
    "example",
    RULE_EXAMPLES,
    ids=[item["rule_id"] for item in RULE_EXAMPLES],
)
def test_each_doc_rule_parses_and_its_config_validates(example: dict[str, Any]) -> None:
    rule = ScoringRule.model_validate(example)

    config = parse_rule_config(rule)

    assert isinstance(config, EVALUATOR_CONFIG_MODELS[rule.evaluator_type])


def test_evaluator_config_models_covers_exactly_evaluator_type() -> None:
    assert frozenset(EVALUATOR_CONFIG_MODELS) == frozenset(EvaluatorType)


# ---------------------------------------------------------------------------------------------
# Hand-written rejection cases.
# ---------------------------------------------------------------------------------------------

_FACT_OBTAINED_EXAMPLE = next(
    item for item in RULE_EXAMPLES if item["evaluator_type"] == "FACT_OBTAINED"
)


def test_scoring_rule_rejects_unknown_top_level_key() -> None:
    with pytest.raises(ValidationError):
        ScoringRule.model_validate({**_FACT_OBTAINED_EXAMPLE, "bogus": 1})


def test_scoring_rule_rejects_non_positive_max_points() -> None:
    with pytest.raises(ValidationError):
        ScoringRule.model_validate({**_FACT_OBTAINED_EXAMPLE, "max_points": 0})


def test_scoring_rule_rejects_min_evidence_below_one() -> None:
    with pytest.raises(ValidationError):
        ScoringRule.model_validate({**_FACT_OBTAINED_EXAMPLE, "min_evidence": 0})


def test_scoring_rule_rejects_unknown_evaluator_type() -> None:
    with pytest.raises(ValidationError):
        ScoringRule.model_validate({**_FACT_OBTAINED_EXAMPLE, "evaluator_type": "NOT_A_TYPE"})


def test_parse_rule_config_rejects_unknown_config_key() -> None:
    rule = ScoringRule.model_validate(
        {**_FACT_OBTAINED_EXAMPLE, "config": {**_FACT_OBTAINED_EXAMPLE["config"], "bogus": 1}}
    )
    with pytest.raises(ValidationError):
        parse_rule_config(rule)


def test_parse_rule_config_rejects_config_for_the_wrong_evaluator_type() -> None:
    """A `FACT_OBTAINED`-shaped config is missing every `CARD_FIELD_PRESENT` key."""
    card_field_present_example = next(
        item for item in RULE_EXAMPLES if item["evaluator_type"] == "CARD_FIELD_PRESENT"
    )
    rule = ScoringRule.model_validate(
        {**card_field_present_example, "config": _FACT_OBTAINED_EXAMPLE["config"]}
    )
    with pytest.raises(ValidationError):
        parse_rule_config(rule)


def test_card_field_correct_requires_exactly_one_expected_source() -> None:
    card_field_correct_example = next(
        item for item in RULE_EXAMPLES if item["evaluator_type"] == "CARD_FIELD_CORRECT"
    )
    both_set = {
        **card_field_correct_example["config"],
        "expected_from_fact_id": "address.house",
        "expected_literal": "5",
    }
    rule = ScoringRule.model_validate({**card_field_correct_example, "config": both_set})
    with pytest.raises(ValidationError):
        parse_rule_config(rule)
