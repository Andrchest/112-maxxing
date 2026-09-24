"""`CallerPromptBuilder` — the only thing that decides what the caller LLM sees (§5.2, §5.3, D3).

SPEC §21 makes the Fact Access Gate "the ONLY normal path through which scenario facts reach the
caller-response LLM". This module is the other half of that sentence: it accepts an
`AllowedFactsPackage` and a persona, and it has **no parameter** through which a `WorldTruth`, a
`ScenarioVersion`, a `FactDefinition` or a `CallerBelief` could arrive (D3, R3). That is enforced by
two tests, not by convention: an import scan of this module and a signature scan of `build()`
(`backend/tests/invariants/test_r3_caller_prompt_information_boundary.py`).

`already_revealed` carries `AllowedFact`s — the **caller** values the gate released on earlier
turns, rebuilt by `DialogueContextLoader` from the persisted `gate_output` of those turns, never
re-derived from a `FactDefinition`. Nothing here can tell a revealed fact's caller value from its
world value, because it never sees the latter.

Budgeting (§5.3): the prompt is built, estimated, and shed turns until it fits
`prompt_token_budget = 2700`. Over budget after shedding it **refuses** — `PromptBudgetExceeded
Error` — and the responder answers with the deterministic fallback. It never ships a truncated
`ALLOWED_FACTS` block, because a truncated one is a prompt that silently drops a fact the gate
released and leaves the caller unable to answer a question it was allowed to answer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.application.dialogue.interpreter import DialogueTurn
from app.application.dialogue.prompts.caller import (
    AGE_GROUP_RU,
    ALLOWED_FACTS_EMPTY_RU,
    ALLOWED_FACTS_HEADER_RU,
    ALREADY_REVEALED_EMPTY_RU,
    ALREADY_REVEALED_HEADER_RU,
    CALLER_SYSTEM_PROMPT_RU,
    CERTAINTY_SUFFIX_RU,
    EMOTION_RU,
    PERSONA_BLOCK_TEMPLATE_RU,
    RELATIONSHIP_RU,
    USER_TEMPLATE_RU,
    level_label_ru,
    speaking_rate_label_ru,
)
from app.application.dialogue.validator import estimate_tokens
from app.application.ports.llm import ChatMessage
from app.config.settings import Settings
from app.domain.caller.emotion import EmotionState
from app.domain.caller.profile import CallerProfile
from app.domain.facts.gate import AllowedFact, AllowedFactsPackage

__all__ = [
    "DISPATCHER_LABEL_RU",
    "OPERATOR_LABEL_RU",
    "CallerPromptBuilder",
    "CallerPromptConfig",
    "PromptBudgetExceededError",
    "caller_prompt_config_from_settings",
]

_SPEAKER_LABELS_RU = {"OPERATOR": "ОПЕРАТОР", "CALLER": "ЗВОНЯЩИЙ"}
_EMPTY_WINDOW_RU = "(разговор только начался)"
_STRESS_SCALE = 10
_SENTENCE_END = re.compile(r"[.!?…]")
#: §5.2's floor: the window "never drops below 4 turns".
_DEFAULT_MIN_WINDOW_TURNS = 4


class PromptBudgetExceededError(RuntimeError):
    """§5.3's hard refusal: the prompt does not fit `prompt_token_budget` even after shedding.

    The responder catches this and answers with the deterministic fallback
    (`reason = "PROMPT_BUDGET"`). It is a `RuntimeError` rather than a `DomainError` because it is
    a fact about a model's context window, not about the simulation.
    """


@dataclass(frozen=True, slots=True)
class CallerPromptConfig:
    """§5.3's budget table, as configuration rather than literals in the builder."""

    prompt_token_budget: int = 2700
    allowed_facts_cap: int = 12
    allowed_facts_token_budget: int = 300
    already_revealed_token_budget: int = 300
    turn_window_token_budget: int = 1200
    utterance_token_budget: int = 200
    max_window_turns: int = 6
    min_window_turns: int = _DEFAULT_MIN_WINDOW_TURNS


def caller_prompt_config_from_settings(settings: Settings) -> CallerPromptConfig:
    """`SIM_CALLER_PROMPT_TOKEN_BUDGET` and `SIM_DIALOGUE_WINDOW_TURNS`; the rest are §5.3's."""
    window = settings.dialogue_window_turns
    return CallerPromptConfig(
        prompt_token_budget=settings.caller_prompt_token_budget,
        max_window_turns=window,
        min_window_turns=min(_DEFAULT_MIN_WINDOW_TURNS, window),
    )


OPERATOR_LABEL_RU = _SPEAKER_LABELS_RU["OPERATOR"]
"""Who the caller is talking to on the 112 call — «ОПЕРАТОР» (§5.2)."""
DISPATCHER_LABEL_RU = "ДИСПЕТЧЕР"
"""Who the claimant is talking to on a ДДС call-back (I3 E6b, HLD 80 §80.3.4)."""
_OPERATOR_SAYS_RU = f"{OPERATOR_LABEL_RU} ГОВОРИТ:"


class CallerPromptBuilder:
    """`build(...) -> list[ChatMessage]` — §5.2's two messages, budgeted by §5.3.

    `operator_label_ru` (additive, I3 E6b — HLD 80 §80.3.4's one change to the frozen chain) names
    the other party in the turn window and the last line: «ОПЕРАТОР» by default, which leaves the
    112 call's prompt byte for byte what it was; «ДИСПЕТЧЕР» when the ДДС calls the claimant back.
    It is a constructor argument, not a `build()` one: `build()`'s signature is the information
    boundary R3's test scans, and a label is not information about the scenario.
    """

    def __init__(
        self,
        config: CallerPromptConfig | None = None,
        *,
        operator_label_ru: str = OPERATOR_LABEL_RU,
    ) -> None:
        self._config = config or CallerPromptConfig()
        self._operator_label_ru = operator_label_ru
        self._user_template = USER_TEMPLATE_RU.replace(
            _OPERATOR_SAYS_RU, f"{operator_label_ru} ГОВОРИТ:"
        )

    @property
    def config(self) -> CallerPromptConfig:
        """The budgets this builder applies."""
        return self._config

    def build(
        self,
        package: AllowedFactsPackage,
        profile: CallerProfile,
        emotion: EmotionState,
        already_revealed: Sequence[AllowedFact],
        window: Sequence[DialogueTurn],
        utterance: str,
    ) -> list[ChatMessage]:
        """The system + user messages for one generation call (§5.2's exact layout)."""
        persona = self._persona_block(profile, emotion)
        allowed_block = self._allowed_facts_block(package)
        revealed_block = self._already_revealed_block(already_revealed)
        fitted_utterance = self._fit_utterance(utterance)

        turns = list(window)[-self._config.max_window_turns :]
        while True:
            user = self._user_template.format(
                persona_block=persona,
                allowed_facts_block=allowed_block,
                already_revealed_block=revealed_block,
                recent_turns=self._render_window(turns),
                operator_utterance=fitted_utterance,
            )
            total = estimate_tokens(CALLER_SYSTEM_PROMPT_RU) + estimate_tokens(user)
            if total <= self._config.prompt_token_budget:
                break
            if len(turns) > self._config.min_window_turns:
                turns = turns[1:]
                continue
            if turns and not _is_truncated(turns[0]):
                # §5.2: "if 4 turns still exceed the budget, the oldest of the four has its
                # caller reply truncated to its first sentence".
                turns = [_first_sentence(turns[0]), *turns[1:]]
                continue
            raise PromptBudgetExceededError(
                f"the caller prompt needs about {total} tokens, over the "
                f"{self._config.prompt_token_budget}-token budget of §5.3"
            )

        return [
            ChatMessage(role="system", content=CALLER_SYSTEM_PROMPT_RU),
            ChatMessage(role="user", content=user),
        ]

    # -- blocks -------------------------------------------------------------------------------

    def _persona_block(self, profile: CallerProfile, emotion: EmotionState) -> str:
        """§5.2's nine lines. No raw float ever reaches the prompt (SPEC §6's last line)."""
        return PERSONA_BLOCK_TEMPLATE_RU.format(
            identity_name=profile.identity_ru,
            age_group=AGE_GROUP_RU[profile.age_group],
            relationship_to_incident=RELATIONSHIP_RU[profile.relationship],
            current_emotion=EMOTION_RU[emotion.emotion],
            stress_level=round(emotion.stress_level * _STRESS_SCALE),
            cooperativeness_ru=level_label_ru(profile.cooperativeness),
            verbosity_ru=level_label_ru(profile.verbosity),
            confusion_ru=level_label_ru(profile.confusion),
            interruption_ru=level_label_ru(profile.interruption_tendency),
            speaking_rate_ru=speaking_rate_label_ru(profile.speaking_rate),
        )

    def _allowed_facts_block(self, package: AllowedFactsPackage) -> str:
        """§5.2: one line per allowed fact, `label_ru` + caller value, never the `fact_id`."""
        facts = package.allowed[: self._config.allowed_facts_cap]
        if not facts:
            return f"{ALLOWED_FACTS_HEADER_RU}\n{ALLOWED_FACTS_EMPTY_RU}"
        lines = [
            f"- {fact.label_ru}: {fact.value_ru}{CERTAINTY_SUFFIX_RU if fact.hedge else ''}"
            for fact in facts
        ]
        return "\n".join([ALLOWED_FACTS_HEADER_RU, *lines])

    def _already_revealed_block(self, revealed: Sequence[AllowedFact]) -> str:
        """§5.2's `ALREADY_REVEALED`, truncated oldest-first when it exceeds its budget (§5.3)."""
        items = list(revealed)
        while items:
            lines = [f"- {fact.label_ru}: {fact.value_ru}" for fact in items]
            block = "\n".join([ALREADY_REVEALED_HEADER_RU, *lines])
            if estimate_tokens(block) <= self._config.already_revealed_token_budget:
                return block
            items = items[1:]
        return f"{ALREADY_REVEALED_HEADER_RU}\n{ALREADY_REVEALED_EMPTY_RU}"

    def _render_window(self, turns: Sequence[DialogueTurn]) -> str:
        if not turns:
            return _EMPTY_WINDOW_RU
        labels = {**_SPEAKER_LABELS_RU, "OPERATOR": self._operator_label_ru}
        return "\n".join(f"{labels[turn.speaker]}: {turn.text}" for turn in turns)

    def _fit_utterance(self, utterance: str) -> str:
        """§5.3: the operator's turn is capped at `utterance_token_budget`, start kept."""
        max_chars = self._config.utterance_token_budget * 3
        return utterance if len(utterance) <= max_chars else utterance[:max_chars]


def _first_sentence(turn: DialogueTurn) -> DialogueTurn:
    match = _SENTENCE_END.search(turn.text)
    text = turn.text if match is None else turn.text[: match.end()]
    return DialogueTurn(speaker=turn.speaker, text=text)


def _is_truncated(turn: DialogueTurn) -> bool:
    return _first_sentence(turn).text == turn.text
