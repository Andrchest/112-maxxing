"""`FallbackTemplates.select` — §7.8's table, one case per row (HLD §7.8, SPEC §24).

The table is keyed by **gate outcome**, not by model output: that is what makes the fallback safe
when the model is the thing that failed. Row 2 is the only row that reveals facts, and its
`fact_ids` must list exactly the facts its text names — nothing else may ever become a
`FACTS_DELIVERED` id (D10, SPEC §42 test 10).
"""

from __future__ import annotations

from app.application.dialogue.fallback_templates_ru import (
    FALLBACK_TEMPLATES_RU,
    ROW_2_MAX_FACTS,
    FallbackRow,
)
from app.application.dialogue.fallbacks import FallbackTemplates
from app.domain.enums import SpeechAct
from app.domain.facts.gate import AllowedFactsPackage

from tests.unit.application.dialogue._support import gate_package, interpreted

TEMPLATES = FallbackTemplates()


def test_the_table_has_the_eight_documented_rows_in_order() -> None:
    assert [template.row for template in FALLBACK_TEMPLATES_RU] == list(FallbackRow)


def test_row_1_unintelligible() -> None:
    package = AllowedFactsPackage()
    choice = TEMPLATES.select(package, interpreted(speech_act=SpeechAct.UNINTELLIGIBLE))
    assert choice.template_row is FallbackRow.UNINTELLIGIBLE
    assert choice.text == "Простите, я не расслышала, повторите, пожалуйста."
    assert choice.fact_ids == ()


def test_row_1_also_covers_low_confidence() -> None:
    """§7.8 row 1's second half: `semantic_confidence < 0.3`."""
    package, _ = gate_package(("address.street",))
    choice = TEMPLATES.select(package, interpreted("address.street", confidence=0.1))
    assert choice.template_row is FallbackRow.UNINTELLIGIBLE


def test_row_2_states_the_allowed_facts_and_lists_exactly_them() -> None:
    package, _ = gate_package(("address.street", "address.house"))
    choice = TEMPLATES.select(package, interpreted("address.street", "address.house"))
    assert choice.template_row is FallbackRow.ALLOWED_FACTS
    assert choice.text == "Улица — улица Николаева, Дом — 27."
    assert choice.fact_ids == ("address.street", "address.house")


def test_row_2_caps_at_three_facts_and_reveals_only_those() -> None:
    """§7.8 row 2: "max 3 facts, the rest dropped and left unrevealed"."""
    asked = (
        "address.locality",
        "address.street",
        "address.house",
        "address.entrance",
        "address.apartment",
    )
    package, _ = gate_package(asked)
    choice = TEMPLATES.select(package, interpreted(*asked))
    assert len(choice.fact_ids) == ROW_2_MAX_FACTS
    assert choice.fact_ids == asked[:ROW_2_MAX_FACTS]
    assert "Подъезд" not in choice.text


def test_row_3_every_requested_fact_is_unknown_to_the_caller() -> None:
    package, _ = gate_package(("hazards.gas_cylinder",))
    choice = TEMPLATES.select(package, interpreted("hazards.gas_cylinder"))
    assert choice.template_row is FallbackRow.ALL_UNKNOWN
    assert choice.text == "Я не знаю, простите."
    assert choice.fact_ids == ()


def test_row_4_never_disclose() -> None:
    package, _ = gate_package(("incident.fire_source",))
    choice = TEMPLATES.select(package, interpreted("incident.fire_source"))
    assert choice.template_row is FallbackRow.WITHHELD_OR_NEVER
    assert choice.text == "Я… я не могу сейчас сказать."


def test_row_4_also_covers_a_withheld_fact() -> None:
    """§7.8 row 4's "or withheld" — `ONLY_IF_EXPLICITLY_ASKED` asked non-explicitly."""
    package, _ = gate_package(("people.victim_01.inside",), explicit=False)
    assert package.withheld_count == 1
    choice = TEMPLATES.select(package, interpreted("people.victim_01.inside", explicit=False))
    assert choice.template_row is FallbackRow.WITHHELD_OR_NEVER


def test_row_5_not_yet_available() -> None:
    """The demo's `hazards.gas_cylinder` is gated by a world event, but the caller knows nothing
    about it — so a `NOT_YET` row needs a fact the caller *does* know. Row 5 is reached through
    the gate's `NOT_YET_AVAILABLE` reason, which row 3's all-UNKNOWN test cannot produce."""
    from app.domain.enums import DisclosurePolicy, KnowledgeState, ValueType
    from app.domain.facts.definitions import AvailableAfter, FactDefinition

    definitions = {
        "later.fact": FactDefinition(
            fact_id="later.fact",
            world_value="позже",
            value_type=ValueType.STRING,
            label_ru="Позже",
            caller_value="позже",
            knowledge=KnowledgeState.KNOWN,
            certainty=1.0,
            policy=DisclosurePolicy.ON_ASK,
            available_after=AvailableAfter(sim_time_ms=60_000),
        )
    }
    package, _ = gate_package(("later.fact",), definitions=definitions, now_ms=0)
    choice = TEMPLATES.select(package, interpreted("later.fact"))
    assert choice.template_row is FallbackRow.NOT_YET
    assert choice.text == "Я пока не знаю."


def test_row_6_nothing_was_asked() -> None:
    choice = TEMPLATES.select(AllowedFactsPackage(), interpreted(speech_act=SpeechAct.GREETING))
    assert choice.template_row is FallbackRow.NOTHING_ASKED
    assert choice.text == "Да, я слушаю."


def test_row_6_covers_any_act_with_no_requested_facts_that_is_not_closing() -> None:
    """Manager ruling (2): the code `SpeechAct` has no `OTHER`, so row 6 is worded by act."""
    for act in (SpeechAct.STATEMENT, SpeechAct.REASSURANCE, SpeechAct.INSTRUCTION):
        choice = TEMPLATES.select(AllowedFactsPackage(), interpreted(speech_act=act))
        assert choice.template_row is FallbackRow.NOTHING_ASKED, act


def test_row_7_closing() -> None:
    choice = TEMPLATES.select(AllowedFactsPackage(), interpreted(speech_act=SpeechAct.CLOSING))
    assert choice.template_row is FallbackRow.CLOSING
    assert choice.text == "Хорошо. Спасибо."


def test_row_8_is_the_catch_all() -> None:
    """A fact was asked about, the gate released nothing and named no reason — row 8."""
    package = AllowedFactsPackage()
    choice = TEMPLATES.select(package, interpreted("address.street", speech_act=SpeechAct.CLOSING))
    assert choice.template_row is FallbackRow.CLOSING
    plain = TEMPLATES.select(package, interpreted("address.street"))
    assert plain.template_row is FallbackRow.OTHERWISE
    assert plain.text == "Я не знаю, что сказать."


def test_first_match_wins_over_a_later_row() -> None:
    """§7.8 is a top-down table: an UNINTELLIGIBLE turn takes row 1 even with allowed facts."""
    package, _ = gate_package(("address.street",))
    choice = TEMPLATES.select(
        package, interpreted("address.street", speech_act=SpeechAct.UNINTELLIGIBLE)
    )
    assert choice.template_row is FallbackRow.UNINTELLIGIBLE
    assert choice.fact_ids == ()


def test_only_row_2_ever_reveals_anything() -> None:
    """D10: every other row reveals nothing, so `FACTS_DELIVERED` cannot name a fact."""
    package, _ = gate_package(("address.street",))
    for act in SpeechAct:
        choice = TEMPLATES.select(AllowedFactsPackage(), interpreted(speech_act=act))
        assert choice.fact_ids == (), act
    assert TEMPLATES.select(package, interpreted("address.street")).fact_ids != ()
