"""The eight deterministic fallback templates (HLD `50-voice-pipeline.md` §7.8), as **data**.

§7.8's last line: "Templates are data in `backend/app/application/dialogue/fallback_templates_ru.py`
and contain no scenario values other than the caller values passed in for row 2." That sentence is
the whole contract of this module — it holds the Russian wording and the conditions in the
document's order, and `fallbacks.py` holds the selector that reads them.

Row 6's condition carries the manager's ruling (2): the interpreter's `speech_act` enum is the code
`SpeechAct` (ten members, no `OTHER`), so §7.8's original "`GREETING`/`OTHER`" wording is replaced
by "`speech_act == GREETING` or any act with no requested facts that is not `CLOSING`".

I8 V4: gender-aware wording. Only row 1's «расслышала» actually carries a gendered past-tense
verb — every other row is gender-neutral Russian as written — but each row still names BOTH a
`text_female` and a `text_male` (identical strings where nothing differs) so a call site never has
to guess which rows need a variant and which don't; `FallbackTemplate.text_for(gender)` is the one
place that decision is made. `fallbacks.py`'s selector is handed the caller's gender (from the
scenario's logical `caller_profile.voice_id`, `gender_from_voice_id` below) and threads it through.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "FALLBACK_TEMPLATES_RU",
    "ROW_2_MAX_FACTS",
    "FallbackRow",
    "FallbackTemplate",
    "Gender",
    "gender_from_voice_id",
]

#: §7.8 row 2: "max 3 facts, the rest dropped and left unrevealed".
ROW_2_MAX_FACTS = 3

#: HLD 30 §30.3's logical `caller_profile.voice_id` names its gender in its prefix
#: (`ru_female_adult_01`, `ru_male_elderly_01`). Only two values exist in the domain today.
Gender = Literal["female", "male"]


class FallbackRow(enum.IntEnum):
    """The row numbers of §7.8's table, so a call site never writes a bare integer."""

    UNINTELLIGIBLE = 1
    ALLOWED_FACTS = 2
    ALL_UNKNOWN = 3
    WITHHELD_OR_NEVER = 4
    NOT_YET = 5
    NOTHING_ASKED = 6
    CLOSING = 7
    OTHERWISE = 8


@dataclass(frozen=True, slots=True)
class FallbackTemplate:
    """One row of §7.8: its number, the condition in the document's words, and both wordings.

    `text_female` is §7.8's original wording, verbatim. `text_male` is the same row said by a male
    caller — identical to `text_female` for every row whose Russian carries no gendered verb; the
    two are written out separately (not `None`-defaulted) so a reader never has to work out which
    rows differ, only `text_for` does.
    """

    row: FallbackRow
    condition: str
    text_female: str
    text_male: str

    def text_for(self, gender: Gender) -> str:
        """§7.8's wording in `gender`'s voice; row 2's `{labels_and_values}` is still unfilled."""
        return self.text_male if gender == "male" else self.text_female


def gender_from_voice_id(voice_id: str) -> Gender:
    """The gender a logical `caller_profile.voice_id` names (HLD 30 §30.3): `ru_male_*` -> male,
    everything else -> female — the template set's original gender and, for a voice id the
    `ru_(female|male)_` prefix does not name, a safe default (§30.3 has no third gender today)."""
    return "male" if voice_id.startswith("ru_male_") else "female"


#: §7.8, verbatim, in table order. `FallbackTemplates.select` matches top-down, first match wins.
FALLBACK_TEMPLATES_RU: tuple[FallbackTemplate, ...] = (
    FallbackTemplate(
        row=FallbackRow.UNINTELLIGIBLE,
        condition="speech_act == UNINTELLIGIBLE or semantic_confidence < 0.3",
        text_female="Простите, я не расслышала, повторите, пожалуйста.",
        text_male="Простите, я не расслышал, повторите, пожалуйста.",
    ),
    FallbackTemplate(
        row=FallbackRow.ALLOWED_FACTS,
        condition="allowed non-empty",
        # `{labels_and_values}` is rendered by the selector as `{label_ru} — {caller_value_ru}`
        # joined by «, », at most `ROW_2_MAX_FACTS` facts. It is the only row that reveals
        # anything, and it does so through the normal TTS path (§7.8's note). No gendered verb.
        text_female="{labels_and_values}.",
        text_male="{labels_and_values}.",
    ),
    FallbackTemplate(
        row=FallbackRow.ALL_UNKNOWN,
        condition="allowed empty and every requested fact is unavailable(reason=UNKNOWN)",
        text_female="Я не знаю, простите.",
        text_male="Я не знаю, простите.",
    ),
    FallbackTemplate(
        row=FallbackRow.WITHHELD_OR_NEVER,
        condition=(
            "allowed empty and some requested fact is unavailable(reason=NEVER_DISCLOSE) "
            "or withheld"
        ),
        text_female="Я… я не могу сейчас сказать.",
        text_male="Я… я не могу сейчас сказать.",
    ),
    FallbackTemplate(
        row=FallbackRow.NOT_YET,
        condition="allowed empty and some requested fact is not_yet",
        text_female="Я пока не знаю.",
        text_male="Я пока не знаю.",
    ),
    FallbackTemplate(
        row=FallbackRow.NOTHING_ASKED,
        # Manager ruling (2): `OTHER` is not a member of the code `SpeechAct` enum.
        condition=(
            "requested_facts empty, speech_act == GREETING or any act with no requested facts "
            "that is not CLOSING"
        ),
        text_female="Да, я слушаю.",
        text_male="Да, я слушаю.",
    ),
    FallbackTemplate(
        row=FallbackRow.CLOSING,
        condition="speech_act == CLOSING",
        text_female="Хорошо. Спасибо.",
        text_male="Хорошо. Спасибо.",
    ),
    FallbackTemplate(
        row=FallbackRow.OTHERWISE,
        condition="anything else",
        text_female="Я не знаю, что сказать.",
        text_male="Я не знаю, что сказать.",
    ),
)
