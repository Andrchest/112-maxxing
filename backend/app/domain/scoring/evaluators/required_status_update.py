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
    """Did the DDS report back, and soon enough? (§10.14 #9, H4/E20-H)

    **Every** occurrence of the reference event type opens its own `within_ms` window (H4,
    E20-H, replacing the earlier "first occurrence in the whole log" reading, which made the
    rule unsatisfiable in a real session the moment any *earlier* qualifying change existed —
    E19/E20-C's `"Задержка … 279160 мс при норме 60000 мс"` finding): the rule passes only when a
    matching status update follows within the window **for every** such reference event
    (`docs/hld/10-domain-model.md` §10.14 #9 updated to match). A report sent before the thing it
    reports on still does not count towards its window.
    """
    updates = _updates(ctx, config.update_kind)
    enough = len(updates) >= config.min_count

    if config.within_ms is None or config.within_ms_of_event is None:
        in_time = True
        pairs: list[tuple[SessionEvent, SessionEvent | None]] = []
    else:
        references = ctx.of_type(config.within_ms_of_event)
        in_time, pairs = _windows(references, updates, config.within_ms)
    passed = enough and in_time

    if pairs:
        items = [
            evidence.from_event(
                match if match is not None else reference,
                _pair_note(reference, match, config),
            )
            for reference, match in pairs[:EVIDENCE_CAP]
        ]
    elif updates:
        items = [
            evidence.from_event(
                event, f"{config.update_kind.value} на {event.monotonic_offset_ms} мс."
            )
            for event in updates[:EVIDENCE_CAP]
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


def _windows(
    references: tuple[SessionEvent, ...],
    updates: tuple[SessionEvent, ...],
    within_ms: int,
) -> tuple[bool, list[tuple[SessionEvent, SessionEvent | None]]]:
    """`(all_satisfied, [(reference, matching_update_or_none), ...])`, one pair per reference.

    No qualifying reference event at all is vacuously in time (§10.14: nothing to report on, so
    no window is missed) — the pre-existing "event never happened" reading for a rule this early
    in the session, kept unchanged by H4.
    """
    pairs: list[tuple[SessionEvent, SessionEvent | None]] = []
    all_satisfied = True
    for reference in references:
        match = next(
            (
                update
                for update in updates
                if 0 <= update.monotonic_offset_ms - reference.monotonic_offset_ms <= within_ms
            ),
            None,
        )
        if match is None:
            all_satisfied = False
        pairs.append((reference, match))
    return all_satisfied, pairs


def _pair_note(
    reference: SessionEvent, match: SessionEvent | None, config: RequiredStatusUpdateConfig
) -> str:
    assert config.within_ms_of_event is not None  # narrowed by the caller
    if match is None:
        return (
            f"{config.within_ms_of_event.value} на {reference.monotonic_offset_ms} мс: "
            f"доклад {config.update_kind.value} не поступил в течение "
            f"{config.within_ms} мс."
        )
    delay = match.monotonic_offset_ms - reference.monotonic_offset_ms
    return (
        f"{config.within_ms_of_event.value} на {reference.monotonic_offset_ms} мс -> "
        f"{config.update_kind.value} на {match.monotonic_offset_ms} мс (через {delay} мс)."
    )


def _kind(raw: object) -> StatusUpdateKind | None:
    if isinstance(raw, StatusUpdateKind):
        return raw
    if isinstance(raw, str):
        try:
            return StatusUpdateKind(raw)
        except ValueError:
            return None
    return None
