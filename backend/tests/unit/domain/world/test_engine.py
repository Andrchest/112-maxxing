"""`advance` — the four event kinds and determinism rules 1-4 (HLD §10.11, D7, SPEC §12)."""

from __future__ import annotations

from random import Random

import pytest
from app.domain.caller.emotion import EmotionState
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import IncidentId
from app.domain.enums import (
    ActorType,
    EmotionLabel,
    KnowledgeState,
    NotificationSeverity,
    ResourceStatus,
    RoleType,
)
from app.domain.events.types import EventType
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.world_truth import WorldTruth
from app.domain.world.conditions import Condition
from app.domain.world.effects import (
    CallerFactChange,
    CreateNotification,
    Effect,
    MutateCallerBelief,
    MutateWorldTruth,
    TriggerEvent,
)
from app.domain.world.engine import PendingAction, ScheduledTrigger, WorldState, advance
from app.domain.world.events import (
    ActionTriggeredEvent,
    ConditionalEvent,
    SeededRandomEvent,
    TimedEvent,
    WorldEventDefinition,
)
from app.domain.world.rng import rng_for

from tests.unit.domain.world._builders import INCIDENT_ID, demo_world_state

_TRAINEE = ActorRef(actor_type=ActorType.TRAINEE)
_RNG = rng_for("test-seed")


def _state(*definitions: WorldEventDefinition, **overrides: object) -> WorldState:
    base: dict[str, object] = {
        "incident_id": IncidentId(INCIDENT_ID),
        "world_truth": WorldTruth(incident_id=IncidentId(INCIDENT_ID), facts={"f": 0}),
        "caller_belief": CallerBelief(
            incident_id=IncidentId(INCIDENT_ID),
            emotion=EmotionState(emotion=EmotionLabel.CALM, stress_level=0.2),
        ),
        "definitions": definitions,
    }
    base.update(overrides)
    return WorldState(**base)  # type: ignore[arg-type]


def _mutation(value: int = 1) -> tuple[Effect, ...]:
    return (MutateWorldTruth(changes={"f": value}),)


def _timed(event_id: str = "timed", at_ms: int = 1_000, **fields: object) -> TimedEvent:
    return TimedEvent(
        world_event_id=event_id,
        title_ru="Событие",
        caller_observable=bool(fields.pop("caller_observable", False)),
        effects=fields.pop("effects", _mutation()),  # type: ignore[arg-type]
        at_ms=at_ms,
        **fields,  # type: ignore[arg-type]
    )


def _conditional(
    event_id: str = "cond", condition: Condition | None = None, **fields: object
) -> ConditionalEvent:
    return ConditionalEvent(
        world_event_id=event_id,
        title_ru="Условие",
        caller_observable=False,
        effects=fields.pop("effects", _mutation()),  # type: ignore[arg-type]
        condition=condition or Condition.model_validate({"sim_time": {"op": "GTE", "ms": 1_000}}),
        **fields,  # type: ignore[arg-type]
    )


def _action_triggered(event_id: str = "act", **fields: object) -> ActionTriggeredEvent:
    return ActionTriggeredEvent(
        world_event_id=event_id,
        title_ru="Действие",
        caller_observable=False,
        effects=fields.pop("effects", _mutation()),  # type: ignore[arg-type]
        on_event_type=EventType.HANDOFF_CREATED,
        payload_match=fields.pop("payload_match", None),  # type: ignore[arg-type]
        **fields,  # type: ignore[arg-type]
    )


def _seeded(
    event_id: str = "rand", probability: float = 1.0, **fields: object
) -> SeededRandomEvent:
    return SeededRandomEvent(
        world_event_id=event_id,
        title_ru="Случайность",
        caller_observable=False,
        effects=fields.pop("effects", _mutation()),  # type: ignore[arg-type]
        probability=probability,
        check_every_ms=fields.pop("check_every_ms", 1_000),  # type: ignore[arg-type]
        window_start_ms=fields.pop("window_start_ms", 0),  # type: ignore[arg-type]
        window_end_ms=fields.pop("window_end_ms", None),  # type: ignore[arg-type]
        condition=fields.pop("condition", None),  # type: ignore[arg-type]
        **fields,  # type: ignore[arg-type]
    )


def _ids(state: WorldState) -> list[str]:
    return [event.world_event_id for event in state.fired]


# ------------------------------------------------------------------------------- time contract


def test_time_never_goes_back() -> None:
    state = _state(last_tick_ms=5_000)
    with pytest.raises(DomainError):
        advance(state, 4_999, [], _RNG)


def test_advance_updates_last_tick_and_resets_fired() -> None:
    state = _state(_timed())
    state, _ = advance(state, 1_000, [], _RNG)
    assert _ids(state) == ["timed"]
    state, _ = advance(state, 2_000, [], _RNG)
    assert state.last_tick_ms == 2_000
    assert state.fired == ()


# ----------------------------------------------------------------------------------- TimedEvent


def test_timed_event_fires_once_the_clock_passes_at_ms() -> None:
    state = _state(_timed(at_ms=1_000))
    state, effects = advance(state, 999, [], _RNG)
    assert _ids(state) == [] and effects == ()
    state, effects = advance(state, 1_000, [], _RNG)
    assert _ids(state) == ["timed"]
    assert len(effects) == 1
    state, effects = advance(state, 5_000, [], _RNG)
    assert _ids(state) == [] and effects == ()


def test_max_occurrences_bounds_a_repeatable_event() -> None:
    condition = Condition.model_validate({"sim_time": {"op": "GTE", "ms": 0}})
    state = _state(_conditional(condition=condition, max_occurrences=2))
    for _ in range(4):
        state, _ = advance(state, state.last_tick_ms + 1_000, [], _RNG)
    assert state.occurrences["cond"] == 2


# ----------------------------------------------------------------------------- ConditionalEvent


def test_conditional_event_waits_for_check_after_ms_and_the_condition() -> None:
    state = _state(_conditional(check_after_ms=3_000))
    state, _ = advance(state, 2_000, [], _RNG)
    assert _ids(state) == []
    state, _ = advance(state, 3_000, [], _RNG)
    assert _ids(state) == ["cond"]


def test_conditional_cooldown_suppresses_the_next_firing() -> None:
    condition = Condition.model_validate({"sim_time": {"op": "GTE", "ms": 0}})
    state = _state(_conditional(condition=condition, max_occurrences=5, cooldown_ms=10_000))
    state, _ = advance(state, 1_000, [], _RNG)
    assert _ids(state) == ["cond"]
    state, _ = advance(state, 5_000, [], _RNG)
    assert _ids(state) == []
    state, _ = advance(state, 11_000, [], _RNG)
    assert _ids(state) == ["cond"]


# -------------------------------------------------------------------------- ActionTriggeredEvent


def _handoff(at_offset_ms: int = 500, **payload: object) -> PendingAction:
    return PendingAction(
        event_type=EventType.HANDOFF_CREATED,
        at_offset_ms=at_offset_ms,
        payload=payload,  # type: ignore[arg-type]
        actor=_TRAINEE,
    )


def test_action_triggered_event_fires_on_a_matching_action_only() -> None:
    state = _state(_action_triggered())
    state, _ = advance(state, 1_000, [], _RNG)
    assert _ids(state) == []
    state, _ = advance(state, 2_000, [_handoff()], _RNG)
    assert _ids(state) == ["act"]


def test_action_triggered_payload_match_is_a_subset_test() -> None:
    state = _state(_action_triggered(payload_match={"service": "FIRE_RESCUE"}))
    state, _ = advance(state, 1_000, [_handoff(service="POLICE")], _RNG)
    assert _ids(state) == []
    state, _ = advance(state, 2_000, [_handoff(service="FIRE_RESCUE", extra=1)], _RNG)
    assert _ids(state) == ["act"]


def test_action_triggered_delay_schedules_instead_of_firing() -> None:
    state = _state(_action_triggered(delay_ms=60_000))
    state, _ = advance(state, 1_000, [_handoff(at_offset_ms=1_000)], _RNG)
    assert _ids(state) == []
    assert state.scheduled == (ScheduledTrigger(world_event_id="act", due_ms=61_000),)
    state, _ = advance(state, 60_999, [], _RNG)
    assert _ids(state) == []
    state, _ = advance(state, 61_000, [], _RNG)
    assert _ids(state) == ["act"]
    assert state.scheduled == ()


# ---------------------------------------------------------------------------- SeededRandomEvent


def test_seeded_random_draws_once_per_absolute_check_tick() -> None:
    state = _state(_seeded(probability=1.0, check_every_ms=1_000))
    state, _ = advance(state, 999, [], _RNG)
    assert _ids(state) == []  # no check tick lies in the half-open interval (0, 999]
    state, _ = advance(state, 1_000, [], _RNG)
    assert _ids(state) == ["rand"]  # the tick k = 1 at 1 000 ms does


def test_seeded_random_probability_zero_never_fires() -> None:
    state = _state(_seeded(probability=0.0))
    for _ in range(10):
        state, _ = advance(state, state.last_tick_ms + 1_000, [], _RNG)
    assert state.occurrences == {}


def test_seeded_random_respects_its_window() -> None:
    state = _state(_seeded(probability=1.0, window_start_ms=5_000, window_end_ms=9_000))
    state, _ = advance(state, 4_999, [], _RNG)
    assert _ids(state) == []
    state, _ = advance(state, 5_000, [], _RNG)
    assert _ids(state) == ["rand"]


def test_seeded_random_after_the_window_never_fires() -> None:
    state = _state(_seeded(probability=1.0, window_start_ms=0, window_end_ms=2_000))
    state, _ = advance(state, 3_000, [], _RNG)  # ticks at 0, 1000, 2000 are all in this call
    assert _ids(state) == ["rand"]
    state = _state(
        _seeded(probability=1.0, window_start_ms=0, window_end_ms=2_000), last_tick_ms=2_500
    )
    state, _ = advance(state, 9_000, [], _RNG)
    assert _ids(state) == []


def test_seeded_random_condition_gates_the_draw() -> None:
    never = Condition.model_validate({"sim_time": {"op": "LT", "ms": 0}})
    state = _state(_seeded(probability=1.0, condition=never))
    state, _ = advance(state, 10_000, [], _RNG)
    assert _ids(state) == []


def test_seeded_random_draw_index_is_partition_independent() -> None:
    """The same absolute horizon fires at the same tick whatever the tick size."""

    def run(step: int) -> list[tuple[str, int]]:
        state = _state(_seeded(probability=0.25, check_every_ms=30_000, max_occurrences=1))
        now = 0
        while now < 600_000:
            now += step
            state, _ = advance(state, now, [], _RNG)
            if state.fired:
                return [(event.world_event_id, event.at_ms) for event in state.fired]
        return []

    assert run(500) == run(2_000) != []


# ------------------------------------------------------------------------- rules 2, 4 and D7


def test_candidate_order_follows_determinism_rule_two() -> None:
    always = Condition.model_validate({"sim_time": {"op": "GTE", "ms": 0}})
    state = _state(
        _seeded("z_rand", probability=1.0),
        _conditional("y_cond", condition=always),
        _action_triggered("x_act"),
        _timed("w_timed", at_ms=0),
        _timed("a_timed", at_ms=0),
    )
    state, _ = advance(state, 1_000, [_handoff()], _RNG)
    assert _ids(state) == ["a_timed", "w_timed", "x_act", "y_cond", "z_rand"]


def test_trigger_event_queues_instead_of_recursing_so_one_call_is_finite() -> None:
    loop_a = _timed("a", at_ms=0, effects=(TriggerEvent(world_event_id="b"),), max_occurrences=99)
    loop_b = _conditional(
        "b",
        condition=Condition.model_validate({"sim_time": {"op": "GTE", "ms": 0}}),
        effects=(TriggerEvent(world_event_id="a"),),
        max_occurrences=99,
    )
    state = _state(loop_a, loop_b)
    state, effects = advance(state, 1_000, [], _RNG)
    assert _ids(state) == ["a", "b"]
    assert all(isinstance(effect, TriggerEvent) for effect in effects)
    state, _ = advance(state, 2_000, [], _RNG)
    assert set(_ids(state)) == {"a", "b"}  # finite per call, never unbounded recursion


def test_caller_observable_false_drops_mutate_caller_belief_without_a_trace() -> None:
    belief_change = MutateCallerBelief(
        changes={"f": CallerFactChange(value=1, knowledge=KnowledgeState.KNOWN, certainty=1.0)}
    )
    effects = (
        belief_change,
        CreateNotification(
            audience_role=RoleType.DDS,
            severity=NotificationSeverity.INFO,
            title_ru="т",
            body_ru="б",
        ),
    )
    hidden = _state(_timed("hidden", at_ms=0, caller_observable=False, effects=effects))
    before = hidden.caller_belief.model_dump_json()
    hidden, returned = advance(hidden, 1_000, [], _RNG)
    assert not any(isinstance(effect, MutateCallerBelief) for effect in returned)
    assert hidden.fired[0].effects == (effects[1],)
    assert hidden.caller_belief.model_dump_json() == before

    shown = _state(_timed("shown", at_ms=0, caller_observable=True, effects=effects))
    shown, returned = advance(shown, 1_000, [], _RNG)
    assert any(isinstance(effect, MutateCallerBelief) for effect in returned)


def test_pending_actions_are_folded_into_the_event_index() -> None:
    state = _state()
    state, _ = advance(state, 1_000, [_handoff(at_offset_ms=900), _handoff(at_offset_ms=100)], _RNG)
    offsets = [occ.at_offset_ms for occ in state.event_index.occurrences[EventType.HANDOFF_CREATED]]
    assert offsets == [100, 900]


def test_rng_factory_is_the_only_source_of_randomness() -> None:
    """A factory that always draws 0.0 fires; one that always draws 1.0 never does."""

    def always(value: float):  # type: ignore[no-untyped-def]
        class _Fixed(Random):
            def random(self) -> float:
                return value

        return lambda event_id, occurrence: _Fixed()

    fires, _ = advance(_state(_seeded(probability=0.5)), 1_000, [], always(0.0))
    misses, _ = advance(_state(_seeded(probability=0.5)), 1_000, [], always(1.0))
    assert _ids(fires) == ["rand"] and _ids(misses) == []


def test_demo_scenario_timed_event_fires_at_its_offset() -> None:
    state = demo_world_state(statuses={"ac2": ResourceStatus.EN_ROUTE})
    state, _ = advance(state, 179_000, [], rng_for("apartment-fire-v1"))
    assert "fire_spreads" not in _ids(state)
    state, _ = advance(state, 180_000, [], rng_for("apartment-fire-v1"))
    assert "fire_spreads" in _ids(state)
