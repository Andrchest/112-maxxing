"""The instructor's per-card timer override (I4 E31, HLD 71 §71.8, D34; ТЗ ¶240 REQ-2200/2201).

A scenario's `timers` (HLD 30 §30.12, `ScenarioVersion.card_timers`) are the norm a card is
played against. The instructor may override them per key when creating a session
(`SessionCreateRequest.timers`) or per lesson card (`PlanEntry.timers`). The override resolves in
the precedence style of the variants (HLD 70 §70.2.2): **scenario ← override**, key by key; an
absent key keeps the scenario's value. `createSession` records the resolved result in
`SESSION_CREATED.timers`, and a `DEADLINE` rule with `max_offset_timer` reads it from there
(`app.domain.scoring.evaluators.deadline`) — so scoring still reads the log only (INV 9).

Rule R39 (`accept_within_ms < not_completed_after_ms`) applies to the resolved result: an
override that breaks it is refused with `422 VALIDATION_ERROR`, never silently clipped.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.errors import DomainError
from app.domain.dds.card_status import CardTimers

__all__ = ["CardTimersOverride", "TimersOverrideError", "resolve_card_timers"]


class TimersOverrideError(DomainError):
    """The resolved timers break rule R39 (`422 VALIDATION_ERROR`)."""

    code = "VALIDATION_ERROR"


class CardTimersOverride(BaseModel):
    """`openapi.yaml`'s `CardTimersRequest`: a per-key override of the scenario's `timers`, in
    session ms. `None` (or an absent key) keeps the scenario value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accept_within_ms: int | None = Field(default=None, gt=0)
    fill_within_ms: int | None = Field(default=None, gt=0)
    not_completed_after_ms: int | None = Field(default=None, gt=0)


def resolve_card_timers(scenario: CardTimers, override: CardTimersOverride | None) -> CardTimers:
    """The timers a session runs with: `scenario`, with every key `override` sets replaced.

    `TimersOverrideError` when the result breaks R39 (`accept_within_ms <
    not_completed_after_ms`); with no override the scenario's own timers are returned unchanged
    (they passed R39 when the scenario was validated).
    """
    if override is None:
        return scenario
    changes = override.model_dump(exclude_none=True)
    if not changes:
        return scenario
    resolved = scenario.model_copy(update=changes)
    if resolved.accept_within_ms >= resolved.not_completed_after_ms:
        raise TimersOverrideError(
            f"timers.accept_within_ms ({resolved.accept_within_ms}) must be less than "
            f"timers.not_completed_after_ms ({resolved.not_completed_after_ms}) (R39)"
        )
    return resolved
