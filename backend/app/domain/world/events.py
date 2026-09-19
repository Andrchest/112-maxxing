"""World-event definitions (HLD `10-domain-model.md` §10.11, `30-scenario-format.md` §30.6).

The four event kinds, discriminated on `kind: WorldEventKind`. All Pydantic v2, `extra="forbid"`,
frozen. Field names and defaults are copied literally from the HLD "four event kinds" table plus
the shared-fields paragraph above it; a field shown with no `= ...` is required. The range
constraints of `30-scenario-format.md` §30.8 items 24-25 are enforced here:

- item 24: `SeededRandomEvent.probability` in `[0.0, 1.0]`; `check_every_ms > 0`; when
  `window_end_ms` is set it is greater than `window_start_ms`.
- item 25: `TimedEvent.at_ms >= 0`; `ConditionalEvent.check_after_ms >= 0`;
  `ActionTriggeredEvent.delay_ms >= 0`.

Interpreting these definitions against a `WorldState` (`advance`) is out of scope for this slice
(E6, `world/engine.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.common.values import FactValue
from app.domain.enums import WorldEventKind
from app.domain.events.types import EventType
from app.domain.world.conditions import Condition
from app.domain.world.effects import Effect


class TimedEvent(BaseModel):
    """Fires once the simulation clock passes `at_ms` (§30.6.3 #1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_event_id: str
    kind: Literal[WorldEventKind.TIMED] = WorldEventKind.TIMED
    title_ru: str
    caller_observable: bool
    max_occurrences: int = 1
    effects: tuple[Effect, ...]
    at_ms: int = Field(ge=0)


class ConditionalEvent(BaseModel):
    """Fires when `condition` holds, re-checked each tick after `check_after_ms` (§30.6.3 #2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_event_id: str
    kind: Literal[WorldEventKind.CONDITIONAL] = WorldEventKind.CONDITIONAL
    title_ru: str
    caller_observable: bool
    max_occurrences: int = 1
    effects: tuple[Effect, ...]
    condition: Condition
    check_after_ms: int = Field(default=0, ge=0)
    cooldown_ms: int = 0


class ActionTriggeredEvent(BaseModel):
    """Fires when a matching `SessionEvent` is appended (§30.6.3 #3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_event_id: str
    kind: Literal[WorldEventKind.ACTION_TRIGGERED] = WorldEventKind.ACTION_TRIGGERED
    title_ru: str
    caller_observable: bool
    max_occurrences: int = 1
    effects: tuple[Effect, ...]
    on_event_type: EventType
    payload_match: Mapping[str, FactValue] | None
    delay_ms: int = Field(default=0, ge=0)


class SeededRandomEvent(BaseModel):
    """Draws from the session-seeded RNG every `check_every_ms` (§30.6.3 #4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_event_id: str
    kind: Literal[WorldEventKind.SEEDED_RANDOM] = WorldEventKind.SEEDED_RANDOM
    title_ru: str
    caller_observable: bool
    max_occurrences: int = 1
    effects: tuple[Effect, ...]
    probability: float = Field(ge=0.0, le=1.0)
    check_every_ms: int = Field(gt=0)
    window_start_ms: int = 0
    window_end_ms: int | None
    condition: Condition | None

    @model_validator(mode="after")
    def _window_end_after_start(self) -> SeededRandomEvent:
        if self.window_end_ms is not None and self.window_end_ms <= self.window_start_ms:
            raise ValueError("window_end_ms must be greater than window_start_ms")
        return self


WorldEventDefinition = Annotated[
    TimedEvent | ConditionalEvent | ActionTriggeredEvent | SeededRandomEvent,
    Field(discriminator="kind"),
]
