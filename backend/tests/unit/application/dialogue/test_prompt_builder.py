"""`CallerPromptBuilder` — sections, caps, budget refusal, and the information boundary (§5.2,
§5.3, SPEC §21, §23, D3).

The last test here is the one that matters: a package with `allowed == ()` must produce a prompt
containing **no caller and no world value** of the demo scenario. That is SPEC §21's "the gate is
the only normal path" expressed as a property of the rendered text rather than of the type system,
and it is repeated over the whole scenario in the §43 adversarial suite.
"""

from __future__ import annotations

import pytest
from app.application.dialogue.interpreter import DialogueTurn
from app.application.dialogue.prompt_builder import (
    CallerPromptBuilder,
    CallerPromptConfig,
    PromptBudgetExceededError,
)
from app.application.dialogue.prompts.caller import (
    ALLOWED_FACTS_EMPTY_RU,
    ALREADY_REVEALED_EMPTY_RU,
    CALLER_SYSTEM_PROMPT_RU,
    CERTAINTY_SUFFIX_RU,
)
from app.application.dialogue.text_normalization import normalize_text
from app.domain.caller.emotion import EmotionState
from app.domain.enums import EmotionLabel
from app.domain.facts.gate import AllowedFactsPackage

from tests.unit.application.dialogue._support import (
    demo_definitions,
    demo_profile,
    gate_package,
    scenario_values,
)

EMOTION = EmotionState(emotion=EmotionLabel.FRIGHTENED, stress_level=0.6)


def build(
    package: AllowedFactsPackage,
    *,
    already_revealed: tuple = (),
    window: tuple[DialogueTurn, ...] = (),
    utterance: str = "Назовите адрес",
    config: CallerPromptConfig | None = None,
) -> str:
    """Render the prompt and return the whole conversation as one string."""
    messages = CallerPromptBuilder(config).build(
        package, demo_profile(), EMOTION, already_revealed, window, utterance
    )
    assert [message.role for message in messages] == ["system", "user"]
    assert messages[0].content == CALLER_SYSTEM_PROMPT_RU
    return "\n".join(message.content for message in messages)


# ---------------------------------------------------------------------------------------------
# §5.2's sections
# ---------------------------------------------------------------------------------------------


def test_the_user_message_has_the_documented_sections_in_order() -> None:
    package, _ = gate_package(("address.street",))
    rendered = build(package)
    positions = [
        rendered.index("ПЕРСОНАЖ:"),
        rendered.index("ALLOWED_FACTS:"),
        rendered.index("ALREADY_REVEALED:"),
        rendered.index("ПОСЛЕДНИЕ РЕПЛИКИ:"),
        rendered.index("ОПЕРАТОР ГОВОРИТ:"),
    ]
    assert positions == sorted(positions)


def test_the_block_order_already_puts_the_relatively_fixed_blocks_before_the_per_turn_ones() -> (
    None
):
    """E13-B4 item 3: checked whether the builder needed reordering for `cache_prompt` (system +
    the relatively-stable blocks first, the always-different-per-turn blocks last, the same shape
    B3 gave the interpreter's prefix). It did not — PERSONA/ALLOWED_FACTS/ALREADY_REVEALED already
    come before the turn window and the current utterance (`test_the_user_message_has_the_
    documented_sections_in_order`, above), and PERSONA/ALLOWED_FACTS/ALREADY_REVEALED are the
    blocks most likely to still be byte-identical across two consecutive turns of the same
    session (persona only changes on an emotion trigger; ALLOWED_FACTS/ALREADY_REVEALED are the
    same whenever no new fact was released this turn), while `ПОСЛЕДНИЕ РЕПЛИКИ`/`ОПЕРАТОР ГОВОРИТ`
    are, by construction, never the same twice. This test proves that positive claim directly: two
    turns with the same package/persona/emotion/revealed set but a different operator utterance
    and window share a long common prefix ending exactly where the turn-specific content starts,
    with no reordering needed in `CallerPromptBuilder`.
    """
    package, _ = gate_package(("address.street",))
    revealed = ()

    first = CallerPromptBuilder().build(
        package, demo_profile(), EMOTION, revealed, (), "Назовите улицу."
    )
    second = CallerPromptBuilder().build(
        package,
        demo_profile(),
        EMOTION,
        revealed,
        (DialogueTurn(speaker="OPERATOR", text="Назовите улицу."),),
        "А дом какой?",
    )

    assert first[0] == second[0], "the system message is always byte-identical"
    first_user, second_user = first[1].content, second[1].content
    split = first_user.index("ПОСЛЕДНИЕ РЕПЛИКИ:")
    assert first_user[:split] == second_user[:split], (
        "PERSONA/ALLOWED_FACTS/ALREADY_REVEALED must stay identical while only the turn-specific "
        "blocks (window, operator utterance) differ — this is the fixed prefix cache_prompt reuses"
    )
    assert first_user != second_user, "the turn-specific suffix must actually differ"


def test_the_persona_block_carries_no_raw_float() -> None:
    """§5.2: the numeric profile fields are rendered as `низкая`/`средняя`/`высокая`."""
    package, _ = gate_package(("address.street",))
    rendered = build(package)
    assert "0.8" not in rendered and "1.15" not in rendered
    assert "Готовность сотрудничать: высокая" in rendered
    assert "Многословность: средняя" in rendered


def test_the_persona_block_renders_the_live_emotion_in_russian() -> None:
    """R7: the model reads the emotion, it never sets one, and it never sees an enum literal."""
    package, _ = gate_package(("address.street",))
    rendered = build(package)
    assert "Сейчас ты чувствуешь: испуг (уровень стресса 6 из 10)" in rendered
    assert "FRIGHTENED" not in rendered


def test_an_allowed_fact_is_rendered_as_label_and_caller_value_without_its_id() -> None:
    """§5.2: "The `fact_id` itself is **never** rendered"."""
    package, _ = gate_package(("address.street",))
    rendered = build(package)
    assert "- Улица: улица Николаева" in rendered
    assert "address.street" not in rendered


def test_an_uncertain_fact_gets_the_certainty_suffix() -> None:
    package, _ = gate_package(("address.landmark",))
    rendered = build(package)
    assert f"- Ориентир: напротив магазина{CERTAINTY_SUFFIX_RU}" in rendered


def test_an_incorrect_belief_is_rendered_like_a_known_fact() -> None:
    """D10: the caller sincerely asserts the wrong value, with no hedge at all."""
    package, _ = gate_package(("address.floor",))
    rendered = build(package)
    assert "- Этаж: 5" in rendered
    assert CERTAINTY_SUFFIX_RU not in rendered


def test_a_boolean_caller_value_is_spoken_russian() -> None:
    package, _ = gate_package(("incident.smoke_visible",))
    rendered = build(package)
    assert "- Видно дым: да" in rendered
    assert "True" not in rendered


def test_the_empty_blocks_are_the_documented_wording() -> None:
    rendered = build(AllowedFactsPackage())
    assert ALLOWED_FACTS_EMPTY_RU in rendered
    assert ALREADY_REVEALED_EMPTY_RU in rendered


def test_already_revealed_carries_caller_values_of_earlier_packages() -> None:
    earlier, _ = gate_package(("address.street",))
    package, _ = gate_package(("address.house",))
    rendered = build(package, already_revealed=earlier.allowed)
    assert "ALREADY_REVEALED:\n- Улица: улица Николаева" in rendered


def test_the_turn_window_is_rendered_with_russian_speaker_labels() -> None:
    package, _ = gate_package(("address.street",))
    window = (
        DialogueTurn(speaker="OPERATOR", text="Что случилось?"),
        DialogueTurn(speaker="CALLER", text="Пожар!"),
    )
    rendered = build(package, window=window)
    assert "ОПЕРАТОР: Что случилось?" in rendered
    assert "ЗВОНЯЩИЙ: Пожар!" in rendered


# ---------------------------------------------------------------------------------------------
# §5.3's caps and the hard refusal
# ---------------------------------------------------------------------------------------------


def test_the_allowed_facts_block_is_capped_at_twelve_facts() -> None:
    """§5.3: "gate output is capped at 12 released facts per turn"."""
    definitions = demo_definitions()
    askable = [
        fact_id
        for fact_id, definition in definitions.items()
        if definition.caller_value is not None
    ]
    package, _ = gate_package(tuple(askable))
    assert len(package.allowed) > 12
    rendered = build(package)
    lines = [line for line in rendered.splitlines() if line.startswith("- ")]
    allowed_lines = lines[: len(package.allowed)]
    assert len([line for line in allowed_lines if line.startswith("- ")]) == 12


def test_the_window_is_shed_oldest_first_when_over_budget() -> None:
    """§5.2: "drops the oldest turns while the rendered window exceeds the budget"."""
    package, _ = gate_package(("address.street",))
    window = tuple(
        DialogueTurn(speaker="OPERATOR", text=f"Реплика номер {index} " + "а" * 400)
        for index in range(6)
    )
    rendered = build(package, window=window, config=CallerPromptConfig(prompt_token_budget=1100))
    assert "Реплика номер 0" not in rendered
    assert "Реплика номер 1" not in rendered
    assert "Реплика номер 5" in rendered
    # §5.2's floor: "never drops below 4 turns".
    assert rendered.count("ОПЕРАТОР: Реплика") == 4


def test_a_prompt_that_cannot_be_shed_into_budget_is_refused() -> None:
    """§5.3's hard refusal — never a truncated `ALLOWED_FACTS` block (R3)."""
    package, _ = gate_package(("address.street",))
    with pytest.raises(PromptBudgetExceededError):
        build(package, config=CallerPromptConfig(prompt_token_budget=10))


def test_the_operator_utterance_is_cropped_to_its_budget() -> None:
    package, _ = gate_package(("address.street",))
    rendered = build(package, utterance="я" * 5000)
    assert "я" * 601 not in rendered


def test_a_normal_turn_fits_the_documented_budget() -> None:
    """§5.3's table adds up: the demo's biggest realistic turn is inside 2700 tokens."""
    definitions = demo_definitions()
    package, _ = gate_package(tuple(definitions))
    window = tuple(
        DialogueTurn(speaker="OPERATOR", text="Назовите точный адрес, пожалуйста.")
        for _ in range(6)
    )
    build(package, already_revealed=package.allowed, window=window)


# ---------------------------------------------------------------------------------------------
# The information boundary (SPEC §21, R3)
# ---------------------------------------------------------------------------------------------


def test_an_empty_package_yields_a_prompt_with_no_scenario_value_at_all() -> None:
    """SPEC §21: with nothing allowed, nothing of the scenario may appear in the prompt."""
    definitions = demo_definitions()
    rendered = build(AllowedFactsPackage(), utterance="Что случилось?")
    haystack = normalize_text(rendered).texts

    leaked = [
        value
        for value in scenario_values(definitions)
        if _contains(haystack, normalize_text(value).texts)
    ]
    assert leaked == []


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[start : start + len(needle)] == needle
        for start in range(len(haystack) - len(needle) + 1)
    )
