"""Tests for `app.domain.caller.emotion` (HLD `10-domain-model.md` §10.5, SPEC §6).

Covers rule declaration-order priority, `max_applications`, `stress_level` clamping to
`[0.0, 1.0]`, and every `EmotionTrigger` kind matching correctly.
"""

from __future__ import annotations

import pytest
from app.domain.caller.emotion import (
    EmotionRule,
    EmotionState,
    EventTypeTrigger,
    FactRevealedTrigger,
    InterruptionCountTrigger,
    SimTimeTrigger,
    WorldEventTrigger,
    apply_emotion_rules,
)
from app.domain.enums import EmotionLabel
from app.domain.events.types import EventType
from pydantic import ValidationError


def _state(stress: float = 0.5) -> EmotionState:
    return EmotionState(emotion=EmotionLabel.CALM, stress_level=stress)


def test_emotion_state_rejects_stress_out_of_range() -> None:
    with pytest.raises(ValidationError):
        EmotionState(emotion=EmotionLabel.CALM, stress_level=1.5)
    with pytest.raises(ValidationError):
        EmotionState(emotion=EmotionLabel.CALM, stress_level=-0.1)


def test_first_matching_rule_with_applications_left_wins() -> None:
    rules = (
        EmotionRule(
            rule_id="first",
            trigger=WorldEventTrigger(world_event_id="fire_spreads"),
            set_emotion=EmotionLabel.PANICKED,
            stress_delta=0.1,
        ),
        EmotionRule(
            rule_id="second",
            trigger=WorldEventTrigger(world_event_id="fire_spreads"),
            set_emotion=EmotionLabel.FRIGHTENED,
            stress_delta=0.2,
        ),
    )

    new_state, rule_id = apply_emotion_rules(
        _state(), rules, WorldEventTrigger(world_event_id="fire_spreads"), {}
    )

    assert rule_id == "first"
    assert new_state.emotion is EmotionLabel.PANICKED


def test_exhausted_rule_is_skipped_in_favour_of_the_next_matching_rule() -> None:
    rules = (
        EmotionRule(
            rule_id="first",
            trigger=WorldEventTrigger(world_event_id="fire_spreads"),
            set_emotion=EmotionLabel.PANICKED,
            max_applications=1,
        ),
        EmotionRule(
            rule_id="second",
            trigger=WorldEventTrigger(world_event_id="fire_spreads"),
            set_emotion=EmotionLabel.FRIGHTENED,
        ),
    )

    new_state, rule_id = apply_emotion_rules(
        _state(),
        rules,
        WorldEventTrigger(world_event_id="fire_spreads"),
        {"first": 1},
    )

    assert rule_id == "second"
    assert new_state.emotion is EmotionLabel.FRIGHTENED


def test_no_matching_rule_returns_state_unchanged() -> None:
    rules = (
        EmotionRule(
            rule_id="only",
            trigger=WorldEventTrigger(world_event_id="fire_spreads"),
            set_emotion=EmotionLabel.PANICKED,
        ),
    )
    state = _state(0.4)

    new_state, rule_id = apply_emotion_rules(
        state, rules, WorldEventTrigger(world_event_id="other_event"), {}
    )

    assert rule_id is None
    assert new_state == state


@pytest.mark.parametrize(
    ("delta", "start", "expected"),
    [(0.9, 0.5, 1.0), (-0.9, 0.5, 0.0), (0.2, 0.5, 0.7)],
)
def test_stress_delta_is_clamped_to_zero_one(delta: float, start: float, expected: float) -> None:
    rules = (
        EmotionRule(rule_id="r", trigger=WorldEventTrigger(world_event_id="e"), stress_delta=delta),
    )

    new_state, _ = apply_emotion_rules(
        _state(start), rules, WorldEventTrigger(world_event_id="e"), {}
    )

    assert new_state.stress_level == pytest.approx(expected)


def test_rule_without_set_emotion_keeps_current_emotion() -> None:
    rules = (
        EmotionRule(rule_id="r", trigger=WorldEventTrigger(world_event_id="e"), stress_delta=0.1),
    )
    state = EmotionState(emotion=EmotionLabel.ANGRY, stress_level=0.2)

    new_state, _ = apply_emotion_rules(state, rules, WorldEventTrigger(world_event_id="e"), {})

    assert new_state.emotion is EmotionLabel.ANGRY


# ---------------------------------------------------------------------------------------------
# Every EmotionTrigger kind
# ---------------------------------------------------------------------------------------------


def test_world_event_trigger_matches_by_id() -> None:
    rules = (EmotionRule(rule_id="r", trigger=WorldEventTrigger(world_event_id="e1")),)

    _, matched = apply_emotion_rules(_state(), rules, WorldEventTrigger(world_event_id="e1"), {})
    assert matched == "r"

    _, unmatched = apply_emotion_rules(_state(), rules, WorldEventTrigger(world_event_id="e2"), {})
    assert unmatched is None


def test_event_type_trigger_matches_by_event_type() -> None:
    rules = (
        EmotionRule(
            rule_id="r", trigger=EventTypeTrigger(event_type=EventType.CALLER_UTTERANCE_INTERRUPTED)
        ),
    )

    _, matched = apply_emotion_rules(
        _state(),
        rules,
        EventTypeTrigger(event_type=EventType.CALLER_UTTERANCE_INTERRUPTED),
        {},
    )
    assert matched == "r"

    _, unmatched = apply_emotion_rules(
        _state(), rules, EventTypeTrigger(event_type=EventType.CALL_ANSWERED), {}
    )
    assert unmatched is None


def test_fact_revealed_trigger_matches_by_fact_id() -> None:
    rules = (EmotionRule(rule_id="r", trigger=FactRevealedTrigger(fact_id="people.trapped_count")),)

    _, matched = apply_emotion_rules(
        _state(), rules, FactRevealedTrigger(fact_id="people.trapped_count"), {}
    )
    assert matched == "r"

    _, unmatched = apply_emotion_rules(
        _state(), rules, FactRevealedTrigger(fact_id="other_fact"), {}
    )
    assert unmatched is None


def test_sim_time_trigger_matches_once_threshold_reached() -> None:
    rules = (EmotionRule(rule_id="r", trigger=SimTimeTrigger(at_ms=60_000)),)

    _, too_early = apply_emotion_rules(_state(), rules, SimTimeTrigger(at_ms=30_000), {})
    assert too_early is None

    _, on_time = apply_emotion_rules(_state(), rules, SimTimeTrigger(at_ms=60_000), {})
    assert on_time == "r"

    _, later = apply_emotion_rules(_state(), rules, SimTimeTrigger(at_ms=90_000), {})
    assert later == "r"


def test_interruption_count_trigger_matches_once_threshold_reached() -> None:
    rules = (EmotionRule(rule_id="r", trigger=InterruptionCountTrigger(at_least=3)),)

    _, too_few = apply_emotion_rules(_state(), rules, InterruptionCountTrigger(at_least=2), {})
    assert too_few is None

    _, enough = apply_emotion_rules(_state(), rules, InterruptionCountTrigger(at_least=3), {})
    assert enough == "r"


def test_different_trigger_kinds_never_match_each_other() -> None:
    rules = (EmotionRule(rule_id="r", trigger=WorldEventTrigger(world_event_id="e1")),)

    _, unmatched = apply_emotion_rules(_state(), rules, FactRevealedTrigger(fact_id="e1"), {})
    assert unmatched is None
