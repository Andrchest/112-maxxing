"""`WORKFLOW_ACTION` evaluator (HLD `10-domain-model.md` §10.14 #7, `30-scenario-format.md` §30.7
example #7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.common.values import FactValue
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring import evidence
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule
from app.domain.scoring.shared import payload_matches

EVIDENCE_CAP: Literal[5] = 5
"""§10.14 #7: "each qualifying event (capped at 5)" — a report lists proof, not the whole log."""


class WorkflowActionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: EventType
    payload_match: Mapping[str, FactValue] | None
    min_count: int = 1
    max_count: int | None
    required_stage_state: str | None
    must_occur_after: EventType | None
    points: float
    penalty_if_missing: float = 0.0
    penalty_per_excess: float = 0.0


def evaluate(rule: ScoringRule, config: WorkflowActionConfig, ctx: ScoringContext) -> ScoreResult:
    """Did the trainee take the action, the right number of times, in the right order? (§10.14 #7)

    `required_stage_state` is checked against the state the stage was actually in when the action
    happened, folded from `STAGE_STATE_CHANGED` (§10.13) up to that event — not against the state
    at the end of the session, which the trainee may have reached correctly by a wrong route.
    """
    qualifying = _qualifying(ctx, config)
    count = len(qualifying)
    above = 0 if config.max_count is None else max(0, count - config.max_count)

    if count < config.min_count:
        points, passed = config.penalty_if_missing, False
    elif above:
        points, passed = config.penalty_per_excess * above, False
    else:
        points, passed = config.points, True

    if qualifying:
        items = [
            evidence.from_event(
                event,
                f"{config.event_type.value} #{index + 1} на {event.monotonic_offset_ms} мс.",
            )
            for index, event in enumerate(qualifying[:EVIDENCE_CAP])
        ]
    else:
        items = [
            evidence.from_event(
                evidence.bounding_event(ctx),
                f"Действие {config.event_type.value} не выполнено ни разу "
                f"(требуется не менее {config.min_count}).",
            )
        ]
    return evidence.result(rule, points=points, passed=passed, evidence=items)


def _qualifying(ctx: ScoringContext, config: WorkflowActionConfig) -> tuple[SessionEvent, ...]:
    after_seq_no = _after_seq_no(ctx, config)
    if after_seq_no is None:
        return ()
    states = _stage_states(ctx)
    qualifying: list[SessionEvent] = []
    for event in ctx.of_type(config.event_type):
        if event.seq_no < after_seq_no:
            continue
        if not payload_matches(event, config.payload_match):
            continue
        if (
            config.required_stage_state is not None
            and _state_at(states, event.seq_no) != config.required_stage_state
        ):
            continue
        qualifying.append(event)
    return tuple(qualifying)


def _after_seq_no(ctx: ScoringContext, config: WorkflowActionConfig) -> int | None:
    """The `seq_no` the ordering constraint opens at; `None` when the predecessor never happened."""
    if config.must_occur_after is None:
        return 0
    predecessor = ctx.first_of_type(config.must_occur_after)
    return None if predecessor is None else predecessor.seq_no


def _stage_states(ctx: ScoringContext) -> tuple[tuple[int, str], ...]:
    """`(seq_no, new_state)` per `STAGE_STATE_CHANGED`, in log order (§10.13)."""
    timeline: list[tuple[int, str]] = []
    for event in ctx.of_type(EventType.STAGE_STATE_CHANGED):
        new_state = event.payload.get("new_state")
        if isinstance(new_state, str):
            timeline.append((event.seq_no, new_state))
    return tuple(timeline)


def _state_at(states: tuple[tuple[int, str], ...], seq_no: int) -> str | None:
    current: str | None = None
    for at, state in states:
        if at > seq_no:
            break
        current = state
    return current
