"""`ResponderTemplates` — what a service head says on a ДДС call, decided by code (HLD
`80-telephony.md` §80.4.2, §80.4.3 `template`, D24; I3 E6c).

The deterministic default of `Settings.responder_dialogue`. Given the head's `ResponderKnowledge`
(script + snapshot, nothing else), the interpreter's reading of the trainee's utterance against
`RESPONDER_SLOT_CATALOG` and the utterance itself, `plan` returns one Russian line, the script steps
that line reports (each becomes one `DDS_CALL_STATUS_PROPOSED`) and the card facts the trainee
stated (each one `DDS_CALL_ASSERTION`). It can emit only knowledge fields:

* a **status** is spoken only for a step in `knowledge.steps_due`, in the persona's words
  («Прибыли на место», «наряд 2415»); with nothing due the head says «Пока в пути, доложу позже» —
  a pending step's status, order number or comment is never in any line (INV 2 by construction:
  the knowledge does not hold them);
* an **address** or **victims** answer quotes the snapshot the ДДС was sent, nothing else (D3);
* an **ETA** is never invented («Время прибытия уточню, доложу»);
* an utterance it cannot read gets «Повторите вопрос».

**The first call** of a leg (§80.4.2): the head knows nothing beyond the snapshot and asks for the
checklist («Диктуйте: адрес, что случилось»). **The trainee's statements** are matched to the
snapshot by code — each checklist value the utterance contains (normalised tokens, numerals
folded, `text_normalization`) is a `matches_snapshot: true` assertion, and a value the interpreter
read for the `address` / `victims` slot that matches none is a `false` one. **A later call** (or an
INBOUND one, `report: CALL_IN`) reports the due steps not yet proposed on this call.

`static_lines` is the set of fixed lines of a persona — pre-synthesised at the voice agent's
warm-up (`voice_agent/tts_cache.py`), so the lines that matter do not wait for a whole-utterance
TTS.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.application.dialogue.interpreter import RESPONDER_SLOTS, InterpretedUtterance
from app.application.dialogue.responder_context import (
    ChecklistItem,
    DueStep,
    ResponderKnowledge,
)
from app.application.dialogue.text_normalization import normalize_text
from app.domain.dds.call import DdsCallDirection
from app.domain.dds.personas import Persona
from app.domain.dds.response import SERVICE_RESPONSE_LABELS_RU, ServiceResponseStatus
from app.domain.enums import SpeechAct

__all__ = [
    "CHECKLIST_TOPICS_RU",
    "DEFAULT_GREETING_RU",
    "LINE_ACKNOWLEDGED_RU",
    "LINE_ETA_RU",
    "LINE_IN_TRANSIT_RU",
    "LINE_NO_CHANGE_RU",
    "LINE_ORDER_LATER_RU",
    "LINE_REPEAT_RU",
    "ResponderAssertion",
    "ResponderPlan",
    "ResponderTemplates",
    "detect_slots",
]

DEFAULT_GREETING_RU = "Слушаю."
LINE_REPEAT_RU = "Повторите вопрос."
LINE_IN_TRANSIT_RU = "Пока в пути, доложу позже."
LINE_NO_CHANGE_RU = "Пока без изменений, доложу позже."
LINE_ACKNOWLEDGED_RU = "Принял."
LINE_ETA_RU = "Время прибытия уточню, доложу."
LINE_ORDER_LATER_RU = "Номер наряда сообщу позже."
LINE_NO_ADDRESS_RU = "Адреса в карточке нет."
LINE_NO_VICTIMS_RU = "По карточке сведений о пострадавших нет."

CHECKLIST_TOPICS_RU: Sequence[tuple[str, str]] = (
    ("address.", "адрес"),
    ("incident.", "что случилось"),
    ("description.", "что случилось"),
    ("victims.", "пострадавшие"),
    ("access.", "подъезд к месту"),
)
"""A checklist path's topic, as the head asks for it; any other path is asked by its card label."""

_SLOT_KEYWORDS: Sequence[tuple[str, tuple[str, ...]]] = (
    ("order_number", ("наряд",)),
    ("address", ("адрес", "улиц")),
    ("victims", ("пострадав", "ранен")),
    ("eta", ("когда будете", "сколько ехать", "время прибытия")),
    (
        "status",
        ("статус", "доехал", "выехал", "прибыл", "обстановк", "как у вас", "что у вас", "доложит"),
    ),
)
"""The code's own slot reading, used when the interpreter named no slot (a fake or a fallback)."""

_VICTIM_MARKERS = ("victim", "injur", "casualt")


@dataclass(frozen=True, slots=True)
class ResponderAssertion:
    """One card fact the trainee stated on the call (`DDS_CALL_ASSERTION`, §80.6.1)."""

    field_path: str
    value_ru: str
    matches_snapshot: bool


@dataclass(frozen=True, slots=True)
class ResponderPlan:
    """What the head says this turn, what it proposes and what the trainee asserted."""

    text: str
    proposals: tuple[DueStep, ...]
    assertions: tuple[ResponderAssertion, ...]
    template_row: str
    slots: tuple[str, ...]


def detect_slots(utterance: str) -> tuple[str, ...]:
    """The responder slots the utterance asks about, by keyword (code, deterministic)."""
    lowered = normalize_text(utterance).normalized.lower()
    return tuple(
        slot for slot, keywords in _SLOT_KEYWORDS if any(word in lowered for word in keywords)
    )


def _canonical(tokens: Iterable[tuple[str, str | None]]) -> tuple[str, ...]:
    return tuple(number if number is not None else text for text, number in tokens)


def _canonical_tokens(text: str) -> tuple[str, ...]:
    normalized = normalize_text(text)
    return _canonical((token.text, token.number) for token in normalized.tokens)


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[start : start + len(needle)] == needle
        for start in range(len(haystack) - len(needle) + 1)
    )


def _value_text(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


class ResponderTemplates:
    """The deterministic responder (see the module docstring)."""

    def plan(
        self,
        knowledge: ResponderKnowledge,
        interpretation: InterpretedUtterance,
        utterance: str,
        *,
        greeted: bool,
    ) -> ResponderPlan:
        """This turn's line, proposals and assertions."""
        slots = self._slots(interpretation, utterance)
        assertions = self.assertions(knowledge, interpretation, utterance)
        parts: list[str] = [] if greeted else [self.greeting(knowledge.persona)]
        proposals: list[DueStep] = []
        row = "ANSWER"
        unintelligible = interpretation.speech_act is SpeechAct.UNINTELLIGIBLE
        if unintelligible and not slots and not assertions:
            parts.append(LINE_REPEAT_RU)
            return ResponderPlan(" ".join(parts), (), (), "REPEAT", slots)

        for slot in slots:
            text, reported = self._answer_slot(knowledge, slot, proposals)
            parts.append(text)
            proposals.extend(reported)
        if not slots:
            first_outbound = (
                knowledge.first_call and knowledge.direction is DdsCallDirection.OUTBOUND
            )
            if first_outbound and not greeted and not assertions:
                parts.append(self.checklist_question(knowledge.checklist))
                row = "CHECKLIST"
            elif first_outbound or assertions:
                parts.append(LINE_ACKNOWLEDGED_RU)
                row = "ACKNOWLEDGED"
            else:
                text, reported = self._report(knowledge, proposals)
                parts.append(text)
                proposals.extend(reported)
                row = "REPORT"
        return ResponderPlan(" ".join(parts), tuple(proposals), assertions, row, slots)

    # -- lines ---------------------------------------------------------------------------------

    @staticmethod
    def greeting(persona: Persona | None) -> str:
        return DEFAULT_GREETING_RU if persona is None else persona.greeting_ru

    @staticmethod
    def checklist_question(checklist: Sequence[ChecklistItem]) -> str:
        """«Диктуйте: адрес, что случилось.» — the checklist's topics, each once, in order."""
        topics: list[str] = []
        for item in checklist:
            topic = next(
                (
                    label
                    for prefix, label in CHECKLIST_TOPICS_RU
                    if item.field_path.startswith(prefix)
                ),
                item.label_ru.lower(),
            )
            if topic not in topics:
                topics.append(topic)
        if not topics:
            return "Диктуйте, что случилось."
        return f"Диктуйте: {', '.join(topics)}."

    @staticmethod
    def status_line(persona: Persona | None, due: DueStep) -> str:
        """One due step in the memo's words: «Прибыли на место, наряд 2415.»"""
        status = due.step.status
        words = (
            persona.vocabulary.get(status)
            if persona is not None and status in persona.vocabulary
            else SERVICE_RESPONSE_LABELS_RU.get(status, status.value)
        )
        line = str(words)
        if due.step.order_number:
            line += f", наряд {due.step.order_number}"
        if due.step.comment_ru:
            line += f", {due.step.comment_ru.rstrip('.')}"
        return line + "."

    def static_lines(self, persona: Persona | None) -> tuple[str, ...]:
        """Every fixed line of a persona — what the voice agent pre-synthesises at warm-up."""
        lines = [
            self.greeting(persona),
            LINE_REPEAT_RU,
            LINE_IN_TRANSIT_RU,
            LINE_NO_CHANGE_RU,
            LINE_ACKNOWLEDGED_RU,
            LINE_ETA_RU,
            LINE_ORDER_LATER_RU,
            "Докладываю.",
        ]
        if persona is not None:
            lines.extend(f"{words}." for words in persona.vocabulary.values())
        return tuple(dict.fromkeys(lines))

    # -- slots ---------------------------------------------------------------------------------

    @staticmethod
    def _slots(interpretation: InterpretedUtterance, utterance: str) -> tuple[str, ...]:
        named = [
            fact.fact_id
            for fact in interpretation.requested_facts
            if fact.fact_id in RESPONDER_SLOTS
        ]
        if not named:
            named = list(detect_slots(utterance))
        return tuple(dict.fromkeys(named))

    def _answer_slot(
        self, knowledge: ResponderKnowledge, slot: str, already: Sequence[DueStep]
    ) -> tuple[str, list[DueStep]]:
        if slot == "status":
            return self._report(knowledge, already)
        if slot == "order_number":
            with_order = [
                due
                for due in self._unreported(knowledge, already)
                if due.step.order_number is not None
            ]
            if with_order:
                return self._report(knowledge, already, only=with_order)
            if knowledge.leg_order_number:
                return f"Номер наряда {knowledge.leg_order_number}.", []
            return LINE_ORDER_LATER_RU, []
        if slot == "address":
            values = [
                text
                for item in knowledge.checklist
                if item.field_path.startswith("address.")
                and (text := _value_text(item.value)) is not None
            ]
            return (f"По карточке: {', '.join(values)}." if values else LINE_NO_ADDRESS_RU), []
        if slot == "victims":
            values = [
                text
                for path, value in sorted(knowledge.snapshot_values.items())
                if any(marker in path for marker in _VICTIM_MARKERS)
                and (text := _value_text(value)) is not None
            ]
            return (f"По карточке: {', '.join(values)}." if values else LINE_NO_VICTIMS_RU), []
        return LINE_ETA_RU, []

    @staticmethod
    def _unreported(knowledge: ResponderKnowledge, already: Sequence[DueStep]) -> list[DueStep]:
        taken = {(due.step.status.value, due.due_offset_ms) for due in already}
        return [
            due
            for due in knowledge.steps_due
            if (due.step.status.value, due.due_offset_ms) not in knowledge.proposed_on_this_call
            and (due.step.status.value, due.due_offset_ms) not in taken
        ]

    def _report(
        self,
        knowledge: ResponderKnowledge,
        already: Sequence[DueStep],
        *,
        only: Sequence[DueStep] | None = None,
    ) -> tuple[str, list[DueStep]]:
        """The due steps not yet reported on this call, in script order — or «Пока в пути»."""
        due = list(only) if only is not None else self._unreported(knowledge, already)
        if not due:
            if knowledge.leg_status_now is ServiceResponseStatus.RESPONSE_STARTED:
                return LINE_IN_TRANSIT_RU, []
            return LINE_NO_CHANGE_RU, []
        lines = " ".join(self.status_line(knowledge.persona, step) for step in due)
        return f"Докладываю. {lines}", due

    # -- assertions ----------------------------------------------------------------------------

    @staticmethod
    def assertions(
        knowledge: ResponderKnowledge, interpretation: InterpretedUtterance, utterance: str
    ) -> tuple[ResponderAssertion, ...]:
        """The checklist facts the utterance states, matched by code (see the module docstring).

        Only on a SERVICE_HEAD's first call is the trainee dictating the card; a later call's
        statements are questions and reports, so nothing is asserted there.
        """
        if not knowledge.first_call:
            return ()
        haystack = _canonical_tokens(utterance)
        found: dict[str, ResponderAssertion] = {}
        for item in knowledge.checklist:
            text = _value_text(item.value)
            if text is None:
                continue
            if _contains(haystack, _canonical_tokens(text)):
                found[item.field_path] = ResponderAssertion(item.field_path, text, True)
        for assertion in interpretation.operator_assertions:
            if assertion.fact_id not in ("address", "victims"):
                continue
            stated = assertion.asserted_value.strip()
            if not stated:
                continue
            prefix = "address." if assertion.fact_id == "address" else ""
            candidates = [
                item
                for item in knowledge.checklist
                if (item.field_path.startswith(prefix) if prefix else _is_victims(item))
            ]
            stated_tokens = _canonical_tokens(stated)
            matched = [
                item
                for item in candidates
                if (text := _value_text(item.value)) is not None
                and _contains(stated_tokens, _canonical_tokens(text))
            ]
            if matched:
                for item in matched:
                    found.setdefault(
                        item.field_path,
                        ResponderAssertion(item.field_path, stated, True),
                    )
            else:
                path = candidates[0].field_path if candidates else f"call.{assertion.fact_id}"
                found.setdefault(path, ResponderAssertion(path, stated, False))
        return tuple(found[path] for path in sorted(found))


def _is_victims(item: ChecklistItem) -> bool:
    return any(marker in item.field_path for marker in _VICTIM_MARKERS)
