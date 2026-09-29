"""`FallbackTemplates` — the deterministic answer when the model cannot be trusted (§7.7, §7.8).

SPEC §24: "retry fail ⇒ deterministic safe fallback". The caller never goes silent, and the text
that replaces a rejected model answer is chosen by the **gate output**, not by the model — which is
why this selector reads an `AllowedFactsPackage` and an `InterpretedUtterance` and nothing else.

Row 2 is the only row that reveals facts, and `FallbackChoice.fact_ids` lists exactly the ones its
text actually names (at most `ROW_2_MAX_FACTS`): the rest are dropped and stay unrevealed, so
`FACTS_DELIVERED` can never claim a fact the trainee did not hear (D10, SPEC §42 test 10). Every
other row carries `fact_ids == ()`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.dialogue.fallback_templates_ru import (
    FALLBACK_TEMPLATES_RU,
    ROW_2_MAX_FACTS,
    FallbackRow,
    FallbackTemplate,
    Gender,
)
from app.application.dialogue.interpreter import InterpretedUtterance
from app.domain.enums import GateReason, SpeechAct
from app.domain.facts.gate import AllowedFactsPackage

__all__ = [
    "LOW_CONFIDENCE_THRESHOLD",
    "FallbackChoice",
    "FallbackTemplates",
]

#: §7.8 row 1: "`semantic_confidence < 0.3`".
LOW_CONFIDENCE_THRESHOLD = 0.3

_TEMPLATES: dict[FallbackRow, FallbackTemplate] = {
    template.row: template for template in FALLBACK_TEMPLATES_RU
}


@dataclass(frozen=True, slots=True)
class FallbackChoice:
    """Which row answered, what it says, and what saying it would reveal."""

    template_row: FallbackRow
    text: str
    fact_ids: tuple[str, ...] = ()


class FallbackTemplates:
    """`select(package, interpreted)` — §7.8's table, top-down, first match wins."""

    def __init__(self, max_facts: int = ROW_2_MAX_FACTS) -> None:
        self._max_facts = max_facts

    def select(
        self,
        package: AllowedFactsPackage,
        interpreted: InterpretedUtterance,
        *,
        gender: Gender = "female",
    ) -> FallbackChoice:
        """The first row of §7.8 whose condition holds for this turn's gate output, worded in
        `gender` (I8 V4; §7.8's own wording, `text_female`, is the default so a caller that does
        not know the scenario's voice gender behaves exactly as before)."""
        if (
            interpreted.speech_act is SpeechAct.UNINTELLIGIBLE
            or interpreted.semantic_confidence < LOW_CONFIDENCE_THRESHOLD
        ):
            return self._plain(FallbackRow.UNINTELLIGIBLE, gender)

        if package.allowed:
            return self._allowed_facts(package, gender)

        reasons = {fact.reason for fact in package.unavailable}
        if package.unavailable and reasons == {GateReason.CALLER_DOES_NOT_KNOW}:
            return self._plain(FallbackRow.ALL_UNKNOWN, gender)
        if GateReason.NEVER_DISCLOSE in reasons or package.withheld_count > 0:
            return self._plain(FallbackRow.WITHHELD_OR_NEVER, gender)
        if GateReason.NOT_YET_AVAILABLE in reasons:
            return self._plain(FallbackRow.NOT_YET, gender)
        if not interpreted.requested_facts and interpreted.speech_act is not SpeechAct.CLOSING:
            return self._plain(FallbackRow.NOTHING_ASKED, gender)
        if interpreted.speech_act is SpeechAct.CLOSING:
            return self._plain(FallbackRow.CLOSING, gender)
        return self._plain(FallbackRow.OTHERWISE, gender)

    # -- rows ---------------------------------------------------------------------------------

    def _plain(self, row: FallbackRow, gender: Gender) -> FallbackChoice:
        return FallbackChoice(template_row=row, text=_TEMPLATES[row].text_for(gender), fact_ids=())

    def _allowed_facts(self, package: AllowedFactsPackage, gender: Gender) -> FallbackChoice:
        """Row 2: `{label_ru} — {caller_value_ru}` joined by «, », capped at `max_facts`."""
        spoken = package.allowed[: self._max_facts]
        rendered = ", ".join(f"{fact.label_ru} — {fact.value_ru}" for fact in spoken)
        template = _TEMPLATES[FallbackRow.ALLOWED_FACTS]
        return FallbackChoice(
            template_row=FallbackRow.ALLOWED_FACTS,
            text=template.text_for(gender).format(labels_and_values=rendered),
            fact_ids=tuple(fact.fact_id for fact in spoken),
        )
