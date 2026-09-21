"""`META_LEXICON_RU`, `META_LEXICON_EN`, `LATIN_ALLOWLIST` (HLD `50-voice-pipeline.md` §7.4).

Fixed word lists, copied from §7.4. Data only: the matching is `validator.py`'s job.

Single-word entries match a whole normalised token; multi-word entries match a contiguous run of
normalised tokens. The three `помощник`/`ассистент` self-references are listed as the phrases §7.4
gives, not as bare words, because «помощник» is an ordinary Russian noun a caller may legitimately
use about a person.
"""

from __future__ import annotations

__all__ = ["LATIN_ALLOWLIST", "META_LEXICON_EN", "META_LEXICON_RU", "META_MIN_LATIN_RUN"]

#: §7.4 RU, verbatim (`ё` is folded to `е` by §7.2 before matching, so the entries are too).
META_LEXICON_RU: tuple[str, ...] = (
    "симуляция",
    "симулятор",
    "сценарий",
    "сценария",
    "промпт",
    "подсказка системы",
    "модель",
    "нейросеть",
    "языковая модель",
    "я ассистент",
    "как помощник",
    "я - ассистент",
    "искусственный интеллект",
    "ии",
    "контекст",
    "инструкция",
    "разрешенные факты",
    "скрытые данные",
    "оценка",
    "баллы",
    "тренажер",
    "упражнение",
    "тест",
    "система оценивания",
    "разработчик",
    "настройки",
    "правила выше",
    "в моем распоряжении",
)

#: §7.4 EN, verbatim.
META_LEXICON_EN: tuple[str, ...] = (
    "simulation",
    "scenario",
    "prompt",
    "system prompt",
    "model",
    "language model",
    "llm",
    "assistant",
    "ai",
    "context",
    "instruction",
    "allowed facts",
    "hidden",
    "scoring",
    "score",
    "token",
    "roleplay",
    "as an ai",
    "i cannot",
    "i m sorry but",
)

#: §7.4: "Any Latin-script run of ≥ 3 letters that is not in a small `LATIN_ALLOWLIST` … also
#: raises `META_LANGUAGE`". These are the §7.4 examples; the validator additionally exempts any
#: Latin token that is part of this turn's permitted value set, because a value the Fact Access
#: Gate released is by construction something the caller may say (see `validator.py`'s HLD-gap
#: note — the HLD's allowlist predates enum-typed caller values such as `FIRE`).
LATIN_ALLOWLIST: frozenset[str] = frozenset(
    {
        "sms",
        "vin",
        "gps",
        "bmw",
        "kia",
        "vaz",
        "lada",
        "ford",
        "audi",
        "mazda",
        "opel",
        "skoda",
        "toyota",
        "renault",
        "hyundai",
        "nissan",
        "volkswagen",
    }
)

#: §7.4's threshold for the Latin-run rule.
META_MIN_LATIN_RUN = 3
