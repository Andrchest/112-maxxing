"""`CallerSpeechSink` — the seam E14 plugs streaming TTS into (§3.7, §6, D9, SPEC §18, §25).

E13 decides *what the caller says*; E14 decides *how it is heard*. The two are separated here so
that the epic that adds streaming TTS adds a class rather than editing `DialogueResponder`, exactly
as `TurnResponder` separated E12's ASR stage from E11's pipeline.

**E13 emits no `CALLER_TTS_*` and no `FACTS_DELIVERED`** (the shared ruling 5). "Facts are revealed
by code, not by text": only an uninterrupted `CALLER_TTS_ENDED` produces `FACTS_DELIVERED`, and no
playback exists yet. `PlannedCallerUtterance.fact_ids` is therefore what the utterance *would*
reveal — `app.domain.facts.revealed.facts_delivered(package)` for a model answer, or
`FallbackChoice.fact_ids` for the one fallback row that names facts — and the sink is the component
that will eventually turn it into an event.

The responder calls the sink **last**, after every event and every row of the turn is committed: a
sink that fails must not be able to lose the audit record of what was planned.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from app.application.dialogue.fallback_templates_ru import FallbackRow
from app.application.voice.turn_pipeline import TurnContext
from app.domain.caller.emotion import EmotionState

__all__ = [
    "CallerSpeechSink",
    "NullCallerSpeechSink",
    "PlannedCallerUtterance",
    "UtteranceSource",
]

UtteranceSource = Literal["LLM", "FALLBACK"]
"""Where the wording came from — a validated model answer, or §7.8's deterministic table."""


@dataclass(frozen=True, slots=True)
class PlannedCallerUtterance:
    """One caller reply, decided and committed, waiting to be spoken (E14)."""

    turn_id: uuid.UUID
    turn_index: int
    text: str
    fact_ids: tuple[str, ...]
    """What speaking this to completion would reveal — never what was merely allowed."""
    emotion: EmotionState
    source: UtteranceSource
    template_row: FallbackRow | None = None
    """§7.8's row number for a fallback; `None` for a validated model answer."""


@runtime_checkable
class CallerSpeechSink(Protocol):
    """What turns a decided utterance into audio the trainee hears (§3.7 step `TTSProvider`)."""

    async def speak(self, planned: PlannedCallerUtterance, context: TurnContext) -> None:
        """Play `planned` to the caller's side of the call."""
        ...


class NullCallerSpeechSink:
    """A `CallerSpeechSink` that records what it was given and plays nothing (D13).

    E13 produces the words and E14 produces the audio; a stub that invented playback events would
    be a silently unmet requirement, and one that emitted `FACTS_DELIVERED` would make a fact
    "revealed" without a single millisecond of audio reaching the trainee (D10, SPEC §42 test 10).

    E14 shipped the real one — `app.application.voice.tts_speech_sink.TtsSpeechSink`:
    `TTSProvider.stream` → `CallTransport.play` → `CALLER_TTS_STARTED` / `CALLER_TTS_ENDED` →
    `FACTS_DELIVERED {fact_ids}`, plus both dialogue-side emotion triggers
    (`app.application.dialogue.emotion_updates`): `FACT_REVEALED` at `FACTS_DELIVERED` and
    `INTERRUPTION_COUNT` at `CALLER_UTTERANCE_INTERRUPTED` (§10.5, R7). This one stays because a
    dialogue test that is about the *words* should not have to synthesise audio for them.
    """

    def __init__(self) -> None:
        #: Every utterance handed over, in call order.
        self.spoken: list[PlannedCallerUtterance] = []

    async def speak(self, planned: PlannedCallerUtterance, context: TurnContext) -> None:
        """Remember the planned utterance; play nothing, emit nothing."""
        self.spoken.append(planned)
