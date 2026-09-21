"""The eight deterministic fallback templates (HLD `50-voice-pipeline.md` §7.8), as **data**.

§7.8's last line: "Templates are data in `backend/app/application/dialogue/fallback_templates_ru.py`
and contain no scenario values other than the caller values passed in for row 2." That sentence is
the whole contract of this module — it holds the Russian wording and the conditions in the
document's order, and `fallbacks.py` holds the selector that reads them.

Row 6's condition carries the manager's ruling (2): the interpreter's `speech_act` enum is the code
`SpeechAct` (ten members, no `OTHER`), so §7.8's original "`GREETING`/`OTHER`" wording is replaced
by "`speech_act == GREETING` or any act with no requested facts that is not `CLOSING`".
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

__all__ = ["FALLBACK_TEMPLATES_RU", "ROW_2_MAX_FACTS", "FallbackRow", "FallbackTemplate"]

#: §7.8 row 2: "max 3 facts, the rest dropped and left unrevealed".
ROW_2_MAX_FACTS = 3


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
    """One row of §7.8: its number, the condition in the document's words, and the wording."""

    row: FallbackRow
    condition: str
    text: str


#: §7.8, verbatim, in table order. `FallbackTemplates.select` matches top-down, first match wins.
FALLBACK_TEMPLATES_RU: tuple[FallbackTemplate, ...] = (
    FallbackTemplate(
        row=FallbackRow.UNINTELLIGIBLE,
        condition="speech_act == UNINTELLIGIBLE or semantic_confidence < 0.3",
        text="Простите, я не расслышала, повторите, пожалуйста.",
    ),
    FallbackTemplate(
        row=FallbackRow.ALLOWED_FACTS,
        condition="allowed non-empty",
        # `{labels_and_values}` is rendered by the selector as `{label_ru} — {caller_value_ru}`
        # joined by «, », at most `ROW_2_MAX_FACTS` facts. It is the only row that reveals
        # anything, and it does so through the normal TTS path (§7.8's note).
        text="{labels_and_values}.",
    ),
    FallbackTemplate(
        row=FallbackRow.ALL_UNKNOWN,
        condition="allowed empty and every requested fact is unavailable(reason=UNKNOWN)",
        text="Я не знаю, простите.",
    ),
    FallbackTemplate(
        row=FallbackRow.WITHHELD_OR_NEVER,
        condition=(
            "allowed empty and some requested fact is unavailable(reason=NEVER_DISCLOSE) "
            "or withheld"
        ),
        text="Я… я не могу сейчас сказать.",
    ),
    FallbackTemplate(
        row=FallbackRow.NOT_YET,
        condition="allowed empty and some requested fact is not_yet",
        text="Я пока не знаю.",
    ),
    FallbackTemplate(
        row=FallbackRow.NOTHING_ASKED,
        # Manager ruling (2): `OTHER` is not a member of the code `SpeechAct` enum.
        condition=(
            "requested_facts empty, speech_act == GREETING or any act with no requested facts "
            "that is not CLOSING"
        ),
        text="Да, я слушаю.",
    ),
    FallbackTemplate(
        row=FallbackRow.CLOSING,
        condition="speech_act == CLOSING",
        text="Хорошо. Спасибо.",
    ),
    FallbackTemplate(
        row=FallbackRow.OTHERWISE,
        condition="anything else",
        text="Я не знаю, что сказать.",
    ),
)
