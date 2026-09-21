"""`few_shot_messages_ru` (HLD `50-voice-pipeline.md` §5.1, this task's brief CHANGE item 2)."""

from __future__ import annotations

import json

from app.application.dialogue.prompts import few_shot_messages_ru

_FULL_CATALOG = (
    ("address.street", "Улица", (), ("address",)),
    ("address.house", "Дом", (), ("address",)),
    ("people.total_inside", "Всего людей", (), ("people",)),
    ("caller.full_name", "ФИО", (), ("caller",)),
    ("incident.type", "Тип происшествия", (), ("incident",)),
)


def test_returns_between_4_and_8_role_content_pairs_and_is_deterministic() -> None:
    first = few_shot_messages_ru(_FULL_CATALOG)
    second = few_shot_messages_ru(_FULL_CATALOG)
    assert first == second
    assert 8 <= len(first) <= 16  # 4-8 examples, 2 messages (user+assistant) each
    assert len(first) % 2 == 0


def test_every_pair_is_a_user_message_then_an_assistant_message() -> None:
    pairs = few_shot_messages_ru(_FULL_CATALOG)
    for index in range(0, len(pairs), 2):
        assert pairs[index][0] == "user"
        assert pairs[index + 1][0] == "assistant"


def test_assistant_messages_are_single_line_compact_json_over_catalog_fact_ids_only() -> None:
    catalog_ids = {entry[0] for entry in _FULL_CATALOG}
    pairs = few_shot_messages_ru(_FULL_CATALOG)
    for role, content in pairs:
        if role != "assistant":
            continue
        assert "\n" not in content
        assert ": " not in content and ", " not in content  # no insignificant whitespace
        payload = json.loads(content)
        ids = (
            {f["fact_id"] for f in payload["requested_facts"]}
            | {a["fact_id"] for a in payload["operator_assertions"]}
            | set(payload["confirmation_targets"])
        )
        assert ids <= catalog_ids


def test_a_missing_category_drops_its_example_rather_than_inventing_a_fact_id() -> None:
    no_people = tuple(entry for entry in _FULL_CATALOG if "people" not in entry[3])
    pairs = few_shot_messages_ru(no_people)
    utterances = [content for role, content in pairs if role == "user"]
    assert not any("пострадавш" in u for u in utterances)


def test_catalog_independent_examples_are_present_even_with_an_empty_catalog() -> None:
    pairs = few_shot_messages_ru(())
    speech_acts = [
        json.loads(content)["speech_act"] for role, content in pairs if role == "assistant"
    ]
    assert "INSTRUCTION" in speech_acts
    assert "REASSURANCE" in speech_acts
    assert "REPEAT_REQUEST" in speech_acts


def test_no_example_contains_a_value_shaped_string_from_the_demo_scenario() -> None:
    """The same word-boundary sweep `test_interpreter.py::
    test_the_prompt_never_carries_a_demo_scenario_value` uses, applied directly to the static
    few-shot texts (independent of any one catalog)."""
    import re

    from app.domain.scenario.validation import build_fact_definitions
    from app.domain.scenario.version import ScenarioVersion

    from tests.fixtures.scenarios import demo_document

    definitions = build_fact_definitions(ScenarioVersion.model_validate(demo_document()))
    values = {
        value
        for item in definitions.values()
        for value in (item.world_value, item.caller_value)
        if isinstance(value, str) and value and len(value) >= 4
    }
    assert values

    pairs = few_shot_messages_ru(_FULL_CATALOG)
    text = "\n".join(content for _role, content in pairs)
    leaked = sorted(v for v in values if re.search(rf"(?<!\w){re.escape(v)}(?!\w)", text))
    assert not leaked
