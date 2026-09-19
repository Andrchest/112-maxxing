"""Tests for `app.domain.world.conditions.Condition` (HLD `10-domain-model.md` §10.11).

Every leaf and combinator parses; the closed-structure rejections (unknown key, unknown op, a
string expression, two kinds on one node) are enforced; and `model_validate(x).model_dump(
exclude_none=True, by_alias=True) == x` round-trips for one example per leaf, matching the YAML
shapes in `docs/hld/30-scenario-format.md` §30.6.1.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.world.conditions import Condition
from pydantic import ValidationError

# ---------------------------------------------------------------------------------------------
# One example dict per leaf/combinator — used both to assert parsing succeeds and, for the
# leaves, to assert the round-trip.
# ---------------------------------------------------------------------------------------------

FACT_EXAMPLE: dict[str, Any] = {
    "fact": {"fact_id": "people.total_affected", "layer": "WORLD", "op": "GT", "value": 2}
}
RESOURCE_EXAMPLE: dict[str, Any] = {
    "resource": {
        "selector": {"resource_id": "ac2"},
        "op": "ANY_IS",
        "status": "EN_ROUTE",
    }
}
STAGE_EXAMPLE: dict[str, Any] = {"stage": {"role": "DDS", "op": "REACHED", "state": "DISPATCHED"}}
SIM_TIME_EXAMPLE: dict[str, Any] = {"sim_time": {"op": "GTE", "ms": 180000}}
ACTION_EXAMPLE: dict[str, Any] = {
    "action": {
        "event_type": "HANDOFF_CREATED",
        "op": "COUNT_GTE",
        "count": 2,
        "within_ms": 60000,
    }
}

LEAF_EXAMPLES = {
    "fact": FACT_EXAMPLE,
    "resource": RESOURCE_EXAMPLE,
    "stage": STAGE_EXAMPLE,
    "sim_time": SIM_TIME_EXAMPLE,
    "action": ACTION_EXAMPLE,
}


@pytest.mark.parametrize("example", LEAF_EXAMPLES.values(), ids=LEAF_EXAMPLES.keys())
def test_each_leaf_parses(example: dict[str, Any]) -> None:
    Condition.model_validate(example)


def test_all_combinator_parses() -> None:
    Condition.model_validate({"all": [FACT_EXAMPLE, RESOURCE_EXAMPLE]})


def test_any_combinator_parses() -> None:
    Condition.model_validate({"any": [FACT_EXAMPLE, STAGE_EXAMPLE]})


def test_not_combinator_parses() -> None:
    Condition.model_validate({"not": FACT_EXAMPLE})


@pytest.mark.parametrize("example", LEAF_EXAMPLES.values(), ids=LEAF_EXAMPLES.keys())
def test_each_leaf_round_trips(example: dict[str, Any]) -> None:
    condition = Condition.model_validate(example)

    assert condition.model_dump(exclude_none=True, by_alias=True) == example


def test_nested_round_trip() -> None:
    nested = {"all": [FACT_EXAMPLE, {"any": [STAGE_EXAMPLE, {"not": SIM_TIME_EXAMPLE}]}]}

    condition = Condition.model_validate(nested)

    assert condition.model_dump(exclude_none=True, by_alias=True) == nested


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate({"fact": FACT_EXAMPLE["fact"], "bogus": 1})


def test_unknown_top_level_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate({"maybe": FACT_EXAMPLE["fact"]})


def test_unknown_op_is_rejected() -> None:
    bad = {
        "fact": {
            "fact_id": "people.total_affected",
            "layer": "WORLD",
            "op": "BOGUS_OP",
            "value": 1,
        }
    }

    with pytest.raises(ValidationError):
        Condition.model_validate(bad)


def test_string_expression_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate("fact.people.total_affected > 2")  # type: ignore[arg-type]


def test_two_kinds_at_once_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate({**FACT_EXAMPLE, **STAGE_EXAMPLE})


def test_no_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate({})


def test_resource_selector_requires_exactly_one_key() -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate(
            {
                "resource": {
                    "selector": {"resource_id": "ac2", "capability": "FIRE_SUPPRESSION"},
                    "op": "ANY_IS",
                    "status": "AVAILABLE",
                    "count": None,
                }
            }
        )
