"""Tests for `app.domain.world.effects` (HLD `10-domain-model.md` §10.11,
`30-scenario-format.md` §30.6.4).

`30-scenario-format.md` §30.6.4 ("Effect YAML shapes") is a type-shape sketch, not concrete
example data: every item uses angle-bracket placeholders (`<fact_id>`, `<KnowledgeState>`,
`<float>`, ...) or a pipe-joined placeholder (`INFO|WARNING|CRITICAL`) standing in for "a value of
this type", the same convention `10-domain-model.md` §10.11 uses and that the existing
`test_conditions_model.py` already treats as non-literal (it hand-writes its own leaf examples
rather than parsing §30.6.1, which uses the identical convention). Per the task brief's own
escape hatch ("if an HLD document is silent or self-contradictory ... pick the reading closest to
docs/SPEC.md ... list it under 'HLD gaps'"), this file:

1. still extracts the §30.6.4 block from the markdown at test time and mechanically substitutes
   each placeholder token with one concrete, correctly-typed value (`PLACEHOLDER_VALUES` below) —
   not a retyped example, just filling in what the placeholder stands for — then asserts every
   resulting item parses as the `Effect` its `kind` names;
2. additionally keeps hand-written, self-documenting parse/reject tests per effect kind, since a
   substituted placeholder value does not exercise real field semantics (e.g. `resource_id: <str>`
   never demonstrates parsing a real UUID-shaped id).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.enums import EffectKind
from app.domain.world.effects import Effect
from pydantic import TypeAdapter, ValidationError

from tests.unit.domain.world._yaml_examples import extract_yaml_blocks

EFFECT_ADAPTER: TypeAdapter[Any] = TypeAdapter(Effect)

# ---------------------------------------------------------------------------------------------
# §30.6.4 extraction: substitute the doc's placeholder tokens with one concrete, correctly-typed
# value each, then parse every item.
# ---------------------------------------------------------------------------------------------

PLACEHOLDER_VALUES: dict[str, Any] = {
    "<KnowledgeState>": "KNOWN",
    "INFO|WARNING|CRITICAL": "INFO",
    "<ResourceStatus>": "AVAILABLE",
    "<EmotionLabel|null>": "CALM",
    "<float>": 0.0,
}


def _substitute_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _substitute_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute_placeholders(item) for item in value]
    if isinstance(value, str) and value in PLACEHOLDER_VALUES:
        return PLACEHOLDER_VALUES[value]
    return value


def _effect_shape_examples() -> list[Any]:
    (block,) = extract_yaml_blocks("### 30.6.4 Effect YAML shapes")
    return block


EFFECT_SHAPE_EXAMPLES = _effect_shape_examples()


def test_doc_has_exactly_the_seven_effect_shapes() -> None:
    assert {item["kind"] for item in EFFECT_SHAPE_EXAMPLES} == {kind.value for kind in EffectKind}


@pytest.mark.parametrize(
    "example",
    EFFECT_SHAPE_EXAMPLES,
    ids=[item["kind"] for item in EFFECT_SHAPE_EXAMPLES],
)
def test_each_doc_effect_shape_parses_after_placeholder_substitution(example: Any) -> None:
    parsed = EFFECT_ADAPTER.validate_python(_substitute_placeholders(example))

    assert parsed.kind.value == example["kind"]


# ---------------------------------------------------------------------------------------------
# Hand-written concrete examples, one per kind (real field semantics; §30.6.4 has no such
# examples because it is a shape sketch, per the module docstring above).
# ---------------------------------------------------------------------------------------------

CONCRETE_EXAMPLES: dict[str, dict[str, Any]] = {
    "MUTATE_WORLD_TRUTH": {
        "kind": "MUTATE_WORLD_TRUTH",
        "changes": {"address.floor": 4},
    },
    "MUTATE_CALLER_BELIEF": {
        "kind": "MUTATE_CALLER_BELIEF",
        "changes": {
            "people.victim_01.inside": {
                "value": True,
                "knowledge": "KNOWN",
                "certainty": 1.0,
            }
        },
    },
    "CREATE_NOTIFICATION": {
        "kind": "CREATE_NOTIFICATION",
        "audience_role": "DDS",
        "severity": "WARNING",
        "title_ru": "Внимание",
        "body_ru": "Возможен взрыв газового баллона.",
    },
    "CREATE_RADIO_MESSAGE": {
        "kind": "CREATE_RADIO_MESSAGE",
        "from_callsign": "АЦ-1",
        "to_role": "DDS",
        "text_ru": "Прибыли на место.",
        "resource_id": None,
    },
    "ALTER_RESOURCE_AVAILABILITY": {
        "kind": "ALTER_RESOURCE_AVAILABILITY",
        "resource_id": "ac2",
        "new_status": "OUT_OF_SERVICE",
        "restore": False,
        "eta_multiplier": 1.0,
    },
    "TRIGGER_EVENT": {
        "kind": "TRIGGER_EVENT",
        "world_event_id": "second_report_balcony",
        "delay_ms": 60000,
    },
    "CHANGE_CALLER_EMOTION": {
        "kind": "CHANGE_CALLER_EMOTION",
        "set_emotion": "PANICKED",
        "stress_delta": 0.2,
    },
}


def test_concrete_examples_cover_every_effect_kind() -> None:
    assert set(CONCRETE_EXAMPLES) == {kind.value for kind in EffectKind}


@pytest.mark.parametrize("example", CONCRETE_EXAMPLES.values(), ids=CONCRETE_EXAMPLES.keys())
def test_each_concrete_example_parses(example: dict[str, Any]) -> None:
    parsed = EFFECT_ADAPTER.validate_python(example)

    assert parsed.kind.value == example["kind"]


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EFFECT_ADAPTER.validate_python({**CONCRETE_EXAMPLES["TRIGGER_EVENT"], "bogus": 1})


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EFFECT_ADAPTER.validate_python({**CONCRETE_EXAMPLES["TRIGGER_EVENT"], "kind": "NOT_A_KIND"})


def test_missing_kind_is_rejected() -> None:
    payload = dict(CONCRETE_EXAMPLES["TRIGGER_EVENT"])
    del payload["kind"]
    with pytest.raises(ValidationError):
        EFFECT_ADAPTER.validate_python(payload)


def test_caller_fact_change_certainty_out_of_range_is_rejected() -> None:
    bad = {
        "kind": "MUTATE_CALLER_BELIEF",
        "changes": {
            "people.victim_01.inside": {
                "value": True,
                "knowledge": "KNOWN",
                "certainty": 1.5,
            }
        },
    }
    with pytest.raises(ValidationError):
        EFFECT_ADAPTER.validate_python(bad)
