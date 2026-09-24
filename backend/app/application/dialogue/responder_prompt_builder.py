"""`ResponderPromptBuilder` — the optional LLM paraphrase of a service head's line (HLD
`80-telephony.md` §80.4.3 `llm`, D24, INV 1/2; I3 E6c).

`Settings.responder_dialogue = llm` lets a model reword the line `ResponderTemplates` already
decided — never decide it. The prompt is built from exactly two things: the persona block (title,
greeting) and `KNOWN_FACTS`, the head's knowledge rendered as lines (`known_facts_of`: the snapshot
values the ДДС was sent and the due steps in the memo's words), plus the recent turns of this call
and the template line to reword. The builder's parameters name no scenario, world-truth or
caller-belief type (the `test_r3` signature test holds that), so nothing outside the knowledge can
reach the model through it.

What comes back is checked by code (`responder_line_violations`) before a word of it is spoken:
every number must already be in the allowed set (the template line, the knowledge, the trainee's
own words), and no scenario value outside the knowledge may appear (the leak check — the check is
code and may see those values, D10). Any failure is the template line (INV 14).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.application.dialogue.interpreter import DialogueTurn
from app.application.dialogue.text_normalization import canonical_numbers, normalize_text
from app.application.ports.llm import ChatMessage
from app.domain.dds.personas import Persona

__all__ = [
    "RESPONDER_JSON_SCHEMA",
    "RESPONDER_MAX_CHARS",
    "RESPONDER_SCHEMA_NAME",
    "ResponderPromptBuilder",
    "responder_line_violations",
]

RESPONDER_MAX_CHARS = 300
RESPONDER_SCHEMA_NAME = "responder_utterance"
RESPONDER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["utterance"],
    "properties": {
        "utterance": {"type": "string", "minLength": 1, "maxLength": RESPONDER_MAX_CHARS}
    },
}

_SYSTEM_TEMPLATE_RU = (
    "Ты — {title}. Ты разговариваешь по телефону с диспетчером ДДС. Говори по-русски, коротко, "
    "одной-двумя фразами, как на служебной связи.\n"
    "KNOWN_FACTS — всё, что ты знаешь. Других сведений у тебя нет:\n{facts}\n"
    "Твоя задача — перефразировать готовый ответ, сохранив его смысл. Не добавляй ни одного "
    "числа, адреса, имени, статуса или обещания, которых нет в готовом ответе или в KNOWN_FACTS. "
    'Верни JSON вида {{"utterance": "..."}}.'
)
_USER_TEMPLATE_RU = (
    "Последние реплики:\n{window}\nДиспетчер сказал: {utterance}\nГотовый ответ: {line}"
)


@dataclass(frozen=True, slots=True)
class ResponderPromptBuilder:
    """Renders the paraphrase prompt from the persona and the head's knowledge only."""

    max_window_turns: int = 4

    def build(
        self,
        persona: Persona | None,
        known_facts: Sequence[str],
        window: Sequence[DialogueTurn],
        utterance: str,
        template_line: str,
    ) -> list[ChatMessage]:
        """The two chat messages of one paraphrase request."""
        title = "старший дежурной службы" if persona is None else persona.title_ru
        facts = "\n".join(f"- {fact}" for fact in known_facts) or "- (ничего)"
        turns = list(window)[-self.max_window_turns :]
        rendered_window = (
            "\n".join(
                f"{'ДИСПЕТЧЕР' if turn.speaker == 'OPERATOR' else 'ТЫ'}: {turn.text}"
                for turn in turns
            )
            or "(нет)"
        )
        return [
            ChatMessage(
                role="system", content=_SYSTEM_TEMPLATE_RU.format(title=title, facts=facts)
            ),
            ChatMessage(
                role="user",
                content=_USER_TEMPLATE_RU.format(
                    window=rendered_window, utterance=utterance, line=template_line
                ),
            ),
        ]


def responder_line_violations(
    text: str, allowed_texts: Iterable[str], forbidden_values: Iterable[str]
) -> list[str]:
    """Why a paraphrased line may not be spoken (empty when it may): empty or too long, a number
    not in the allowed texts, or a scenario value outside the knowledge (the leak check)."""
    problems: list[str] = []
    stripped = text.strip()
    if not stripped:
        return ["EMPTY"]
    if len(stripped) > RESPONDER_MAX_CHARS:
        problems.append("TOO_LONG")
    allowed = list(allowed_texts)
    permitted_numbers = canonical_numbers(allowed)
    spoken_numbers = normalize_text(stripped).number_values
    if not spoken_numbers <= permitted_numbers:
        problems.append("NUMBER_NOT_ALLOWED")
    haystack = normalize_text(stripped).texts
    allowed_haystacks = [normalize_text(item).texts for item in allowed]
    for value in forbidden_values:
        needle = normalize_text(value).texts
        if not needle:
            continue
        if _contains(haystack, needle) and not any(
            _contains(source, needle) for source in allowed_haystacks
        ):
            problems.append("LEAK")
            break
    return problems


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if len(needle) > len(haystack):
        return False
    return any(
        haystack[start : start + len(needle)] == needle
        for start in range(len(haystack) - len(needle) + 1)
    )
