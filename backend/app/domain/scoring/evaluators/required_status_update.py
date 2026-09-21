"""`REQUIRED_STATUS_UPDATE` evaluator (HLD `10-domain-model.md` §10.14 #9,
`30-scenario-format.md` §30.7 example #9).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.enums import RoleType, StatusUpdateKind
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring import evidence
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule

EVIDENCE_CAP = 5


class RequiredStatusUpdateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    update_kind: StatusUpdateKind
    min_count: int = 1
    within_ms_of_event: EventType | None
    within_ms: int | None
    points: float
    penalty_if_missing: float = 0.0


def evaluate(
    rule: ScoringRule,
    config: RequiredStatusUpdateConfig,
    ctx: ScoringContext,
) -> ScoreResult:
    """Did the DDS report back, and soon enough? (§10.14 #9)

    The timing half reads the **first** qualifying update against the **first** occurrence of the
    reference event, and requires the update to follow it: a report sent before the thing it
    reports on is not a report on it. §10.14 says only "within `within_ms` of the reference
    event"; the direction is the reading closest to SPEC §13's "report on arrival" wording and is
    recorded in this task's HLD-gaps list.
    """
    updates = _updates(ctx, config.update_kind)
    reference = (
        None if config.within_ms_of_event is None else ctx.first_of_type(config.within_ms_of_event)
    )

    enough = len(updates) >= config.min_count
    in_time, note = _timing(updates, reference, config)
    passed = enough and in_time

    if updates:
        items = [
            evidence.from_event(
                event,
                f"{config.update_kind.value} на {event.monotonic_offset_ms} мс."
                + ("" if index or not note else f" {note}"),
            )
            for index, event in enumerate(updates[:EVIDENCE_CAP])
        ]
    else:
        items = [
            evidence.from_event(
                evidence.bounding_event(ctx, RoleType.DDS),
                f"Доклад {config.update_kind.value} не отправлялся "
                f"(требуется не менее {config.min_count}).",
            )
        ]
    return evidence.result(
        rule,
        points=config.points if passed else config.penalty_if_missing,
        passed=passed,
        evidence=items,
    )


def _updates(ctx: ScoringContext, kind: StatusUpdateKind) -> tuple[SessionEvent, ...]:
    return tuple(
        event
        for event in ctx.of_type(EventType.DDS_STATUS_UPDATE_SENT)
        if _kind(event.payload.get("update_kind")) is kind
    )


def _timing(
    updates: tuple[SessionEvent, ...],
    reference: SessionEvent | None,
    config: RequiredStatusUpdateConfig,
) -> tuple[bool, str]:
    if config.within_ms is None or config.within_ms_of_event is None:
        return True, ""
    if reference is None:
        return True, f"Событие {config.within_ms_of_event.value} не наступало — срок не отсчитан."
    if not updates:
        return False, ""
    delay = updates[0].monotonic_offset_ms - reference.monotonic_offset_ms
    note = (
        f"Задержка от {config.within_ms_of_event.value}: {delay} мс "
        f"при норме {config.within_ms} мс."
    )
    return 0 <= delay <= config.within_ms, note


def _kind(raw: object) -> StatusUpdateKind | None:
    if isinstance(raw, StatusUpdateKind):
        return raw
    if isinstance(raw, str):
        try:
            return StatusUpdateKind(raw)
        except ValueError:
            return None
    return None
