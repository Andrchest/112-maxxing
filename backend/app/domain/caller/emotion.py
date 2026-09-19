"""`EmotionState`, `EmotionRule`, `EmotionTrigger`, `apply_emotion_rules` (HLD `10-domain-model.md`
§10.5, SPEC §6, D4).

`current_emotion` and `stress_level` are simulation state, not scenario data (D4): they live in
`CallerBelief.emotion` as an `EmotionState`, and change only through deterministic `EmotionRule`s
applied by `apply_emotion_rules`. No model output ever feeds an `EmotionTrigger` — it is always
built by deterministic engine/pipeline code from a `WorldEvent`, an `EventType`, a revealed
`fact_id`, elapsed sim time, or an interruption count.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EmotionLabel
from app.domain.events.types import EventType


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class EmotionState(BaseModel):
    """Current emotion + stress level (§10.5). `stress_level` is always in `[0.0, 1.0]`."""

    model_config = ConfigDict(extra="forbid")

    emotion: EmotionLabel
    stress_level: float = Field(ge=0.0, le=1.0)


class WorldEventTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["WORLD_EVENT"] = "WORLD_EVENT"
    world_event_id: str


class EventTypeTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["EVENT_TYPE"] = "EVENT_TYPE"
    event_type: EventType


class FactRevealedTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["FACT_REVEALED"] = "FACT_REVEALED"
    fact_id: str


class SimTimeTrigger(BaseModel):
    """Fires once the simulation has reached at least `at_ms` (§10.5)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["SIM_TIME"] = "SIM_TIME"
    at_ms: int


class InterruptionCountTrigger(BaseModel):
    """Fires once the trainee has interrupted the caller at least `at_least` times (§10.5)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["INTERRUPTION_COUNT"] = "INTERRUPTION_COUNT"
    at_least: int


EmotionTrigger = Annotated[
    WorldEventTrigger
    | EventTypeTrigger
    | FactRevealedTrigger
    | SimTimeTrigger
    | InterruptionCountTrigger,
    Field(discriminator="kind"),
]


class EmotionRule(BaseModel):
    """`trigger -> delta`, scenario data (D4); applied in scenario declaration order (§10.5)."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    trigger: EmotionTrigger
    set_emotion: EmotionLabel | None = None
    stress_delta: float = 0.0
    max_applications: int | None = None


def _trigger_matches(rule_trigger: EmotionTrigger, actual: EmotionTrigger) -> bool:
    """True when `actual` satisfies the declarative `rule_trigger` (§10.5).

    `WORLD_EVENT`/`EVENT_TYPE`/`FACT_REVEALED` match by identity; `SIM_TIME`/`INTERRUPTION_COUNT`
    match when `actual`'s current value has reached the rule's threshold (`at_ms`/`at_least` on
    `actual` is the *current* simulation time / interruption count, supplied by the caller).
    """
    if isinstance(rule_trigger, WorldEventTrigger) and isinstance(actual, WorldEventTrigger):
        return rule_trigger.world_event_id == actual.world_event_id
    if isinstance(rule_trigger, EventTypeTrigger) and isinstance(actual, EventTypeTrigger):
        return rule_trigger.event_type == actual.event_type
    if isinstance(rule_trigger, FactRevealedTrigger) and isinstance(actual, FactRevealedTrigger):
        return rule_trigger.fact_id == actual.fact_id
    if isinstance(rule_trigger, SimTimeTrigger) and isinstance(actual, SimTimeTrigger):
        return actual.at_ms >= rule_trigger.at_ms
    if isinstance(rule_trigger, InterruptionCountTrigger) and isinstance(
        actual, InterruptionCountTrigger
    ):
        return actual.at_least >= rule_trigger.at_least
    return False


def apply_emotion_rules(
    state: EmotionState,
    rules: tuple[EmotionRule, ...],
    trigger: EmotionTrigger,
    applied_counts: Mapping[str, int],
) -> tuple[EmotionState, str | None]:
    """Apply the first rule (declaration order) that matches `trigger` and has applications left.

    Deterministic: no randomness, no clock. Returns `(state, None)` unchanged when no rule
    matches. `stress_level` is always clamped to `[0.0, 1.0]` after applying `stress_delta`.
    """
    for rule in rules:
        if not _trigger_matches(rule.trigger, trigger):
            continue
        applied = applied_counts.get(rule.rule_id, 0)
        if rule.max_applications is not None and applied >= rule.max_applications:
            continue
        new_emotion = rule.set_emotion if rule.set_emotion is not None else state.emotion
        new_stress = _clamp01(state.stress_level + rule.stress_delta)
        return EmotionState(emotion=new_emotion, stress_level=new_stress), rule.rule_id
    return state, None
