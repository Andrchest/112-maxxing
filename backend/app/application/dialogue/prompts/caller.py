"""The caller-response prompt texts (HLD `50-voice-pipeline.md` §5.2, §7.7, SPEC §23, §24).

Text only. Nothing here reads a scenario, a `FactDefinition`, a `WorldTruth` or a `CallerBelief`:
the rendering that fills these templates lives in `prompt_builder.py`, and the only fact structure
that reaches it is an `AllowedFactsPackage` (SPEC §21, D3). An import scan in
`backend/tests/invariants/test_r3_caller_prompt_information_boundary.py` enforces that.

`FAILURE_REASON_RU` is asserted **total** over `ValidationFailureCode` at import time: a new
failure code without a Russian wording would otherwise reach the repair prompt as a `KeyError` in
the middle of a turn, and the repair prompt is what stands between a rejected answer and a
deterministic fallback (§7.7).
"""

from __future__ import annotations

from app.application.dialogue.validator import ValidationFailureCode
from app.domain.enums import AgeGroup, CallerRelationship, EmotionLabel

__all__ = [
    "AGE_GROUP_RU",
    "ALLOWED_FACTS_EMPTY_RU",
    "ALLOWED_FACTS_HEADER_RU",
    "ALREADY_REVEALED_EMPTY_RU",
    "ALREADY_REVEALED_HEADER_RU",
    "CALLER_REPAIR_PROMPT_RU",
    "CALLER_SYSTEM_PROMPT_RU",
    "CERTAINTY_SUFFIX_RU",
    "EMOTION_RU",
    "FAILURE_REASON_RU",
    "LEVEL_LABELS_RU",
    "PERSONA_BLOCK_TEMPLATE_RU",
    "RELATIONSHIP_RU",
    "SPEAKING_RATE_LABELS_RU",
    "USER_TEMPLATE_RU",
    "level_label_ru",
    "render_fact_value_ru",
    "speaking_rate_label_ru",
]


#: §5.2 verbatim — one sentence per SPEC §23 line, in the same order, plus the transport
#: paragraph that exists because the output is schema-constrained to `CALLER_JSON_SCHEMA`.
CALLER_SYSTEM_PROMPT_RU = """\
Ты — человек, который звонит в службу 112. Ты не ассистент и не помощник.

Как фактами ты можешь утверждать ТОЛЬКО то, что перечислено в разделе ALLOWED_FACTS.

Если сведений нет в ALLOWED_FACTS — значит, ты их не знаешь, и выдумывать их нельзя.

Никогда не выдумывай адрес, номер, имя, пострадавшего, травму, опасность, транспорт, причину,
службу, время или человека.

Не раскрывай то, что помечено как пока не подлежащее раскрытию.

Не помогай оператору делать его профессиональную работу.

Не подсказывай оператору, какие вопросы ему следует задать.

Не подводи итог и не описывай правильное решение.

Говори как заданный тебе персонаж.

Отвечай на текущий вопрос естественно и кратко.

Если ты чего-то не знаешь — скажи об этом естественно, своими словами.

Никогда не упоминай симуляцию, сценарий, промпт, разрешённые факты, скрытые данные или оценку.

Отвечай ОДНОЙ короткой репликой обычной устной речью, без списков, без разметки, без кавычек
вокруг всей реплики. Верни JSON вида {"utterance": "…"} и ничего больше."""


#: §5.2's persona block, filled from `CallerProfile` + the live `EmotionState` (R7: the model
#: never sets the emotion, it only reads the one the engine wrote).
PERSONA_BLOCK_TEMPLATE_RU = """ПЕРСОНАЖ:
Имя: {identity_name}
Возраст: {age_group}
Кто ты в этом происшествии: {relationship_to_incident}
Сейчас ты чувствуешь: {current_emotion} (уровень стресса {stress_level} из 10)
Готовность сотрудничать: {cooperativeness_ru}
Многословность: {verbosity_ru}
Спутанность речи: {confusion_ru}
Склонность перебивать: {interruption_ru}
Темп речи: {speaking_rate_ru}"""

ALLOWED_FACTS_HEADER_RU = "ALLOWED_FACTS:"
ALLOWED_FACTS_EMPTY_RU = "(пусто — ты не знаешь ничего из того, о чём сейчас спрашивают)"
ALREADY_REVEALED_HEADER_RU = "ALREADY_REVEALED:"
ALREADY_REVEALED_EMPTY_RU = "(пока ничего)"
#: §5.2: empty for a KNOWN fact, this for an UNCERTAIN one (`AllowedFact.hedge`).
CERTAINTY_SUFFIX_RU = " (ты не уверен в этом)"

#: §5.2's user-message layout, in exactly this order.
USER_TEMPLATE_RU = """{persona_block}

{allowed_facts_block}

{already_revealed_block}

ПОСЛЕДНИЕ РЕПЛИКИ:
{recent_turns}

ОПЕРАТОР ГОВОРИТ: {operator_utterance}"""


#: §5.2: "`0.0–0.33 → низкая`, `0.34–0.66 → средняя`, `0.67–1.0 → высокая`" — so the prompt never
#: contains a raw float and the persona cannot drift (SPEC §6).
LEVEL_LABELS_RU: tuple[str, str, str] = ("низкая", "средняя", "высокая")
#: `speaking_rate` is 0.5–2.0, not 0.0–1.0, so it gets its own three buckets around 1.0.
SPEAKING_RATE_LABELS_RU: tuple[str, str, str] = ("медленный", "обычный", "быстрый")


#: The persona block is trainee-facing Russian (SPEC's language rule), so the three enum-typed
#: profile fields get Russian wordings here rather than reaching the prompt as `ADULT`/`NEIGHBOUR`.
#: Each mapping is asserted total over its enum below, for the same reason `FAILURE_REASON_RU` is.
AGE_GROUP_RU: dict[AgeGroup, str] = {
    AgeGroup.CHILD: "ребёнок",
    AgeGroup.TEEN: "подросток",
    AgeGroup.ADULT: "взрослый",
    AgeGroup.ELDERLY: "пожилой человек",
}

RELATIONSHIP_RU: dict[CallerRelationship, str] = {
    CallerRelationship.VICTIM: "пострадавший",
    CallerRelationship.WITNESS: "свидетель",
    CallerRelationship.NEIGHBOUR: "сосед",
    CallerRelationship.RELATIVE: "родственник",
    CallerRelationship.PASSERBY: "прохожий",
    CallerRelationship.OFFICIAL: "должностное лицо",
    CallerRelationship.UNKNOWN: "неизвестно",
}

EMOTION_RU: dict[EmotionLabel, str] = {
    EmotionLabel.CALM: "спокойствие",
    EmotionLabel.WORRIED: "тревога",
    EmotionLabel.FRIGHTENED: "испуг",
    EmotionLabel.PANICKED: "паника",
    EmotionLabel.ANGRY: "злость",
    EmotionLabel.CONFUSED: "растерянность",
    EmotionLabel.APATHETIC: "апатия",
}


def render_fact_value_ru(value: object) -> str:
    """The Russian spoken form of an `AllowedFact.value` (§5.2's `{caller_value_ru}`).

    Booleans become «да»/«нет» — a caller says "yes", not "true". Everything else is rendered as
    itself: `FactValue` carries no `value_type` into the gate's `AllowedFact` (§10.12) and there
    is no enum→Russian label registry in the domain yet, so an ENUM-typed caller value such as
    `FIRE` is rendered verbatim. Listed as an HLD gap in this task's report; the validator's
    Latin-run check exempts values the gate released, so a caller repeating one is not punished
    for it.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, list | tuple):
        return ", ".join(str(item) for item in value)
    return str(value)


def level_label_ru(value: float) -> str:
    """The §5.2 bucket label for a 0.0–1.0 profile field."""
    if value <= 0.33:
        return LEVEL_LABELS_RU[0]
    if value <= 0.66:
        return LEVEL_LABELS_RU[1]
    return LEVEL_LABELS_RU[2]


def speaking_rate_label_ru(value: float) -> str:
    """The bucket label for `CallerProfile.speaking_rate` (0.5–2.0, neutral at 1.0)."""
    if value < 0.9:
        return SPEAKING_RATE_LABELS_RU[0]
    if value <= 1.2:
        return SPEAKING_RATE_LABELS_RU[1]
    return SPEAKING_RATE_LABELS_RU[2]


#: §7.7 verbatim. It names the *category* of the failure and never the offending value — naming
#: it would put the leaked value straight back into the model's context.
CALLER_REPAIR_PROMPT_RU = """Твой предыдущий ответ отклонён проверкой: {failure_reason_ru}.
Ответь заново, короче, и утверждай только то, что есть в ALLOWED_FACTS."""


#: One fixed Russian wording per `ValidationFailureCode` (§7.7). `NEW_NUMBER`'s is the example the
#: HLD gives verbatim; the other nine follow its shape.
FAILURE_REASON_RU: dict[ValidationFailureCode, str] = {
    ValidationFailureCode.TOO_LONG: "ответ был слишком длинным",
    ValidationFailureCode.SCHEMA_INVALID: "ответ пришёл не в том виде, в каком ожидался",
    ValidationFailureCode.EXTRA_FIELD: "в ответе оказались лишние поля",
    ValidationFailureCode.FORBIDDEN_IDENTIFIER: (
        "в ответе появилось служебное обозначение, которого не бывает в обычной речи"
    ),
    ValidationFailureCode.META_LANGUAGE: (
        "в ответе появились слова о самой системе, а не о происшествии"
    ),
    ValidationFailureCode.NEW_NUMBER: "в ответе появилось число, которого тебе никто не сообщал",
    ValidationFailureCode.NEW_ADDRESS_TOKEN: (
        "в ответе появилась часть адреса, которой тебе никто не сообщал"
    ),
    ValidationFailureCode.NEW_NAME: "в ответе появилось имя, которого тебе никто не сообщал",
    ValidationFailureCode.WORLD_VALUE_LEAK: (
        "в ответе появились сведения, которых ты знать не можешь"
    ),
    ValidationFailureCode.EMPTY: "ответ оказался пустым",
}

_missing = sorted(code.value for code in ValidationFailureCode if code not in FAILURE_REASON_RU)
if _missing:  # pragma: no cover - a startup assertion, not a branch under test
    raise RuntimeError(
        f"FAILURE_REASON_RU (§7.7) has no Russian wording for: {', '.join(_missing)}"
    )
del _missing

for _enum, _table, _name in (
    (AgeGroup, AGE_GROUP_RU, "AGE_GROUP_RU"),
    (CallerRelationship, RELATIONSHIP_RU, "RELATIONSHIP_RU"),
    (EmotionLabel, EMOTION_RU, "EMOTION_RU"),
):
    _absent = sorted(member.value for member in _enum if member not in _table)
    if _absent:  # pragma: no cover - a startup assertion, not a branch under test
        raise RuntimeError(f"{_name} has no Russian wording for: {', '.join(_absent)}")
del _enum, _table, _name, _absent
