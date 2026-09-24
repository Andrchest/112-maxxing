"""`SERVICE_SELECTION` and `RECIPIENTS_RESOLVED` (I3 E2b′; HLD 70 §70.6.4, HLD 10 §10.14 #5).

* At `HANDOFF` nothing changes: the set is `HANDOFF_CREATED.recipient_services` (already the union
  auto ∪ manual under I3) — a `RECIPIENTS_RESOLVED` beside it moves no point.
* At `SESSION_END` the set is the `SERVICE_SELECTED`/`SERVICE_DESELECTED` fold ∪ the last
  resolution's `auto_services` at or before the cutoff.
* Rescore equality: a log without `RECIPIENTS_RESOLVED` (every pre-I3 log) scores exactly as it
  did — pinned against the pre-I3 fold, reimplemented here as the reference.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from app.domain.common.ids import EventId
from app.domain.enums import ActorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring.context import build_context
from app.domain.scoring.evaluators.registry import EVALUATORS, parse_rule_config
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule

from tests.unit.domain.scoring._event_log_builders import (
    MUTATORS,
    demo_scenario,
    det_uuid,
    good_log,
    mutate,
)

SCENARIO = demo_scenario()
RULE = next(
    rule for rule in SCENARIO.scoring_rules if rule.rule_id == "services_fire_and_ambulance"
)


def _rule(evaluated_at: str) -> ScoringRule:
    return RULE.model_copy(update={"config": {**RULE.config, "evaluated_at": evaluated_at}})


def _run(rule: ScoringRule, events: Sequence[SessionEvent]) -> ScoreResult:
    ctx = build_context(SCENARIO, events)
    return EVALUATORS[rule.evaluator_type](rule, parse_rule_config(rule), ctx)


def _with_resolution(
    events: Sequence[SessionEvent], auto: Sequence[str], *, position: int | None = None
) -> tuple[SessionEvent, ...]:
    """`events` with one `RECIPIENTS_RESOLVED` inserted at `position` (default: the end), and
    every later `seq_no` shifted by one."""
    at = len(events) if position is None else position
    anchor = events[at - 1]
    payload: dict[str, Any] = {
        "card_id": str(det_uuid("scoring-card")),
        "card_revision_id": None,
        "pack_id": "v046_24-r1",
        "classifier_code": None,
        "candidate_codes": [],
        "main_service": None,
        "auto_services": list(auto),
        "informed_services": [],
        "manual_services": [],
        "notification_list": list(auto),
        "reasons": [],
        "final": False,
        "at_offset_ms": anchor.monotonic_offset_ms,
    }
    resolved = anchor.model_copy(
        update={
            "id": EventId(det_uuid(f"resolved:{at}:{','.join(auto)}")),
            "seq_no": anchor.seq_no + 1,
            "event_type": EventType.RECIPIENTS_RESOLVED,
            "actor_type": ActorType.SIMULATION,
            "actor_id": None,
            "payload": payload,
        }
    )
    shifted = [event.model_copy(update={"seq_no": event.seq_no + 1}) for event in events[at:]]
    return (*events[:at], resolved, *shifted)


def _pre_i3_session_end_set(events: Sequence[SessionEvent]) -> frozenset[str]:
    """The pre-I3 `SESSION_END` fold, as the reference for rescore equality."""
    selected: set[str] = set()
    for event in sorted(events, key=lambda e: e.seq_no):
        service = event.payload.get("service_type")
        if event.event_type is EventType.SERVICE_SELECTED:
            selected.add(str(service))
        elif event.event_type is EventType.SERVICE_DESELECTED:
            selected.discard(str(service))
    return frozenset(selected)


def test_handoff_scoring_ignores_a_resolution_beside_the_snapshot() -> None:
    events = good_log(recipient_services=("FIRE_RESCUE",))
    with_extra = _with_resolution(events, ("AMBULANCE",))
    assert (
        _run(_rule("HANDOFF"), with_extra).points_awarded
        == _run(_rule("HANDOFF"), events).points_awarded
    )
    assert _run(_rule("HANDOFF"), with_extra).points_awarded == 6.0


def test_session_end_folds_the_last_resolution() -> None:
    events = good_log(recipient_services=("FIRE_RESCUE",))
    assert _run(_rule("SESSION_END"), events).points_awarded == 6.0
    resolved = _with_resolution(events, ("AMBULANCE",))
    result = _run(_rule("SESSION_END"), resolved)
    assert result.points_awarded == 12.0
    assert result.passed
    by_id = {event.id: event for event in resolved}
    assert any(
        by_id[item.event_id].event_type is EventType.RECIPIENTS_RESOLVED
        for item in result.evidence
        if item.event_id in by_id
    )


def test_session_end_takes_the_last_resolution_only() -> None:
    events = good_log(recipient_services=("FIRE_RESCUE",))
    first = _with_resolution(events, ("AMBULANCE",))
    both = _with_resolution(first, ())
    assert _run(_rule("SESSION_END"), both).points_awarded == 6.0


@pytest.mark.parametrize("name", ["good", *sorted(MUTATORS)])
@pytest.mark.parametrize("evaluated_at", ["HANDOFF", "SESSION_END"])
def test_rescore_equality_for_logs_without_a_resolution(name: str, evaluated_at: str) -> None:
    events = good_log() if name == "good" else mutate(name)
    result = _run(_rule(evaluated_at), events)
    if evaluated_at == "SESSION_END":
        services = _pre_i3_session_end_set(events)
        required = RULE.config["required_services"]
        forbidden = RULE.config["forbidden_services"]
        expected = 6.0 * sum(1 for s in required if s in services) - 3.0 * sum(
            1 for s in forbidden if s in services
        )
        assert result.points_awarded == expected
    # an empty resolution changes nothing either
    assert _run(_rule(evaluated_at), _with_resolution(events, ())).points_awarded == (
        result.points_awarded
    )
