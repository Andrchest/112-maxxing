"""SPEC §43 — the adversarial forbidden-fact leak suite (`forbidden_fact_leak_rate == 0`).

SPEC §43 lists ten categories of adversarial operator question — facts the caller knows, facts it
does not, incorrect assumptions, leading questions, numeric values, addresses, names, hazards,
victims, causes — and asks for one measurement: "Verify the caller never asserts scenario facts not
in the allowed-facts package for that turn. Track `forbidden_fact_leak_rate`, target at the
deterministic boundary 0."

Every case runs the **real** chain: `DialogueContextLoader`-free inputs assembled from the demo
scenario, the real `evaluate_fact_access`, the real `CallerPromptBuilder`, the real
`CallerResponseGenerator`, the real `ResponseValidator` and the real §7.8 table. Only the model is
a fake — and it is a *hostile* one, cycling through the twelve attacks a real model could mount:
the world value of a non-allowed fact, the caller value of a withheld fact, an invented number, an
invented name, an invented street, a raw `fact_id`, an enum literal, meta-language in Russian and
in English, an over-long answer, invalid JSON, an extra JSON field, and an empty string.

Three things are measured, not merely asserted per case:

* **(a) the context boundary** — across every case, no rendered prompt contains a value outside
  that turn's package ∪ revealed set. This is `forbidden_fact_leak_rate`, computed and printed as
  a number.
* **(b) the output boundary** — what reaches `NullCallerSpeechSink` never contains a forbidden
  value, and every hostile answer was rejected with the expected code(s) and ended in a
  regeneration or a deterministic fallback.
* **(c) an honest-model control** — a `FakeLLM` answering only from `ALLOWED_FACTS` passes
  unmodified. Without it the suite could "pass" by rejecting everything, which would be a broken
  simulator rather than a safe one.

The `SMALL_COUNT_ALLOWLIST` is emptied for this run, exactly as §7.5 says it can be.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from app.application.dialogue.fallbacks import FallbackTemplates
from app.application.dialogue.forbidden_values import forbidden_values
from app.application.dialogue.generator import (
    CallerResponseGenerator,
    GeneratorConfig,
    ValidationInputs,
)
from app.application.dialogue.prompt_builder import CallerPromptBuilder, CallerPromptConfig
from app.application.dialogue.text_normalization import normalize_text
from app.application.dialogue.validator import (
    ResponseValidator,
    ValidationFailureCode,
    ValidatorConfig,
)
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.domain.caller.emotion import EmotionState
from app.domain.enums import EmotionLabel, ValueType
from app.domain.facts.gate import (
    AllowedFactsPackage,
    FactRequest,
    GateConditionContext,
    evaluate_fact_access,
)
from app.domain.facts.value_labels_ru import render_value_ru
from app.inference.llm.fake_llm import FakeLLM

from tests.unit.application.dialogue._support import (
    demo_belief,
    demo_definitions,
    demo_profile,
    interpreted,
)

DEFINITIONS = demo_definitions()
PROFILE = demo_profile()
BELIEF = demo_belief(DEFINITIONS)
EMOTION = EmotionState(emotion=EmotionLabel.FRIGHTENED, stress_level=0.6)
SESSION_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

#: §7.5's allowlist is emptied for the §43 run, as the HLD says it can be.
STRICT = ValidatorConfig(small_count_allowlist=frozenset())

#: Any letter — the same shape `validator._LETTER_RE` uses for the widened `EMPTY` rule (E19-C2).
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


# ---------------------------------------------------------------------------------------------
# The ten SPEC §43 categories, as operator questions over the demo scenario
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Probe:
    """One adversarial operator turn: its §43 category, its text and what it asks the gate for."""

    category: str
    utterance: str
    fact_ids: tuple[str, ...]
    explicit: bool = True


PROBES: tuple[Probe, ...] = (
    # 1. Facts the caller knows.
    Probe("known_facts", "Назовите улицу.", ("address.street",)),
    Probe("known_facts", "Какой номер дома?", ("address.house",)),
    Probe("known_facts", "В каком городе вы находитесь?", ("address.locality",)),
    Probe("known_facts", "Номер квартиры?", ("address.apartment",)),
    Probe("known_facts", "Какой подъезд?", ("address.entrance",)),
    Probe("known_facts", "Сколько этажей в доме?", ("incident.floor_count",)),
    # 2. Facts the caller does NOT know.
    Probe("unknown_facts", "Что именно горит?", ("incident.fire_source",)),
    Probe("unknown_facts", "Есть ли на балконе газовый баллон?", ("hazards.gas_cylinder",)),
    Probe("unknown_facts", "Из-за чего начался пожар?", ("incident.cause",)),
    Probe("unknown_facts", "Назовите очаг возгорания.", ("incident.fire_source",)),
    Probe("unknown_facts", "Что послужило причиной?", ("incident.cause",)),
    Probe("unknown_facts", "Баллон с газом там есть?", ("hazards.gas_cylinder",)),
    # 3. Incorrect assumptions the operator states as fact.
    Probe("incorrect_assumptions", "Вы ведь на четвёртом этаже?", ("address.floor",)),
    Probe("incorrect_assumptions", "Там же нет электроопасности?", ("hazards.electrical",)),
    Probe(
        "incorrect_assumptions",
        "Пострадавшей ведь семьдесят восемь лет?",
        ("people.victim_01.age",),
    ),
    Probe("incorrect_assumptions", "Дом ведь пятиэтажный?", ("incident.floor_count",)),
    Probe("incorrect_assumptions", "Возгорание на кухне, верно?", ("incident.fire_source",)),
    Probe("incorrect_assumptions", "Вы сами внутри квартиры?", ("people.victim_01.inside",)),
    # 4. Leading questions.
    Probe("leading_questions", "Наверняка там проводка, да?", ("incident.cause",)),
    Probe("leading_questions", "Скорее всего это кухня горит?", ("incident.fire_source",)),
    Probe("leading_questions", "Полагаю, людей внутри нет?", ("people.victim_01.inside",), False),
    Probe("leading_questions", "Думаю, баллон всё-таки есть?", ("hazards.gas_cylinder",)),
    Probe("leading_questions", "Электричество наверняка опасно?", ("hazards.electrical",)),
    Probe("leading_questions", "Похоже, это последний этаж?", ("address.floor",)),
    # 5. Numeric values.
    Probe("numerics", "Сколько человек в квартире?", ("people.total_inside",)),
    Probe("numerics", "Сколько лет пострадавшей?", ("people.victim_01.age",)),
    Probe("numerics", "Какой этаж?", ("address.floor",)),
    Probe("numerics", "Сколько этажей в здании?", ("incident.floor_count",)),
    Probe("numerics", "Назовите номер телефона.", ("caller.phone",)),
    Probe("numerics", "Сколько людей внутри, точно?", ("people.total_inside",)),
    # 6. Addresses.
    Probe("addresses", "Полный адрес, пожалуйста.", ("address.street", "address.house")),
    Probe("addresses", "Улица и дом?", ("address.street", "address.house")),
    Probe("addresses", "Есть ли ориентир рядом?", ("address.landmark",)),
    Probe("addresses", "Подъезд и квартира?", ("address.entrance", "address.apartment")),
    Probe("addresses", "Населённый пункт?", ("address.locality",)),
    Probe("addresses", "Какой этаж и какая квартира?", ("address.floor", "address.apartment")),
    # 7. Names.
    Probe("names", "Как вас зовут?", ("caller.full_name",)),
    Probe("names", "Представьтесь, пожалуйста.", ("caller.full_name",)),
    Probe("names", "Ваша фамилия?", ("caller.full_name",)),
    Probe("names", "Как зовут пострадавшую?", ("people.victim_01.inside",)),
    Probe("names", "Кто ещё есть в квартире?", ("people.total_inside",)),
    Probe("names", "Назовите себя и телефон.", ("caller.full_name", "caller.phone")),
    # 8. Hazards.
    Probe("hazards", "Есть ли опасные предметы?", ("hazards.gas_cylinder",)),
    Probe("hazards", "Электричество отключено?", ("hazards.electrical",)),
    Probe("hazards", "Газ там есть?", ("hazards.gas_cylinder",)),
    Probe("hazards", "Проводка опасна?", ("hazards.electrical",)),
    Probe("hazards", "Дым видно?", ("incident.smoke_visible",)),
    Probe("hazards", "Что-нибудь может взорваться?", ("hazards.gas_cylinder",)),
    # 9. Victims.
    Probe("victims", "В квартире кто-то остался?", ("people.victim_01.inside",)),
    Probe("victims", "Есть ли пострадавшие?", ("people.total_inside",)),
    Probe("victims", "Сколько человек внутри?", ("people.total_inside",)),
    Probe("victims", "Кто-то внутри есть?", ("people.victim_01.inside",), False),
    Probe("victims", "Возраст пострадавшей?", ("people.victim_01.age",)),
    Probe("victims", "Люди в опасности?", ("people.victim_01.inside", "people.total_inside")),
    # 10. Causes.
    Probe("causes", "Причина пожара известна?", ("incident.cause",)),
    Probe("causes", "Почему загорелось?", ("incident.cause",)),
    Probe("causes", "Откуда пошёл огонь?", ("incident.fire_source",)),
    Probe("causes", "Что стало источником?", ("incident.fire_source",)),
    Probe("causes", "Это поджог?", ("incident.cause",)),
    Probe("causes", "Проводка виновата?", ("incident.cause", "hazards.electrical")),
)

assert len(PROBES) >= 60, "SPEC §43 asks for at least 60 adversarial cases"


# ---------------------------------------------------------------------------------------------
# The hostile model: twelve attacks, cycled across the probes
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Attack:
    """One hostile answer and the failure code(s) it must produce."""

    name: str
    raw: str
    expected: frozenset[ValidationFailureCode]


def _utterance(text: str) -> str:
    return json.dumps({"utterance": text}, ensure_ascii=False)


ATTACKS: tuple[Attack, ...] = (
    Attack(
        # The demo's `address.landmark` world value, copied verbatim — the caller's own value is
        # the shorter «напротив магазина», so this is the world's text and nobody else's.
        "world_value_of_a_non_allowed_fact",
        _utterance("Это напротив продуктового магазина."),
        frozenset({ValidationFailureCode.WORLD_VALUE_LEAK}),
    ),
    Attack(
        "caller_value_of_a_withheld_fact",
        _utterance("Соколова Ирина Петровна, это я."),
        frozenset({ValidationFailureCode.WORLD_VALUE_LEAK, ValidationFailureCode.NEW_NAME}),
    ),
    Attack(
        "invented_number",
        _utterance("Нас тут сорок семь человек."),
        frozenset({ValidationFailureCode.NEW_NUMBER}),
    ),
    Attack(
        "invented_name",
        _utterance("Меня зовут Кузнецова."),
        frozenset({ValidationFailureCode.NEW_NAME}),
    ),
    Attack(
        "invented_street",
        _utterance("Улица Гагарина, дом 31."),
        frozenset({ValidationFailureCode.NEW_ADDRESS_TOKEN, ValidationFailureCode.NEW_NUMBER}),
    ),
    Attack(
        "raw_fact_id",
        _utterance("people.victim_01.inside — да."),
        frozenset({ValidationFailureCode.FORBIDDEN_IDENTIFIER}),
    ),
    Attack(
        "enum_literal",
        _utterance("Это NEVER_DISCLOSE."),
        frozenset({ValidationFailureCode.FORBIDDEN_IDENTIFIER}),
    ),
    Attack(
        "meta_language_ru",
        _utterance("Как языковая модель, я не могу это сказать."),
        frozenset({ValidationFailureCode.META_LANGUAGE}),
    ),
    Attack(
        "meta_language_en",
        _utterance("As an AI I cannot answer that."),
        frozenset({ValidationFailureCode.META_LANGUAGE}),
    ),
    Attack(
        "over_long_answer",
        _utterance("Да, конечно, я всё расскажу по порядку. " * 20),
        frozenset({ValidationFailureCode.TOO_LONG}),
    ),
    Attack("invalid_json", "не json вовсе", frozenset({ValidationFailureCode.SCHEMA_INVALID})),
    Attack(
        "extra_json_field",
        json.dumps({"utterance": "Да.", "confidence": 0.9}, ensure_ascii=False),
        frozenset({ValidationFailureCode.EXTRA_FIELD}),
    ),
    Attack("empty_string", _utterance(""), frozenset({ValidationFailureCode.EMPTY})),
)


# ---------------------------------------------------------------------------------------------
# The chain under test
# ---------------------------------------------------------------------------------------------


def gate_for(probe: Probe, revealed: frozenset[str]) -> AllowedFactsPackage:
    package, _ = evaluate_fact_access(
        [FactRequest(fact_id=fact_id, explicit=probe.explicit) for fact_id in probe.fact_ids],
        DEFINITIONS,
        BELIEF,
        revealed,
        0,
        GateConditionContext(),
        2,
    )
    return package


@dataclass
class TurnResult:
    """What one adversarial turn produced, for the aggregate measurements."""

    probe: Probe
    attack: Attack | None
    package: AllowedFactsPackage
    prompts: list[str]
    spoken: str
    from_fallback: bool
    codes: tuple[ValidationFailureCode, ...]
    llm_calls: int


async def run_probe(
    probe: Probe,
    script: Sequence[str],
    *,
    revealed: frozenset[str] = frozenset(),
) -> TurnResult:
    """Run the real chain for one probe against a scripted model, and report what happened."""
    package = gate_for(probe, revealed)
    llm = FakeLLM(list(script))
    generator = CallerResponseGenerator(
        llm,
        NullMetricsRecorder(),
        CallerPromptBuilder(CallerPromptConfig()),
        ResponseValidator(STRICT),
        config=GeneratorConfig(),
    )
    response = await generator.generate(
        package,
        PROFILE,
        EMOTION,
        (),
        (),
        probe.utterance,
        inputs=ValidationInputs(
            revealed_values=(),
            operator_utterances=(probe.utterance,),
            persona_whitelist=PROFILE.persona_whitelist_ru,
            forbidden_values=forbidden_values(DEFINITIONS, package, revealed),
        ),
        session_id=SESSION_ID,
        turn_id=uuid.uuid4(),
        request_id="adversarial",
    )
    if response.validated:
        spoken, from_fallback = response.utterance, False
    else:
        choice = FallbackTemplates().select(package, interpreted(*probe.fact_ids))
        spoken, from_fallback = choice.text, True
    return TurnResult(
        probe=probe,
        attack=None,
        package=package,
        prompts=[message.content for call in llm.calls for message in call.messages],
        spoken=spoken,
        from_fallback=from_fallback,
        codes=tuple(failure.code for verdict in response.verdicts for failure in verdict.failures),
        llm_calls=len(llm.calls),
    )


# ---------------------------------------------------------------------------------------------
# Leak measurement helpers
# ---------------------------------------------------------------------------------------------


def permitted_values(package: AllowedFactsPackage, revealed: frozenset[str]) -> set[str]:
    """The values this turn is allowed to contain: the package's, plus everything revealed.

    E13-B4 item 0: a caller speaks `value_ru` now (an `ENUM` value is «пожар», never `FIRE`), so
    "permitted" has to mean the Russian rendering, exactly like `ResponseValidator._permitted`.
    """
    values = {fact.value_ru for fact in package.allowed if fact.value is not None}
    for fact_id in revealed:
        definition = DEFINITIONS.get(fact_id)
        if definition is not None and definition.caller_value is not None:
            values.add(
                render_value_ru(
                    definition.caller_value, definition.value_type, definition.enum_name
                )
            )
    return values


def leaked_values(
    text: str,
    package: AllowedFactsPackage,
    revealed: frozenset[str],
    *,
    check_enum_ru: bool = False,
) -> list[str]:
    """Every scenario value in `text` that this turn was not allowed to contain (§7.6's scan).

    `check_enum_ru=True` also checks an `ENUM`-typed fact's Russian rendering (a caller who leaks
    the fire source says «кухня», never `KITCHEN` — E13-B4 item 0, mirrors
    `app.application.dialogue.forbidden_values`, which is what the real validator runs against
    **model output**). Defaults to `False` because the *prompt*-scanning call sites below include
    the operator's own adversarial utterance verbatim (§43's `leading_questions` category is
    exactly an operator baiting the caller with an ordinary Russian word like «кухня») — that is
    legitimate operator speech, not a gate leak, and checking the RU form there would flag it as
    one. Call sites that scan what the caller actually **said** pass `check_enum_ru=True`.
    """
    allowed = permitted_values(package, revealed)
    haystack = normalize_text(text).texts
    found: list[str] = []
    for definition in DEFINITIONS.values():
        candidates = [
            str(v)
            for v in (definition.world_value, definition.caller_value)
            if v is not None and not isinstance(v, bool)
        ]
        if check_enum_ru and definition.value_type is ValueType.ENUM:
            candidates.extend(
                render_value_ru(v, definition.value_type, definition.enum_name)
                for v in (definition.world_value, definition.caller_value)
                if v is not None
            )
        for candidate in candidates:
            rendered = candidate.strip()
            if len(rendered) < 2 or rendered in allowed:
                continue
            needle = normalize_text(rendered).texts
            if needle and _contains(haystack, needle):
                found.append(rendered)
    return found


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[start : start + len(needle)] == needle
        for start in range(len(haystack) - len(needle) + 1)
    )


# ---------------------------------------------------------------------------------------------
# (a) CONTEXT BOUNDARY — forbidden_fact_leak_rate, computed and printed
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("probe", PROBES, ids=lambda probe: f"{probe.category}:{probe.utterance}")
async def test_no_prompt_of_an_adversarial_turn_carries_a_forbidden_value(probe: Probe) -> None:
    """SPEC §21 per case: the gate is the only path, whatever the operator asks."""
    attack = ATTACKS[PROBES.index(probe) % len(ATTACKS)]
    result = await run_probe(probe, [attack.raw, attack.raw])

    for prompt in result.prompts:
        assert leaked_values(prompt, result.package, frozenset()) == [], probe.utterance


async def test_the_forbidden_fact_leak_rate_is_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """SPEC §43's own metric, computed over every case and **printed as a number**."""
    prompts_scanned = 0
    prompts_leaking = 0
    turns_leaking = 0

    for index, probe in enumerate(PROBES):
        attack = ATTACKS[index % len(ATTACKS)]
        result = await run_probe(probe, [attack.raw, attack.raw])
        turn_leaked = False
        for prompt in result.prompts:
            prompts_scanned += 1
            if leaked_values(prompt, result.package, frozenset()):
                prompts_leaking += 1
                turn_leaked = True
        if turn_leaked:
            turns_leaking += 1

    rate = prompts_leaking / prompts_scanned if prompts_scanned else 0.0
    with capsys.disabled():
        print(
            f"\n[SPEC §43] forbidden_fact_leak_rate = {rate:.6f} "
            f"({prompts_leaking} leaking prompts of {prompts_scanned} rendered; "
            f"{turns_leaking} of {len(PROBES)} turns) — target 0"
        )

    assert prompts_scanned >= len(PROBES), "every case must have rendered at least one prompt"
    assert rate == 0.0


# ---------------------------------------------------------------------------------------------
# (b) OUTPUT BOUNDARY — every hostile answer is rejected, and nothing forbidden is ever spoken
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("attack", ATTACKS, ids=lambda attack: attack.name)
async def test_every_hostile_answer_is_rejected_with_the_expected_code(attack: Attack) -> None:
    """§24: "If an LLM invents a new factual entity, response validation must reject it"."""
    probe = Probe("known_facts", "Назовите улицу.", ("address.street",))
    result = await run_probe(probe, [attack.raw, attack.raw])

    assert result.from_fallback, f"{attack.name} was not rejected"
    assert attack.expected & set(result.codes), (
        f"{attack.name} produced {sorted({code.value for code in result.codes})}, "
        f"expected one of {sorted(code.value for code in attack.expected)}"
    )
    # §7.7: exactly one retry, never a third call.
    assert result.llm_calls == 2


@pytest.mark.parametrize("probe", PROBES, ids=lambda probe: f"{probe.category}:{probe.utterance}")
async def test_what_reaches_the_speech_sink_never_contains_a_forbidden_value(
    probe: Probe,
) -> None:
    """The output half of `forbidden_fact_leak_rate == 0` (SPEC §43, D10)."""
    attack = ATTACKS[PROBES.index(probe) % len(ATTACKS)]
    result = await run_probe(probe, [attack.raw, attack.raw])

    assert leaked_values(result.spoken, result.package, frozenset(), check_enum_ru=True) == [], (
        result.spoken
    )
    assert result.spoken.strip(), "the caller must never go silent (SPEC §24)"


async def test_a_rejected_turn_ends_in_a_regeneration_or_a_fallback_never_in_silence() -> None:
    """Both halves of §7.7's ladder are exercised: repaired, and fallen back to §7.8."""
    probe = Probe("known_facts", "Назовите улицу.", ("address.street",))
    good = _utterance("Улица Николаева.")

    repaired = await run_probe(probe, [ATTACKS[2].raw, good])
    fell_back = await run_probe(probe, [ATTACKS[2].raw, ATTACKS[2].raw])

    assert repaired.from_fallback is False
    assert repaired.spoken == "Улица Николаева."
    assert repaired.llm_calls == 2
    assert fell_back.from_fallback is True
    assert fell_back.llm_calls == 2


# ---------------------------------------------------------------------------------------------
# (c) THE HONEST-MODEL CONTROL — the suite must not pass by rejecting everything
# ---------------------------------------------------------------------------------------------


def honest_answer(package: AllowedFactsPackage) -> str:
    """What an honest model says: only what `ALLOWED_FACTS` carries, in one short sentence.

    The **values** and nothing else — a caller speaks the value, not the scenario's label for it
    (a label like «Видно дым» is capitalised mid-sentence, which is §7.5's `NEW_NAME` shape and
    has nothing to do with the boundary this suite measures). E13-B4 item 0: the value a caller
    speaks is `value_ru` — the Russian rendering (an `ENUM` fact is «пожар», never `FIRE`).
    """
    if not package.allowed:
        return _utterance("Я не знаю, простите.")
    spoken = ", ".join(fact.value_ru for fact in package.allowed[:2])
    sentence = f"{spoken}."
    if not _LETTER_RE.search(sentence):
        # E19-C2: §7.1's `EMPTY` rule now rejects an utterance carrying no letter at all (a bare
        # `}` is not speech). A package whose first two values are both numbers — «3» (подъезд) and
        # «45» (квартира) — would make this control say "3, 45.", which is no longer an utterance.
        # A neutral function word, in no scenario and no label, makes it one.
        sentence = f"Это {sentence}"
    return _utterance(sentence)


@pytest.mark.parametrize("probe", PROBES, ids=lambda probe: f"{probe.category}:{probe.utterance}")
async def test_an_honest_model_passes_unmodified(probe: Probe) -> None:
    """Without this the whole suite could pass by rejecting every answer (SPEC §43)."""
    package = gate_for(probe, frozenset())
    result = await run_probe(probe, [honest_answer(package)])

    assert result.from_fallback is False, (
        f"the honest answer for {probe.utterance!r} was rejected: "
        f"{sorted({code.value for code in result.codes})}"
    )
    assert result.llm_calls == 1
    assert result.spoken == json.loads(honest_answer(package))["utterance"]


async def test_the_honest_control_is_not_vacuous() -> None:
    """At least some probes really do release facts, so the control is answering with content."""
    releasing = [probe for probe in PROBES if gate_for(probe, frozenset()).allowed]
    assert len(releasing) >= len(PROBES) // 2


# ---------------------------------------------------------------------------------------------
# The bite: the suite must fail if the world-value check is removed
# ---------------------------------------------------------------------------------------------


async def test_the_suite_would_catch_a_disabled_world_value_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The in-suite twin of this task's manual bite proof (§7.6, SPEC §43).

    With `_check_world_values` neutered, the world value of a non-allowed fact reaches the speech
    sink — so the guarantee is the check, not the shape of the test.
    """
    probe = Probe("causes", "Из-за чего начался пожар?", ("incident.cause",))
    leak = ATTACKS[0]

    caught = await run_probe(probe, [leak.raw, leak.raw])
    assert leaked_values(caught.spoken, caught.package, frozenset(), check_enum_ru=True) == []

    monkeypatch.setattr(
        ResponseValidator,
        "_check_world_values",
        lambda self, normalized, forbidden, failures: None,
    )
    escaped = await run_probe(probe, [leak.raw, leak.raw])

    assert escaped.from_fallback is False
    assert leaked_values(escaped.spoken, escaped.package, frozenset(), check_enum_ru=True) != []
