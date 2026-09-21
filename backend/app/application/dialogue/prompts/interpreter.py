"""The interpreter's Russian prompt texts (HLD `50-voice-pipeline.md` §5.1, D10, SPEC §20).

**HLD gap, ruling (2) of this task's brief:** §5.1's system prompt rule 2 described the ten
`speech_act` members using a stray `OTHER` (which is not a member of the code enum
`app.domain.enums.SpeechAct`) and omitted `ANSWER`, `REASSURANCE` and `REPEAT_REQUEST`. That is a
doc bug, not a product decision — the JSON schema enum list a few lines above it in the same HLD
section already lists the correct ten. `speech_act_help_ru()` builds the rule-2 sentence from
`_SPEECH_ACT_DESCRIPTIONS_RU`, whose key set is asserted equal to `set(SpeechAct)` at import time:
the prose and the schema are two views of the one enum, not two independently maintained lists,
so a code enum that grows without this module being updated fails to import rather than silently
describing nine of ten members.

**This task (E13-B3), CHANGE items 1-2 — compact output + few-shot prefix.** The system prompt's
rule 1 now says the output must be single-line JSON with no insignificant whitespace (the GBNF
grammar in `app.application.dialogue.grammar` enforces this mechanically when
`llm_interpreter_use_grammar=true`; the prompt text is the belt-and-braces half for the
`response_format=json_schema` fallback path). `few_shot_messages_ru()` builds 6-8 RU
operator-utterance -> compact-JSON example pairs *from the catalog handed to the call* — fact ids
and categories only, never a value — dropping any example whose fact category the catalog lacks.
Everything this module renders (system prompt, few-shot pairs) is a function of the catalog alone,
never of a per-turn value, which is what lets `DialogueInterpreter` treat "system + few-shot +
catalog" as one byte-identical prefix across a session's turns (CHANGE item 3, `cache_prompt`).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.domain.enums import SpeechAct

__all__ = [
    "INTERPRETER_REPAIR_PROMPT_RU",
    "INTERPRETER_SYSTEM_PROMPT_RU",
    "INTERPRETER_USER_TEMPLATE_RU",
    "few_shot_messages_ru",
    "render_fact_catalog_ru",
    "render_turn_window_ru",
    "speech_act_help_ru",
]

#: One short RU clause per `SpeechAct` member (SPEC §20). Checked against the live enum below.
_SPEECH_ACT_DESCRIPTIONS_RU: dict[SpeechAct, str] = {
    SpeechAct.QUESTION: "оператор спрашивает",
    SpeechAct.ANSWER: "оператор отвечает на вопрос звонящего",
    SpeechAct.STATEMENT: "сообщает или инструктирует без вопроса",
    SpeechAct.CONFIRMATION: "переспрашивает или уточняет уже названное",
    SpeechAct.INSTRUCTION: "даёт указание («выйдите из здания»)",
    SpeechAct.GREETING: "приветствие",
    SpeechAct.CLOSING: "завершение разговора",
    SpeechAct.REASSURANCE: "успокаивает или подбадривает звонящего",
    SpeechAct.REPEAT_REQUEST: "просит повторить или говорит громче",
    SpeechAct.UNINTELLIGIBLE: "реплика непонятна или пуста",
}

if set(_SPEECH_ACT_DESCRIPTIONS_RU) != set(SpeechAct):
    # A member was added to (or removed from) the code enum without this prose being updated —
    # fail at import time rather than silently describing the wrong set to the LLM.
    raise RuntimeError(
        "app.application.dialogue.prompts.interpreter: _SPEECH_ACT_DESCRIPTIONS_RU does not "
        "cover exactly SpeechAct's members; update the descriptions (SPEC §20)."
    )


def speech_act_help_ru() -> str:
    """Rule 2 of `INTERPRETER_SYSTEM_PROMPT_RU`: one clause per `SpeechAct` member, enum order."""
    return "; ".join(f"{act.value} — {_SPEECH_ACT_DESCRIPTIONS_RU[act]}" for act in SpeechAct)


#: CHANGE item 1(a): a single, fully generic (no real fact id) compact-JSON example, shown once in
#: the system prompt so the *shape* is unambiguous even on the `response_format=json_schema`
#: fallback path (no grammar). Braces are doubled for `.format()`.
_COMPACT_EXAMPLE_JSON = (
    '{{"speech_act":"GREETING","requested_facts":[],"operator_assertions":[],'
    '"confirmation_targets":[],"semantic_confidence":1.0}}'
)

INTERPRETER_SYSTEM_PROMPT_RU = (
    """\
Ты — анализатор реплик оператора службы 112. Ты НЕ отвечаешь оператору и НЕ ведёшь диалог.
Твоя единственная задача — превратить реплику оператора в строгий JSON по заданной схеме.

Правила:
1. Возвращай только JSON, ОДНОЙ СТРОКОЙ, без пробелов и переносов строк между элементами
   (компактный формат — см. пример ниже). Никакого текста до или после, никаких пояснений.
2. Поле speech_act: {speech_act_help}.
3. В requested_facts указывай ТОЛЬКО fact_id из КАТАЛОГА ФАКТОВ ниже. Никаких новых
   идентификаторов не придумывай. Если подходящего факта в каталоге нет — не добавляй ничего.
4. Для каждого запрошенного факта укажи explicit:
   true  — оператор назвал этот факт прямо, своим именем или одним из его синонимов;
   false — факт подразумевается общим вопросом (например «что случилось?», «что там у вас?»).
5. operator_assertions — утверждения оператора о значении факта («значит, это дом 27»):
   fact_id из каталога и asserted_value строкой, как её произнёс оператор.
6. confirmation_targets — fact_id, которые оператор переспрашивает.
7. semantic_confidence — твоя уверенность в разборе, число от 0 до 1.
8. Не угадывай. Пустой список лучше выдуманного значения.

ПРИМЕР КОМПАКТНОГО ФОРМАТА (структура, не реальный ответ):
"""
    + _COMPACT_EXAMPLE_JSON
    + """

Далее — несколько примеров разбора (ПРИМЕРЫ), затем КАТАЛОГ ФАКТОВ этого звонка.

КАТАЛОГ ФАКТОВ:
{fact_catalog}\
"""
)

INTERPRETER_USER_TEMPLATE_RU = """\
ПОСЛЕДНИЕ РЕПЛИКИ:
{recent_turns}

РЕПЛИКА ОПЕРАТОРА:
{operator_utterance}\
"""

INTERPRETER_REPAIR_PROMPT_RU = """\
Твой предыдущий ответ не прошёл проверку схемы.

ТВОЙ ОТВЕТ:
{previous_raw_output}

ОШИБКА:
{validation_error}

Верни исправленный JSON, строго по схеме. Только JSON, без пояснений.
Не добавляй идентификаторы, которых нет в КАТАЛОГЕ ФАКТОВ.\
"""


def render_fact_catalog_ru(entries: Sequence[tuple[str, str, Sequence[str], Sequence[str]]]) -> str:
    """`{fact_catalog}` rendering (§5.1): one line per fact, values never appear.

    `entries` is `(fact_id, label_ru, aliases_ru, categories)` — a plain tuple rather than
    `FactCatalogEntry` so this prompts module carries no dependency on the domain package.
    """
    if not entries:
        return "(каталог пуст)"
    lines = []
    for fact_id, label_ru, aliases_ru, categories in entries:
        aliases = ", ".join(aliases_ru) if aliases_ru else "—"
        cats = ", ".join(categories) if categories else "—"
        lines.append(f"- {fact_id} | {label_ru} | синонимы: {aliases} | категории: {cats}")
    return "\n".join(lines)


def render_turn_window_ru(turns: Sequence[tuple[str, str]]) -> str:
    """`{recent_turns}` rendering: `ОПЕРАТОР: …` / `ЗВОНЯЩИЙ: …`, one line per turn (§5.1, §5.3).

    `turns` is `(speaker, text)` with `speaker` one of `"OPERATOR"` / `"CALLER"`.
    """
    if not turns:
        return "(реплик ещё не было)"
    prefixes = {"OPERATOR": "ОПЕРАТОР", "CALLER": "ЗВОНЯЩИЙ"}
    return "\n".join(f"{prefixes.get(speaker, speaker)}: {text}" for speaker, text in turns)


# ---------------------------------------------------------------------------------------------
# Few-shot prefix (this task's brief, CHANGE item 2) — catalog fact ids only, never a value.
# ---------------------------------------------------------------------------------------------


def _compact(payload: dict[str, Any]) -> str:
    """The same single-line, no-insignificant-whitespace shape rule 1 asks the model for."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _payload(
    *,
    speech_act: str,
    requested: Sequence[tuple[str, bool]] = (),
    assertions: Sequence[tuple[str, str]] = (),
    confirmations: Sequence[str] = (),
    confidence: float = 0.95,
) -> dict[str, Any]:
    return {
        "speech_act": speech_act,
        "requested_facts": [{"fact_id": fid, "explicit": explicit} for fid, explicit in requested],
        "operator_assertions": [
            {"fact_id": fid, "asserted_value": value} for fid, value in assertions
        ],
        "confirmation_targets": list(confirmations),
        "semantic_confidence": confidence,
    }


def _first_by_category(
    entries: Sequence[tuple[str, str, Sequence[str], Sequence[str]]],
    category: str,
    *,
    exclude: str | None = None,
) -> tuple[str, str, Sequence[str], Sequence[str]] | None:
    for entry in entries:
        fact_id, _label, _aliases, categories = entry
        if category in categories and fact_id != exclude:
            return entry
    return None


def few_shot_messages_ru(
    entries: Sequence[tuple[str, str, Sequence[str], Sequence[str]]],
) -> tuple[tuple[str, str], ...]:
    """6-8 RU operator-utterance -> compact-JSON example pairs (CHANGE item 2), deterministic in
    `entries` (the same `(fact_id, label_ru, aliases_ru, categories)` tuples
    `render_fact_catalog_ru` takes — catalog fact ids and categories only, never a caller/world
    value).

    Returns `(role, content)` pairs in presentation order (`role` is `"user"` or `"assistant"`),
    not `ChatMessage` — this module stays free of the `app.application.ports.llm` dependency, same
    as every other renderer here; `DialogueInterpreter` wraps each pair.

    A category the catalog has no entry for drops that one example rather than inventing a fact
    id; the four catalog-category examples below (address/people/caller/incident) plus the four
    catalog-independent ones (instruction/confirmation-of-an-address-fact/reassurance/repeat
    request) total at most 8, at least 4.
    """
    address = _first_by_category(entries, "address")
    address_second = _first_by_category(entries, "address", exclude=address[0]) if address else None
    people = _first_by_category(entries, "people")
    caller = _first_by_category(entries, "caller")
    incident = _first_by_category(entries, "incident")

    examples: list[tuple[str, dict[str, Any]]] = []
    if address is not None:
        examples.append(
            ("Какой у вас адрес?", _payload(speech_act="QUESTION", requested=[(address[0], True)]))
        )
    if people is not None:
        examples.append(
            (
                "Есть ли пострадавшие внутри?",
                _payload(speech_act="QUESTION", requested=[(people[0], True)]),
            )
        )
    if caller is not None:
        examples.append(
            ("Как вас зовут?", _payload(speech_act="QUESTION", requested=[(caller[0], True)]))
        )
    if incident is not None:
        examples.append(
            (
                "Что у вас случилось?",
                _payload(speech_act="QUESTION", requested=[(incident[0], False)]),
            )
        )
    examples.append(
        ("Оставайтесь на линии, не кладите трубку.", _payload(speech_act="INSTRUCTION"))
    )
    if address_second is not None:
        examples.append(
            (
                "Правильно, вы сказали дом пятнадцать?",
                _payload(
                    speech_act="CONFIRMATION",
                    assertions=[(address_second[0], "пятнадцать")],
                    confirmations=[address_second[0]],
                ),
            )
        )
    examples.append(("Не переживайте, помощь уже выехала.", _payload(speech_act="REASSURANCE")))
    examples.append(
        ("Повторите, пожалуйста, я вас не расслышал.", _payload(speech_act="REPEAT_REQUEST"))
    )

    messages: list[tuple[str, str]] = []
    for utterance, payload in examples:
        user_text = INTERPRETER_USER_TEMPLATE_RU.format(
            recent_turns=render_turn_window_ru(()), operator_utterance=utterance
        )
        messages.append(("user", user_text))
        messages.append(("assistant", _compact(payload)))
    return tuple(messages)
