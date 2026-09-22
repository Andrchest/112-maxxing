"""`ResponseValidator` — one case per `ValidationFailureCode`, plus a clean pass (§7, SPEC §24).

The validator is the deterministic boundary SPEC §24 puts between the model and the trainee's ear,
so every one of §7's ten codes gets a case that produces it and the clean case proves the whole set
can be satisfied at once. Russian normalisation is exercised through the validator rather than only
through `normalize_text`, because the property that matters is "«двадцать семь» is caught exactly
when `27` is", not "the tokenizer folds numerals".
"""

from __future__ import annotations

import json

import pytest
from app.application.dialogue.validator import (
    ResponseValidator,
    ValidationFailureCode,
    ValidatorConfig,
)
from app.domain.enums import DisclosurePolicy, KnowledgeState, ValueType
from app.domain.facts.definitions import FactDefinition
from app.domain.facts.gate import AllowedFactsPackage

from tests.unit.application.dialogue._support import demo_profile, gate_package

ADDRESS_FACTS = ("address.street", "address.house")


def validator(**overrides: object) -> ResponseValidator:
    """A validator with §7's defaults unless a case needs a different limit."""
    return ResponseValidator(ValidatorConfig(**overrides))  # type: ignore[arg-type]


def answer(text: str) -> str:
    """The raw model output for `text` — the schema-constrained `{"utterance": …}` shape."""
    return json.dumps({"utterance": text}, ensure_ascii=False)


def check(
    raw: str,
    *,
    package: AllowedFactsPackage | None = None,
    revealed_values: tuple[str, ...] = (),
    operator_utterances: tuple[str, ...] = (),
    forbidden: tuple[str, ...] = (),
    config: ValidatorConfig | None = None,
) -> tuple[ValidationFailureCode, ...]:
    """Run the validator over `raw` and return the codes it produced, in check order."""
    resolved = package if package is not None else gate_package(ADDRESS_FACTS)[0]
    verdict = ResponseValidator(config).validate(
        raw,
        package=resolved,
        revealed_values=revealed_values,
        operator_utterances=operator_utterances,
        persona_whitelist=demo_profile().persona_whitelist_ru,
        forbidden_values=forbidden,
    )
    return verdict.codes


# ---------------------------------------------------------------------------------------------
# The clean pass — without it every rejection below could be "the validator rejects everything"
# ---------------------------------------------------------------------------------------------


def test_an_answer_built_only_from_allowed_facts_passes() -> None:
    """§7: a caller repeating exactly what the gate released is a valid answer."""
    package, _ = gate_package(ADDRESS_FACTS)
    verdict = ResponseValidator().validate(
        answer("улица Николаева, дом 27."),
        package=package,
        revealed_values=(),
        operator_utterances=("Назовите адрес",),
        persona_whitelist=demo_profile().persona_whitelist_ru,
        forbidden_values=(),
    )
    assert verdict.ok, verdict.failures
    assert verdict.utterance == "улица Николаева, дом 27."


def test_a_plain_i_do_not_know_passes() -> None:
    """The commonest honest answer must not trip any check (SPEC §23's "скажи об этом")."""
    package, _ = gate_package(("incident.fire_source",))
    assert check(answer("Я не знаю, простите."), package=package) == ()


# ---------------------------------------------------------------------------------------------
# §7.1 — length, schema, extra fields, empty
# ---------------------------------------------------------------------------------------------


def test_too_long_by_characters() -> None:
    assert ValidationFailureCode.TOO_LONG in check(answer("да " * 300))


def test_too_long_by_sentences() -> None:
    """`caller_max_sentences`: SPEC §23's "ОДНОЙ короткой репликой"."""
    codes = check(answer("Да. Да. Да. Да."), config=ValidatorConfig(max_chars=400, max_sentences=3))
    assert ValidationFailureCode.TOO_LONG in codes


def test_schema_invalid_when_the_output_is_not_json() -> None:
    assert check("улица Николаева") == (ValidationFailureCode.SCHEMA_INVALID,)


def test_schema_invalid_when_the_utterance_field_is_missing() -> None:
    assert ValidationFailureCode.SCHEMA_INVALID in check(json.dumps({"reply": "да"}))


def test_extra_field_is_its_own_code() -> None:
    """§7.1: `extra="forbid"` — "no unexpected structured fields" (SPEC §24 item 3)."""
    raw = json.dumps({"utterance": "Да.", "confidence": 0.9})
    assert ValidationFailureCode.EXTRA_FIELD in check(raw)


def test_an_empty_utterance_is_empty_not_schema_invalid() -> None:
    assert check(answer("   ")) == (ValidationFailureCode.EMPTY,)


@pytest.mark.parametrize("text", ["}", "{", "}{", "...", ":", "—", "3, 45", " ) "])
def test_an_utterance_with_no_letter_is_empty_speech(text: str) -> None:
    """E19-C2: §7.1's `EMPTY` rule is "no letter after strip", not "no characters after strip".

    E19-C measured the Qwen3.5 family filling the caller grammar's `utterance` string with a bare
    `}` on 13-27 of 46 real dialogue turns (`docs/benchmarks/llm.md` §3) — and this validator
    passed every one of them through, because `"}".strip()` is truthy. A caller that "says" `}`
    is nonsense in a trainee's ear, so an answer carrying no letter at all is empty *speech*.
    `"3, 45"` is in this list on purpose: a bare numeric answer is no longer accepted either, and
    the caller must speak a word («Подъезд 3, квартира 45»).
    """
    assert check(answer(text)) == (ValidationFailureCode.EMPTY,)


@pytest.mark.parametrize("text", ["Да.", "улица Николаева, 27.", "Подъезд 3, квартира 45."])
def test_an_utterance_with_a_letter_is_not_empty(text: str) -> None:
    """The counterpart: one letter anywhere is enough for `EMPTY` not to fire (other checks may)."""
    assert ValidationFailureCode.EMPTY not in check(answer(text))


@pytest.mark.parametrize(
    "text",
    [
        "}I не знаю, где находится ваш дом, но дым действительно видно.",
        "Горит кухня.}",
        "[Звонящий] Горит кухня.",
        "<пауза> Горит кухня.",
        "`Горит кухня.`",
        "Горит кухня\\ быстрее",
    ],
)
def test_structural_characters_in_speech_are_schema_invalid(text: str) -> None:
    """E20-I: the real `make up` walk heard the DEV caller say `}I не знаю…` — every other rule
    passed it (the line does contain Cyrillic). A caller never pronounces JSON structure, markup
    or an escape; it is the output's structure leaking, i.e. §7.1's SCHEMA_INVALID."""
    assert check(answer(text)) == (ValidationFailureCode.SCHEMA_INVALID,)


@pytest.mark.parametrize("text", ["Горит кухня.", "Да, «скорая» уже едет?", "Подъезд 3, этаж 5."])
def test_ordinary_speech_punctuation_is_not_structural(text: str) -> None:
    assert ValidationFailureCode.SCHEMA_INVALID not in check(answer(text))


# ---------------------------------------------------------------------------------------------
# §7.3 — forbidden identifiers
# ---------------------------------------------------------------------------------------------


def test_a_raw_fact_id_is_a_forbidden_identifier() -> None:
    assert ValidationFailureCode.FORBIDDEN_IDENTIFIER in check(
        answer("people.victim_01.inside — да.")
    )


def test_a_domain_enum_literal_is_a_forbidden_identifier() -> None:
    assert ValidationFailureCode.FORBIDDEN_IDENTIFIER in check(
        answer("Это NEVER_DISCLOSE, простите.")
    )


def test_a_reserved_word_is_a_forbidden_identifier() -> None:
    assert ValidationFailureCode.FORBIDDEN_IDENTIFIER in check(answer("Мои ALLOWED_FACTS пусты."))


# ---------------------------------------------------------------------------------------------
# §7.4 — meta-language
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Как языковая модель, я не могу ответить.",
        "Это симуляция, а не настоящий вызов.",
        "Мой сценарий этого не предусматривает.",
    ],
)
def test_russian_meta_language_is_rejected(text: str) -> None:
    assert ValidationFailureCode.META_LANGUAGE in check(answer(text))


def test_english_refusal_boilerplate_is_rejected() -> None:
    assert ValidationFailureCode.META_LANGUAGE in check(answer("As an AI I cannot help."))


def test_a_latin_run_a_russian_caller_would_not_say_is_rejected() -> None:
    """§7.4's catch-all for refusal boilerplate the lexicon missed."""
    assert ValidationFailureCode.META_LANGUAGE in check(answer("Sorry, something happened."))


def test_a_permitted_latin_token_that_is_not_a_raw_enum_member_is_not_meta_language() -> None:
    """§7.4's Latin-run exemption still protects a genuinely permitted Latin token.

    Post E13-B4 item 0 the exemption is keyed on `value_ru` (Russian), so this case uses a
    synthetic `AllowedFactsPackage` whose released value is itself Latin (a `STRING`-typed fact,
    not an `ENUM` one) — the exemption mechanism (a Latin token already in this turn's permitted
    set) is still exercised, just not by an ENUM's raw member name any more (see the next test).
    """
    fact_id = "callback.voice_id"
    fact_def = FactDefinition(
        fact_id=fact_id,
        world_value="ECHO-7",
        value_type=ValueType.STRING,
        label_ru="Позывной",
        caller_value="ECHO-7",
        knowledge=KnowledgeState.KNOWN,
        policy=DisclosurePolicy.ON_ASK,
    )
    package, _ = gate_package([fact_id], definitions={fact_id: fact_def})
    assert ValidationFailureCode.META_LANGUAGE not in check(answer("ECHO-7."), package=package)


def test_the_raw_enum_member_the_gate_released_is_rejected_not_the_russian_label() -> None:
    """MANAGER RULING (E13-B4, HLD gap 4): `incident.type` releases «пожар», never `FIRE`.

    A hostile — or merely un-updated — model answer that still says the raw member name is
    rejected. `_ENUM_LITERALS` (§7.3) does not cover `IncidentType`, and `FIRE` is not a
    dotted/underscored identifier either, so `FORBIDDEN_IDENTIFIER` does not fire; the code that
    catches it is `META_LANGUAGE` (§7.4's Latin-run check — `FIRE` is no longer in the permitted
    set now that the permitted rendering is `value_ru` = «пожар»).
    """
    package, _ = gate_package(("incident.type",))
    codes = check(answer("Кажется, это FIRE."), package=package)
    assert ValidationFailureCode.META_LANGUAGE in codes
    assert ValidationFailureCode.FORBIDDEN_IDENTIFIER not in codes


def test_a_latin_only_answer_is_a_language_failure_not_empty_speech() -> None:
    """MANAGER RULING (E20-A, R5): §7.4 owns "the caller answered in the wrong language".

    The caller is a Russian speaker on a Russian emergency line (SPEC §23 — the caller's lines
    and the whole trainee-facing UI are Russian). An answer with letters but not one Cyrillic
    letter is a `META_LANGUAGE` failure; `EMPTY` stays "no letter at all" and must not quietly
    become a second language check.
    """
    codes = check(answer("Ok, yes."))

    assert ValidationFailureCode.META_LANGUAGE in codes
    assert ValidationFailureCode.EMPTY not in codes


@pytest.mark.parametrize("text", ["Ok, yes.", "I am at home.", "Help me please!", "No."])
def test_every_latin_only_answer_fails_7_4(text: str) -> None:
    """Including the short words the per-token Latin-run rule (>= 3 characters) never saw."""
    assert ValidationFailureCode.META_LANGUAGE in check(answer(text))


def test_a_russian_answer_that_merely_contains_a_latin_word_is_judged_token_by_token() -> None:
    """The whole-utterance rule only fires when there is NO Cyrillic letter anywhere."""
    codes = check(answer("Да, это на улице Николаева."))

    assert ValidationFailureCode.META_LANGUAGE not in codes


def test_a_latin_only_answer_made_of_permitted_values_is_still_allowed() -> None:
    """The same exemption the Latin-run rule already grants: a released value may be spoken.

    `ECHO-7` is what this turn's gate released, so an utterance that says nothing else is the
    caller repeating a permitted value, not the model switching language.
    """
    fact_id = "callback.voice_id"
    fact_def = FactDefinition(
        fact_id=fact_id,
        world_value="ECHO-7",
        value_type=ValueType.STRING,
        label_ru="Позывной",
        caller_value="ECHO-7",
        knowledge=KnowledgeState.KNOWN,
        policy=DisclosurePolicy.ON_ASK,
    )
    package, _ = gate_package([fact_id], definitions={fact_id: fact_def})

    assert ValidationFailureCode.META_LANGUAGE not in check(answer("ECHO-7."), package=package)


def test_a_numeric_only_answer_stays_empty_pending_the_owners_confirmation() -> None:
    """E19-C2's policy is UNCHANGED by R5: a bare number is still `EMPTY`, not `META_LANGUAGE`.

    It carries no letter at all, so the language rule never reaches it. Recorded here so that the
    open question — whether «27» alone should be a valid caller answer — is visible in the suite;
    `docs/hld/50-voice-pipeline.md` §7.4 states it as current policy, owner to confirm.
    """
    assert check(answer("27")) == (ValidationFailureCode.EMPTY,)


# ---------------------------------------------------------------------------------------------
# §7.5 — new entities
# ---------------------------------------------------------------------------------------------


def test_a_number_nobody_supplied_is_a_new_number() -> None:
    assert ValidationFailureCode.NEW_NUMBER in check(answer("Нас тут 47 человек."))


def test_the_same_number_spelled_out_is_caught_too() -> None:
    """§7.2 step 5 is what makes this one work: «сорок семь» folds to `47`."""
    assert ValidationFailureCode.NEW_NUMBER in check(answer("Нас тут сорок семь человек."))


def test_a_number_the_gate_released_is_not_new() -> None:
    package, _ = gate_package(ADDRESS_FACTS)
    assert ValidationFailureCode.NEW_NUMBER not in check(answer("Дом 27."), package=package)


def test_a_number_the_gate_released_is_not_new_when_spelled_out() -> None:
    package, _ = gate_package(ADDRESS_FACTS)
    assert ValidationFailureCode.NEW_NUMBER not in check(
        answer("Дом двадцать семь."), package=package
    )


def test_a_number_the_operator_said_is_permitted() -> None:
    """§7.5's "operator utterances of the last `entity_lookback_turns` turns" source."""
    package, _ = gate_package(("incident.type",))
    assert ValidationFailureCode.NEW_NUMBER not in check(
        answer("Да, 45."), package=package, operator_utterances=("Квартира 45?",)
    )


def test_emergency_numbers_are_always_permitted() -> None:
    package, _ = gate_package(("incident.type",))
    assert ValidationFailureCode.NEW_NUMBER not in check(answer("Я звоню в 112."), package=package)


def test_a_small_count_is_exempt_by_default_and_not_with_an_empty_allowlist() -> None:
    """§7.5's `SMALL_COUNT_ALLOWLIST`, which the §43 run empties."""
    package, _ = gate_package(("incident.type",))
    assert ValidationFailureCode.NEW_NUMBER not in check(answer("Тут 2."), package=package)
    strict = ValidatorConfig(small_count_allowlist=frozenset())
    assert ValidationFailureCode.NEW_NUMBER in check(
        answer("Тут 2."), package=package, config=strict
    )


def test_a_new_address_token_is_rejected() -> None:
    package, _ = gate_package(("incident.type",))
    assert ValidationFailureCode.NEW_ADDRESS_TOKEN in check(
        answer("Улица Гагарина."), package=package
    )


def test_a_house_number_nobody_gave_is_a_new_address_token() -> None:
    package, _ = gate_package(("incident.type",))
    codes = check(answer("Дом 31."), package=package)
    assert ValidationFailureCode.NEW_ADDRESS_TOKEN in codes


def test_the_released_street_is_not_a_new_address_token() -> None:
    package, _ = gate_package(ADDRESS_FACTS)
    assert ValidationFailureCode.NEW_ADDRESS_TOKEN not in check(
        answer("Улица Николаева, дом 27."), package=package
    )


def test_an_invented_name_is_rejected() -> None:
    package, _ = gate_package(("incident.type",))
    assert ValidationFailureCode.NEW_NAME in check(answer("Меня зовут Кузнецова."), package=package)


def test_a_sentence_initial_invented_name_is_still_caught() -> None:
    """§7.5's surname/given-name heuristic for the sentence-initial special case."""
    package, _ = gate_package(("incident.type",))
    assert ValidationFailureCode.NEW_NAME in check(answer("Иван тут."), package=package)


def test_the_personas_own_name_is_permitted() -> None:
    """`PERSONA_WHITELIST` — the demo persona is «Ирина Петровна Соколова»."""
    package, _ = gate_package(("incident.type",))
    assert ValidationFailureCode.NEW_NAME not in check(
        answer("Меня зовут Ирина Петровна."), package=package
    )


# ---------------------------------------------------------------------------------------------
# §7.6 — world-value leak
# ---------------------------------------------------------------------------------------------


def test_a_forbidden_value_is_a_world_value_leak() -> None:
    package, _ = gate_package(("incident.type",))
    assert ValidationFailureCode.WORLD_VALUE_LEAK in check(
        answer("Горит из-за неисправной электропроводки."),
        package=package,
        forbidden=("неисправная электропроводка", "неисправной электропроводки"),
    )


def test_a_multi_word_forbidden_value_must_match_contiguously() -> None:
    """§7.6: "appears as a contiguous subsequence of the response's token sequence"."""
    package, _ = gate_package(("incident.type",))
    assert ValidationFailureCode.WORLD_VALUE_LEAK not in check(
        answer("Улица тут тихая, а магазин закрыт."),
        package=package,
        forbidden=("напротив продуктового магазина",),
    )


# ---------------------------------------------------------------------------------------------
# Every failure is reported, not only the first
# ---------------------------------------------------------------------------------------------


def test_every_failure_is_reported_not_only_the_first() -> None:
    """§43 asserts on the set of codes, so a first-only validator would hide the leak."""
    package, _ = gate_package(("incident.type",))
    codes = check(
        answer("Как языковая модель, я скажу: улица Гагарина, дом 31, зовут меня Кузнецова."),
        package=package,
    )
    assert len(set(codes)) >= 3
