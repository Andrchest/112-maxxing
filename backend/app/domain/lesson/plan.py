"""A lesson's plan — who plays, which cards, and when each card arrives (HLD 70 §70.3.1, D15).

Arrivals are evaluated in **lesson wall milliseconds** (since the lesson's `started_at`): a
lesson's wall clock decides only *when* a card's session starts, never anything inside it (INV 7).
The evaluation is pure — `due_offset_ms` gets the facts about the previous card already projected
by the application (`PreviousCard`), the way a guard gets a `GuardRuntime`. The card is due
at (lesson wall ms):

* `AT_OFFSET` — `offset_ms + delay_ms`;
* `AFTER_PREVIOUS_112_STAGE` — when the previous card's 112 stage reached `HANDED_OFF`,
  `+ delay_ms`;
* `AFTER_PREVIOUS_SESSION` — when the previous card's session became `COMPLETED` or
  `ABORTED`, `+ delay_ms`.

`None` means "not due yet, and not knowable yet": the condition does not hold.
"""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.common.errors import DomainError
from app.domain.common.ids import ScenarioVersionId, UserId
from app.domain.enums import RoleType, ServiceId
from app.domain.session.variants import PartialVariants

__all__ = [
    "Arrival",
    "ArrivalKind",
    "LessonParticipant",
    "LessonPlanError",
    "PlanEntry",
    "PreviousCard",
    "arrival_due_offset_ms",
    "arrival_holds",
    "validate_plan",
]


class ArrivalKind(str, Enum):
    """When a plan entry's card arrives (§70.3.1)."""

    AT_OFFSET = "AT_OFFSET"
    """Lesson wall ms since the lesson started ≥ `offset_ms`."""
    AFTER_PREVIOUS_112_STAGE = "AFTER_PREVIOUS_112_STAGE"
    """The previous card's OPERATOR_112 stage reached `HANDED_OFF`."""
    AFTER_PREVIOUS_SESSION = "AFTER_PREVIOUS_SESSION"
    """The previous card's session is `COMPLETED` or `ABORTED`."""


class LessonPlanError(DomainError):
    """The plan itself is malformed (`422 VALIDATION_ERROR`)."""

    code = "VALIDATION_ERROR"


class Arrival(BaseModel):
    """`openapi.yaml`'s `Arrival` — `offset_ms` required for `AT_OFFSET`, forbidden otherwise."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ArrivalKind
    offset_ms: int | None = Field(default=None, ge=0)
    delay_ms: int = Field(default=0, ge=0)
    """Added after the condition holds (for `AT_OFFSET`, after the offset)."""

    @model_validator(mode="after")
    def _offset_only_for_at_offset(self) -> Self:
        if self.kind is ArrivalKind.AT_OFFSET and self.offset_ms is None:
            raise ValueError("arrival.offset_ms is required for AT_OFFSET")
        if self.kind is not ArrivalKind.AT_OFFSET and self.offset_ms is not None:
            raise ValueError(f"arrival.offset_ms is forbidden for {self.kind.value}")
        return self


class LessonParticipant(BaseModel):
    """One user of the lesson, optionally pinned to a role (§70.3.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UserId
    assigned_role_type: RoleType | None = None
    assigned_service_id: ServiceId | None = None
    """E5's ДДС participant → service binding (§70.4.5); carried, not used, before E5."""


class PlanEntry(BaseModel):
    """One card of the lesson (§70.3.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: int = Field(ge=1)
    scenario_version_id: ScenarioVersionId
    arrival: Arrival
    variants: PartialVariants | None = None
    """A per-card override of the lesson-wide request, within the version's support."""
    participants: tuple[UserId, ...] | None = None
    """E9a hook — per-workstation tasks; `None` = every lesson participant."""
    weight: float = Field(default=1.0, gt=0)
    """E9a hook — the card's weight in the lesson report."""


def validate_plan(entries: tuple[PlanEntry, ...]) -> tuple[PlanEntry, ...]:
    """The plan in `position` order, or `LessonPlanError`.

    Positions are exactly `1..N` (unique, no gap); position 1 must be `AT_OFFSET`, because the
    `AFTER_*` kinds need a previous card.
    """
    if not entries:
        raise LessonPlanError("scenario_plan must have at least one entry")
    ordered = tuple(sorted(entries, key=lambda entry: entry.position))
    positions = [entry.position for entry in ordered]
    if positions != list(range(1, len(ordered) + 1)):
        raise LessonPlanError(
            f"scenario_plan positions must be exactly 1..{len(ordered)}, got {positions}"
        )
    if ordered[0].arrival.kind is not ArrivalKind.AT_OFFSET:
        raise LessonPlanError("scenario_plan position 1 must arrive AT_OFFSET")
    return ordered


class PreviousCard(BaseModel):
    """What `AFTER_*` arrivals need to know about the previous card, in lesson wall ms."""

    model_config = ConfigDict(frozen=True)

    handed_off_at_ms: int | None = None
    """When its 112 stage reached `HANDED_OFF` (for a card without a 112 stage: when its prefab
    handoff was received; for a session that ended without a handoff: when it ended)."""
    ended_at_ms: int | None = None
    """When its session became `COMPLETED` or `ABORTED`."""


def arrival_due_offset_ms(arrival: Arrival, previous: PreviousCard | None) -> int | None:
    """The lesson wall ms at which the card is due, or `None` while that is not known yet."""
    if arrival.kind is ArrivalKind.AT_OFFSET:
        assert arrival.offset_ms is not None  # the model validator guarantees it
        return arrival.offset_ms + arrival.delay_ms
    if previous is None:
        return None
    base = (
        previous.handed_off_at_ms
        if arrival.kind is ArrivalKind.AFTER_PREVIOUS_112_STAGE
        else previous.ended_at_ms
    )
    return None if base is None else base + arrival.delay_ms


def arrival_holds(arrival: Arrival, previous: PreviousCard | None, now_lesson_ms: int) -> bool:
    """`True` when the card is due at `now_lesson_ms`."""
    due = arrival_due_offset_ms(arrival, previous)
    return due is not None and now_lesson_ms >= due
