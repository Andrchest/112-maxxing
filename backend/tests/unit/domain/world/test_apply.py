"""`apply_effects` — the pure state transition and its `DomainEvent`s (HLD §10.11, §10.5, D3)."""

from __future__ import annotations

import uuid

from app.domain.caller.emotion import EmotionRule, EmotionState, WorldEventTrigger
from app.domain.common.ids import IncidentId
from app.domain.enums import (
    ActorType,
    EmotionLabel,
    KnowledgeState,
    NotificationSeverity,
    ResourceStatus,
    RoleType,
)
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.world_truth import WorldTruth
from app.domain.world.apply import apply_effects
from app.domain.world.effects import (
    AlterResourceAvailability,
    CallerFactChange,
    ChangeCallerEmotion,
    CreateNotification,
    CreateRadioMessage,
    Effect,
    MutateCallerBelief,
    MutateWorldTruth,
    TriggerEvent,
)
from app.domain.world.engine import FiredEvent, WorldState
from app.domain.world.events import TimedEvent

from tests.unit.domain.world._builders import INCIDENT_ID, demo_world_state

_BELIEF_CHANGE = MutateCallerBelief(
    changes={
        "incident.smoke_visible": CallerFactChange(
            value=True, knowledge=KnowledgeState.KNOWN, certainty=1.0
        )
    }
)


def _definition(effects: tuple[Effect, ...], *, observable: bool = True) -> TimedEvent:
    return TimedEvent(
        world_event_id="e1",
        title_ru="Событие",
        caller_observable=observable,
        effects=effects,
        at_ms=0,
    )


def _state(
    effects: tuple[Effect, ...], *, observable: bool = True, **overrides: object
) -> WorldState:
    base: dict[str, object] = {
        "incident_id": IncidentId(INCIDENT_ID),
        "world_truth": WorldTruth(incident_id=IncidentId(INCIDENT_ID), facts={"f": 0}),
        "caller_belief": CallerBelief(
            incident_id=IncidentId(INCIDENT_ID),
            facts={"f": 0},
            emotion=EmotionState(emotion=EmotionLabel.CALM, stress_level=0.2),
        ),
        "definitions": (_definition(effects, observable=observable),),
    }
    base.update(overrides)
    return WorldState(**base)  # type: ignore[arg-type]


def _fired(
    effects: tuple[Effect, ...], *, observable: bool = True, at_ms: int = 1_000
) -> FiredEvent:
    return FiredEvent(
        world_event_id="e1",
        occurrence=0,
        at_ms=at_ms,
        caller_observable=observable,
        effects=effects,
    )


def _types(events: list[DomainEvent]) -> list[EventType]:
    return [event.event_type for event in events]


# ------------------------------------------------------------------------------- the two layers


def test_mutate_world_truth_never_touches_caller_belief() -> None:
    effects: tuple[Effect, ...] = (MutateWorldTruth(changes={"f": 7}),)
    state = _state(effects)
    before = state.caller_belief.model_dump_json()
    result = apply_effects(state, [_fired(effects)], 1_000)
    assert result.state.world_truth.facts["f"] == 7
    assert result.state.world_truth.revision == 1
    assert result.state.caller_belief.model_dump_json() == before


def test_mutate_caller_belief_never_touches_world_truth() -> None:
    effects: tuple[Effect, ...] = (_BELIEF_CHANGE,)
    state = _state(effects)
    before = state.world_truth.model_dump_json()
    result = apply_effects(state, [_fired(effects)], 1_000)
    belief = result.state.caller_belief
    assert belief.facts["incident.smoke_visible"] is True
    assert belief.knowledge["incident.smoke_visible"] is KnowledgeState.KNOWN
    assert belief.certainty["incident.smoke_visible"] == 1.0
    assert belief.revision == 1
    assert result.state.world_truth.model_dump_json() == before


def test_the_input_state_is_never_mutated() -> None:
    effects: tuple[Effect, ...] = (MutateWorldTruth(changes={"f": 7}),)
    state = _state(effects)
    snapshot = state.model_dump_json()
    apply_effects(state, [_fired(effects)], 1_000)
    assert state.model_dump_json() == snapshot


# ------------------------------------------------------------------------------------- events


def test_one_world_event_triggered_then_one_event_per_effect() -> None:
    effects: tuple[Effect, ...] = (
        MutateWorldTruth(changes={"f": 1}),
        _BELIEF_CHANGE,
        CreateNotification(
            audience_role=RoleType.DDS,
            severity=NotificationSeverity.WARNING,
            title_ru="Заголовок",
            body_ru="Текст",
        ),
        CreateRadioMessage(
            from_callsign="АЦ-1", to_role=RoleType.DDS, text_ru="Приём", resource_id=None
        ),
        TriggerEvent(world_event_id="other"),
    )
    result = apply_effects(_state(effects), [_fired(effects)], 1_000)
    assert _types(result.events) == [
        EventType.WORLD_EVENT_TRIGGERED,
        EventType.WORLD_TRUTH_MUTATED,
        EventType.CALLER_BELIEF_MUTATED,
        EventType.NOTIFICATION_CREATED,
        EventType.RADIO_MESSAGE_CREATED,
    ]
    for event in result.events:
        validate_payload(event.event_type, event.payload)
        assert event.actor.actor_type is ActorType.SIMULATION


def test_created_ids_are_derived_not_drawn() -> None:
    effects: tuple[Effect, ...] = (
        CreateNotification(
            audience_role=RoleType.DDS,
            severity=NotificationSeverity.INFO,
            title_ru="т",
            body_ru="б",
        ),
    )
    first = apply_effects(_state(effects), [_fired(effects)], 1_000)
    second = apply_effects(_state(effects), [_fired(effects)], 1_000)
    assert first.events[1].payload["notification_id"] == second.events[1].payload["notification_id"]


def test_notification_and_radio_ids_are_distinct_across_sessions() -> None:
    """H1 (E20-H): two sessions of the *same* scenario + seed fire the same `world_event_id` /
    `occurrence` / effect index, so without `incident_id` in the derivation their notification and
    radio-message ids collide and `notification_repository.add_all`'s `ON CONFLICT (id) DO NOTHING`
    silently swallows the second session's row. Bite proof: dropping `str(state.incident_id)` from
    either `_derived_id(...)` call in `app/domain/world/apply.py` makes this fail (both equal).
    """
    effects: tuple[Effect, ...] = (
        CreateNotification(
            audience_role=RoleType.DDS,
            severity=NotificationSeverity.INFO,
            title_ru="т",
            body_ru="б",
        ),
        CreateRadioMessage(
            from_callsign="АЦ-1", to_role=RoleType.DDS, text_ru="Приём", resource_id=None
        ),
    )
    other_incident_id = IncidentId(uuid.uuid5(uuid.NAMESPACE_URL, "second-session"))
    first = apply_effects(_state(effects), [_fired(effects)], 1_000)
    second = apply_effects(_state(effects, incident_id=other_incident_id), [_fired(effects)], 1_000)
    assert first.events[1].payload["notification_id"] != second.events[1].payload["notification_id"]
    assert (
        first.events[2].payload["radio_message_id"] != second.events[2].payload["radio_message_id"]
    )


# ------------------------------------------------------------------------------------- emotion


def test_change_caller_emotion_effect_applies_and_clamps() -> None:
    effects: tuple[Effect, ...] = (
        ChangeCallerEmotion(set_emotion=EmotionLabel.PANICKED, stress_delta=0.9),
    )
    result = apply_effects(_state(effects), [_fired(effects)], 1_000)
    assert result.state.caller_belief.emotion.emotion is EmotionLabel.PANICKED
    assert result.state.caller_belief.emotion.stress_level == 1.0


def test_emotion_rules_fire_for_the_world_event_trigger_and_are_bounded() -> None:
    rule = EmotionRule(
        rule_id="panic",
        trigger=WorldEventTrigger(world_event_id="e1"),
        set_emotion=EmotionLabel.PANICKED,
        stress_delta=0.3,
        max_applications=1,
    )
    effects: tuple[Effect, ...] = ()
    state = _state(effects, emotion_rules=(rule,))
    result = apply_effects(state, [_fired(effects)], 1_000)
    assert result.state.caller_belief.emotion.emotion is EmotionLabel.PANICKED
    assert result.state.emotion_applications == {"panic": 1}
    emotion_events = [e for e in result.events if e.event_type is EventType.CALLER_EMOTION_CHANGED]
    assert emotion_events[0].payload["emotion_rule_id"] == "panic"
    validate_payload(EventType.CALLER_EMOTION_CHANGED, emotion_events[0].payload)

    again = apply_effects(result.state, [_fired(effects)], 2_000)
    assert again.state.emotion_applications == {"panic": 1}
    assert not [e for e in again.events if e.event_type is EventType.CALLER_EMOTION_CHANGED]


def test_sim_time_emotion_rule_fires_once_per_call() -> None:
    rule = EmotionRule(
        rule_id="late_stress",
        trigger={"kind": "SIM_TIME", "at_ms": 60_000},  # type: ignore[arg-type]
        stress_delta=0.2,
        max_applications=1,
    )
    state = _state((), emotion_rules=(rule,))
    early = apply_effects(state, [], 10_000)
    assert early.state.emotion_applications == {}
    late = apply_effects(state, [], 60_000)
    assert late.state.emotion_applications == {"late_stress": 1}
    assert late.state.caller_belief.emotion.stress_level == 0.4


# --------------------------------------------------------------------- AlterResourceAvailability


def _demo(status: ResourceStatus) -> WorldState:
    return demo_world_state(statuses={"ac2": status})


def test_breakdown_moves_the_resource_through_the_state_machine() -> None:
    state = _demo(ResourceStatus.EN_ROUTE)
    effect = AlterResourceAvailability(resource_id="ac2", new_status=ResourceStatus.OUT_OF_SERVICE)
    result = apply_effects(state, [_fired((effect,))], 1_000)
    key = state.resource_keys["ac2"]
    assert result.state.resources[key].current_status is ResourceStatus.OUT_OF_SERVICE
    assert result.state.resources[key].status_changed_at_offset_ms == 1_000
    assert result.skipped == ()
    status_events = [e for e in result.events if e.event_type is EventType.RESOURCE_STATUS_CHANGED]
    assert status_events[0].payload["trigger"] == "breakdown"
    validate_payload(EventType.RESOURCE_STATUS_CHANGED, status_events[0].payload)


def test_repair_restores_an_out_of_service_resource() -> None:
    state = _demo(ResourceStatus.OUT_OF_SERVICE)
    effect = AlterResourceAvailability(
        resource_id="ac2", new_status=ResourceStatus.AVAILABLE, restore=True
    )
    result = apply_effects(state, [_fired((effect,))], 1_000)
    assert result.state.resources[state.resource_keys["ac2"]].current_status is (
        ResourceStatus.AVAILABLE
    )


def test_an_illegal_transition_is_skipped_and_reported_not_raised() -> None:
    state = _demo(ResourceStatus.AVAILABLE)  # AVAILABLE has no `breakdown` edge
    effect = AlterResourceAvailability(resource_id="ac2", new_status=ResourceStatus.OUT_OF_SERVICE)
    result = apply_effects(state, [_fired((effect,))], 1_000)
    assert result.state.resources[state.resource_keys["ac2"]].current_status is (
        ResourceStatus.AVAILABLE
    )
    assert [skip.trigger for skip in result.skipped] == ["breakdown"]
    assert not [e for e in result.events if e.event_type is EventType.RESOURCE_STATUS_CHANGED]


def test_an_unknown_resource_is_skipped() -> None:
    effect = AlterResourceAvailability(
        resource_id="no_such", new_status=ResourceStatus.OUT_OF_SERVICE
    )
    result = apply_effects(_demo(ResourceStatus.EN_ROUTE), [_fired((effect,))], 1_000)
    assert [skip.resource_id for skip in result.skipped] == ["no_such"]


def test_eta_multiplier_rescales_the_profile_with_a_one_second_floor() -> None:
    state = _demo(ResourceStatus.EN_ROUTE)
    key = state.resource_keys["ac2"]
    before = state.resources[key].eta
    effect = AlterResourceAvailability(
        resource_id="ac2", new_status=ResourceStatus.OUT_OF_SERVICE, eta_multiplier=2.0
    )
    result = apply_effects(state, [_fired((effect,))], 1_000)
    after = result.state.resources[key].eta
    assert after.travel_time_seconds == before.travel_time_seconds * 2
    tiny = AlterResourceAvailability(
        resource_id="ac2", new_status=ResourceStatus.OUT_OF_SERVICE, eta_multiplier=0.0001
    )
    floored = apply_effects(state, [_fired((tiny,))], 1_000)
    assert floored.state.resources[key].eta.setup_seconds == 1
