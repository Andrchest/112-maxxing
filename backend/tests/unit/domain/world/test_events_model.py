"""Tests for `app.domain.world.events` (HLD `10-domain-model.md` §10.11, `30-scenario-format.md`
§30.6.2, §30.6.3).

§30.6.3 ("The four kinds") is extracted from the markdown at test time and parsed into
`WorldEventDefinition`. It writes `effects: [ ... ]` and, once, `condition: { all: [ ... ] }`,
using YAML's own ellipsis convention for "some valid value, elided for brevity" (as opposed to
`30-scenario-format.md` §30.6.1/§30.6.4's `<angle-bracket>` type-placeholder convention — see
`test_effects_model.py`'s module docstring for why those two are *not* treated as literal example
data). `_yaml_examples.replace_elisions` turns each `[ ... ]` back into `[]` before parsing; no
field value from the doc is retyped.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.enums import WorldEventKind
from app.domain.world.events import WorldEventDefinition
from pydantic import TypeAdapter, ValidationError

from tests.unit.domain.world._yaml_examples import extract_yaml_blocks, replace_elisions

EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(WorldEventDefinition)


def _four_kinds_examples() -> list[dict[str, Any]]:
    (block,) = extract_yaml_blocks("### 30.6.3 The four kinds")
    return [replace_elisions(item) for item in block]


FOUR_KINDS_EXAMPLES = _four_kinds_examples()


def test_doc_has_exactly_the_four_kinds() -> None:
    assert {item["kind"] for item in FOUR_KINDS_EXAMPLES} == {kind.value for kind in WorldEventKind}


@pytest.mark.parametrize(
    "example",
    FOUR_KINDS_EXAMPLES,
    ids=[item["kind"] for item in FOUR_KINDS_EXAMPLES],
)
def test_each_doc_example_parses(example: dict[str, Any]) -> None:
    parsed = EVENT_ADAPTER.validate_python(example)

    assert parsed.kind.value == example["kind"]
    assert parsed.world_event_id == example["world_event_id"]


# ---------------------------------------------------------------------------------------------
# Common-field and per-kind rejection cases (§30.6.2 common keys; §30.8 items 24-25 range
# constraints).
# ---------------------------------------------------------------------------------------------

TIMED_BASE: dict[str, Any] = {
    "world_event_id": "fire_spreads",
    "kind": "TIMED",
    "title_ru": "Огонь распространяется",
    "caller_observable": True,
    "effects": [],
    "at_ms": 180000,
}

SEEDED_BASE: dict[str, Any] = {
    "world_event_id": "ac2_breakdown",
    "kind": "SEEDED_RANDOM",
    "title_ru": "Отказ техники",
    "caller_observable": False,
    "effects": [],
    "probability": 0.25,
    "check_every_ms": 30000,
    "window_start_ms": 0,
    "window_end_ms": 600000,
    "condition": None,
}

CONDITIONAL_BASE: dict[str, Any] = {
    "world_event_id": "gas_cylinder_hazard",
    "kind": "CONDITIONAL",
    "title_ru": "Газовый баллон нагревается",
    "caller_observable": False,
    "effects": [],
    "condition": {"sim_time": {"op": "GTE", "ms": 0}},
    "check_after_ms": 0,
    "cooldown_ms": 0,
}

ACTION_TRIGGERED_BASE: dict[str, Any] = {
    "world_event_id": "second_report_balcony",
    "kind": "ACTION_TRIGGERED",
    "title_ru": "Повторное сообщение",
    "caller_observable": False,
    "effects": [],
    "on_event_type": "HANDOFF_CREATED",
    "payload_match": None,
    "delay_ms": 60000,
}


def test_max_occurrences_defaults_to_one() -> None:
    parsed = EVENT_ADAPTER.validate_python(TIMED_BASE)
    assert parsed.max_occurrences == 1


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python({**TIMED_BASE, "bogus": 1})


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python({**TIMED_BASE, "kind": "NOT_A_KIND"})


def test_timed_event_negative_at_ms_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python({**TIMED_BASE, "at_ms": -1})


def test_conditional_event_negative_check_after_ms_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python({**CONDITIONAL_BASE, "check_after_ms": -1})


def test_action_triggered_event_negative_delay_ms_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python({**ACTION_TRIGGERED_BASE, "delay_ms": -1})


@pytest.mark.parametrize("probability", [-0.1, 1.1])
def test_seeded_random_out_of_range_probability_is_rejected(probability: float) -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python({**SEEDED_BASE, "probability": probability})


@pytest.mark.parametrize("probability", [0.0, 1.0])
def test_seeded_random_boundary_probability_is_accepted(probability: float) -> None:
    parsed = EVENT_ADAPTER.validate_python({**SEEDED_BASE, "probability": probability})
    assert parsed.probability == probability


def test_seeded_random_non_positive_check_every_ms_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python({**SEEDED_BASE, "check_every_ms": 0})


def test_seeded_random_window_end_not_after_start_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python(
            {**SEEDED_BASE, "window_start_ms": 1000, "window_end_ms": 1000}
        )


def test_seeded_random_window_end_none_is_accepted() -> None:
    parsed = EVENT_ADAPTER.validate_python({**SEEDED_BASE, "window_end_ms": None})
    assert parsed.window_end_ms is None
