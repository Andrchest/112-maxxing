"""`apply_effects` — the pure state transition of a tick's fired world events
(HLD `10-domain-model.md` §10.11, §10.5, §10.7, D3, D7, SPEC §12).

`engine.advance` decides **what** fired; this module decides **what that changes**. It is pure:
simulated time is the `now_ms` argument, every id it needs is derived with `uuid5` from the firing
that produced it (no `uuid4`, D2/D7), and it neither reads a clock nor mutates its input — every
changed aggregate is a `model_copy`.

Per §10.11, each fired event emits `WORLD_EVENT_TRIGGERED` and each applied effect emits its own
event, with `actor = SIMULATION`:

| Effect | State change | Event |
|:--|:--|:--|
| `MutateWorldTruth` | `WorldTruth.facts`, `revision + 1` | `WORLD_TRUTH_MUTATED` |
| `MutateCallerBelief` | `CallerBelief.facts/knowledge/certainty`, `revision + 1` |
  `CALLER_BELIEF_MUTATED` |
| `ChangeCallerEmotion` | `CallerBelief.emotion` | `CALLER_EMOTION_CHANGED` |
| `AlterResourceAvailability` | the resource, through `RESOURCE_STATE_MACHINE` |
  `RESOURCE_STATUS_CHANGED` |
| `CreateNotification` | — (the table is E9's) | `NOTIFICATION_CREATED` |
| `CreateRadioMessage` | — (the table is E9's) | `RADIO_MESSAGE_CREATED` |
| `TriggerEvent` | — (already in `WorldState.scheduled`) | — |

D3 is structural here: **a `MutateWorldTruth` never touches `caller_belief` and a
`MutateCallerBelief` never touches `world_truth`** — the two layers are two objects and are copied
independently (`tests/unit/domain/world/test_apply.py` asserts both directions).

Emotion (§10.5): the scenario's `EmotionRule`s run through the existing `apply_emotion_rules` for
the `WorldEventTrigger` of every fired event and, once per call, for the `SimTimeTrigger` of
`now_ms`; `WorldState.emotion_applications` bounds the repeats. An explicit `ChangeCallerEmotion`
effect is applied first, so a rule sees the effect's result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NamedTuple
from uuid import UUID, uuid5

from app.domain.caller.emotion import (
    EmotionState,
    SimTimeTrigger,
    WorldEventTrigger,
    apply_emotion_rules,
)
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import ResourceId
from app.domain.common.state_machine import GuardContext
from app.domain.common.values import FactValue
from app.domain.dds.resources import (
    RESOURCE_STATE_MACHINE,
    EmergencyResource,
    EtaProfile,
)
from app.domain.enums import ActorType, EmotionLabel, ResourceStatus
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.world_truth import WorldTruth
from app.domain.world.conditions import resolve_resource_id
from app.domain.world.effects import (
    AlterResourceAvailability,
    ChangeCallerEmotion,
    CreateNotification,
    CreateRadioMessage,
    MutateCallerBelief,
    MutateWorldTruth,
)
from app.domain.world.engine import FiredEvent, WorldState

__all__ = ["ApplyResult", "SkippedTransition", "apply_effects"]

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)

_ID_NAMESPACE = UUID("2f7c1d43-6b9e-5a02-9d18-4c3f0a6b25d1")
"""Fixed `uuid5` namespace for the notification/radio ids a pure domain may not draw (D2/D7)."""


class SkippedTransition(NamedTuple):
    """One `AlterResourceAvailability` the resource machine refused — a reported no-op."""

    world_event_id: str
    resource_id: str
    trigger: str
    reason: str


class ApplyResult(NamedTuple):
    """`(state, events)` as §10.11 asks, plus the `skipped` list of refused resource transitions.

    A `NamedTuple`, so `state, events, skipped = apply_effects(...)` and `result.state` both read
    naturally; §10.11 prints no return type for `apply_effects` at all — see this task's report.
    """

    state: WorldState
    events: list[DomainEvent]
    skipped: tuple[SkippedTransition, ...]


def _event(event_type: EventType, now_ms: int, payload: Mapping[str, object]) -> DomainEvent:
    return DomainEvent(
        event_type=event_type, actor=_SIMULATION, monotonic_offset_ms=now_ms, payload=payload
    )


def _derived_id(*parts: str) -> UUID:
    """`uuid5(_ID_NAMESPACE, "|".join(parts))`.

    Every caller includes `state.incident_id` among `parts` (H1, E20-H): `incident_id` is a fresh
    random id per session (`create_session.py`'s `self._ids.new()`), so two sessions of the same
    scenario + seed — which fire the *same* `world_event_id`/`occurrence`/effect `index` — still
    derive distinct notification/radio-message ids. Without it, `notification_repository.add_all`'s
    `ON CONFLICT (id) DO NOTHING` (meant to make one tick's re-examination idempotent) silently
    swallows the second session's row as a "duplicate" of the first session's.
    """
    return uuid5(_ID_NAMESPACE, "|".join(parts))


def _scaled(profile: EtaProfile, multiplier: float) -> EtaProfile:
    """Rescale every duration, rounded and never below one second (`eta_multiplier`, §10.11)."""

    def scale(seconds: int) -> int:
        return max(1, round(seconds * multiplier))

    return EtaProfile(
        turnout_delay_seconds=scale(profile.turnout_delay_seconds),
        travel_time_seconds=scale(profile.travel_time_seconds),
        setup_seconds=scale(profile.setup_seconds),
        on_scene_work_seconds=scale(profile.on_scene_work_seconds),
        return_time_seconds=scale(profile.return_time_seconds),
    )


def _availability_trigger(current: ResourceStatus, target: ResourceStatus) -> str | None:
    """The `RESOURCE_STATUS_TRANSITIONS` trigger an `AlterResourceAvailability` means (§10.7)."""
    if target is ResourceStatus.OUT_OF_SERVICE:
        return "breakdown"
    if target is ResourceStatus.UNAVAILABLE:
        return "make_unavailable"
    if target is ResourceStatus.AVAILABLE:
        if current is ResourceStatus.OUT_OF_SERVICE:
            return "repair"
        if current is ResourceStatus.UNAVAILABLE:
            return "make_available"
    return None


def _apply_world_truth(
    world_truth: WorldTruth, effect: MutateWorldTruth, source: str, now_ms: int
) -> tuple[WorldTruth, DomainEvent]:
    facts: dict[str, FactValue] = dict(world_truth.facts)
    changes = []
    for fact_id, new_value in effect.changes.items():
        changes.append(
            {
                "fact_id": fact_id,
                "previous_value": facts.get(fact_id),
                "new_value": new_value,
            }
        )
        facts[fact_id] = new_value
    updated = world_truth.model_copy(update={"facts": facts, "revision": world_truth.revision + 1})
    return updated, _event(
        EventType.WORLD_TRUTH_MUTATED,
        now_ms,
        {
            "revision": updated.revision,
            "changes": changes,
            "source_world_event_id": source,
            "at_offset_ms": now_ms,
        },
    )


def _apply_caller_belief(
    caller_belief: CallerBelief, effect: MutateCallerBelief, source: str, now_ms: int
) -> tuple[CallerBelief, DomainEvent]:
    facts: dict[str, FactValue] = dict(caller_belief.facts)
    knowledge = dict(caller_belief.knowledge)
    certainty = dict(caller_belief.certainty)
    changes = []
    for fact_id, change in effect.changes.items():
        changes.append(
            {
                "fact_id": fact_id,
                "previous_value": facts.get(fact_id),
                "new_value": change.value,
                "knowledge": change.knowledge.value,
                "certainty": change.certainty,
            }
        )
        facts[fact_id] = change.value
        knowledge[fact_id] = change.knowledge
        certainty[fact_id] = change.certainty
    updated = caller_belief.model_copy(
        update={
            "facts": facts,
            "knowledge": knowledge,
            "certainty": certainty,
            "revision": caller_belief.revision + 1,
        }
    )
    return updated, _event(
        EventType.CALLER_BELIEF_MUTATED,
        now_ms,
        {
            "revision": updated.revision,
            "changes": changes,
            "source_world_event_id": source,
            "at_offset_ms": now_ms,
        },
    )


def _emotion_event(
    previous: EmotionState, new: EmotionState, rule_id: str | None, trigger_kind: str, now_ms: int
) -> DomainEvent:
    return _event(
        EventType.CALLER_EMOTION_CHANGED,
        now_ms,
        {
            "previous_emotion": previous.emotion.value,
            "new_emotion": new.emotion.value,
            "previous_stress_level": previous.stress_level,
            "new_stress_level": new.stress_level,
            "emotion_rule_id": rule_id,
            "trigger_kind": trigger_kind,
            "at_offset_ms": now_ms,
        },
    )


def _changed_emotion(effect: ChangeCallerEmotion, current: EmotionState) -> EmotionState:
    emotion: EmotionLabel = (
        effect.set_emotion if effect.set_emotion is not None else current.emotion
    )
    stress = max(0.0, min(1.0, current.stress_level + effect.stress_delta))
    return EmotionState(emotion=emotion, stress_level=stress)


def apply_effects(state: WorldState, fired: Sequence[FiredEvent], now_ms: int) -> ApplyResult:
    """Apply the effects of `fired` to `state` and return the new state plus its `DomainEvent`s.

    `fired` is `WorldState.fired` (the events of one `advance` call); its `effects` already had the
    non-observable `MutateCallerBelief`s dropped, so this function applies what it is given.
    """
    definitions = {definition.world_event_id: definition for definition in state.definitions}
    world_truth = state.world_truth
    caller_belief = state.caller_belief
    resources: dict[ResourceId, EmergencyResource] = dict(state.resources)
    emotion_applications = dict(state.emotion_applications)
    events: list[DomainEvent] = []
    skipped: list[SkippedTransition] = []

    for entry in fired:
        definition = definitions.get(entry.world_event_id)
        events.append(
            _event(
                EventType.WORLD_EVENT_TRIGGERED,
                entry.at_ms,
                {
                    "world_event_id": entry.world_event_id,
                    "kind": definition.kind.value if definition is not None else "UNKNOWN",
                    "occurrence": entry.occurrence,
                    "title_ru": definition.title_ru if definition is not None else "",
                    "caller_observable": entry.caller_observable,
                    "trigger_reason": definition.kind.value
                    if definition is not None
                    else "UNKNOWN",
                    "effect_kinds": [effect.kind.value for effect in entry.effects],
                    "at_offset_ms": entry.at_ms,
                },
            )
        )
        for index, effect in enumerate(entry.effects):
            if isinstance(effect, MutateWorldTruth):
                world_truth, event = _apply_world_truth(
                    world_truth, effect, entry.world_event_id, entry.at_ms
                )
                events.append(event)
            elif isinstance(effect, MutateCallerBelief):
                caller_belief, event = _apply_caller_belief(
                    caller_belief, effect, entry.world_event_id, entry.at_ms
                )
                events.append(event)
            elif isinstance(effect, ChangeCallerEmotion):
                previous = caller_belief.emotion
                new_emotion = _changed_emotion(effect, previous)
                caller_belief = caller_belief.model_copy(update={"emotion": new_emotion})
                events.append(
                    _emotion_event(previous, new_emotion, None, "WORLD_EVENT_EFFECT", entry.at_ms)
                )
            elif isinstance(effect, CreateNotification):
                events.append(
                    _event(
                        EventType.NOTIFICATION_CREATED,
                        entry.at_ms,
                        {
                            "notification_id": _derived_id(
                                "notification",
                                str(state.incident_id),
                                entry.world_event_id,
                                str(entry.occurrence),
                                str(index),
                            ),
                            "audience_role": effect.audience_role.value,
                            "severity": effect.severity.value,
                            "title_ru": effect.title_ru,
                            "body_ru": effect.body_ru,
                            "source_world_event_id": entry.world_event_id,
                            "at_offset_ms": entry.at_ms,
                        },
                    )
                )
            elif isinstance(effect, CreateRadioMessage):
                events.append(
                    _event(
                        EventType.RADIO_MESSAGE_CREATED,
                        entry.at_ms,
                        {
                            "radio_message_id": _derived_id(
                                "radio",
                                str(state.incident_id),
                                entry.world_event_id,
                                str(entry.occurrence),
                                str(index),
                            ),
                            "from_callsign": effect.from_callsign,
                            "to_role": effect.to_role.value,
                            "text_ru": effect.text_ru,
                            "resource_id": effect.resource_id,
                            "source_world_event_id": entry.world_event_id,
                            "at_offset_ms": entry.at_ms,
                        },
                    )
                )
            elif isinstance(effect, AlterResourceAvailability):
                resources, status_event, refusal = _apply_resource_effect(
                    resources, state.resource_keys, effect, entry, now_ms
                )
                if status_event is not None:
                    events.append(status_event)
                if refusal is not None:
                    skipped.append(refusal)
            # TriggerEvent is already queued in `WorldState.scheduled` by `advance` (rule 4).

        caller_belief, emotion_applications, rule_event = _run_emotion_rules(
            state,
            caller_belief,
            emotion_applications,
            WorldEventTrigger(world_event_id=entry.world_event_id),
            "WORLD_EVENT",
            entry.at_ms,
        )
        if rule_event is not None:
            events.append(rule_event)

    caller_belief, emotion_applications, rule_event = _run_emotion_rules(
        state,
        caller_belief,
        emotion_applications,
        SimTimeTrigger(at_ms=now_ms),
        "SIM_TIME",
        now_ms,
    )
    if rule_event is not None:
        events.append(rule_event)

    new_state = state.model_copy(
        update={
            "world_truth": world_truth,
            "caller_belief": caller_belief,
            "resources": resources,
            "emotion_applications": emotion_applications,
        }
    )
    return ApplyResult(new_state, events, tuple(skipped))


def _run_emotion_rules(
    state: WorldState,
    caller_belief: CallerBelief,
    emotion_applications: dict[str, int],
    trigger: WorldEventTrigger | SimTimeTrigger,
    trigger_kind: str,
    now_ms: int,
) -> tuple[CallerBelief, dict[str, int], DomainEvent | None]:
    """Run `apply_emotion_rules` (§10.5) for one trigger; `emotion_applications` bounds repeats."""
    if not state.emotion_rules:
        return caller_belief, emotion_applications, None
    previous = caller_belief.emotion
    new_emotion, rule_id = apply_emotion_rules(
        previous, state.emotion_rules, trigger, emotion_applications
    )
    if rule_id is None:
        return caller_belief, emotion_applications, None
    counts = dict(emotion_applications)
    counts[rule_id] = counts.get(rule_id, 0) + 1
    updated = caller_belief.model_copy(update={"emotion": new_emotion})
    return updated, counts, _emotion_event(previous, new_emotion, rule_id, trigger_kind, now_ms)


def _apply_resource_effect(
    resources: dict[ResourceId, EmergencyResource],
    resource_keys: Mapping[str, ResourceId],
    effect: AlterResourceAvailability,
    entry: FiredEvent,
    now_ms: int,
) -> tuple[dict[ResourceId, EmergencyResource], DomainEvent | None, SkippedTransition | None]:
    """Fire one `AlterResourceAvailability` through `RESOURCE_STATE_MACHINE` (§10.7, §10.11)."""
    key = resolve_resource_id(effect.resource_id, resources, resource_keys)
    if key is None:
        return (
            resources,
            None,
            SkippedTransition(
                entry.world_event_id, effect.resource_id, "-", "no such resource on the board"
            ),
        )
    resource = resources[key]
    trigger = _availability_trigger(resource.current_status, effect.new_status)
    if trigger is None:
        return (
            resources,
            None,
            SkippedTransition(
                entry.world_event_id,
                effect.resource_id,
                "-",
                f"no availability trigger reaches {effect.new_status.value}",
            ),
        )
    ctx = GuardContext(
        actor=_SIMULATION,
        now_ms=entry.at_ms,
        resources={effect.resource_id: resource},
        world_flags={"availability_effect": True, "restore_effect": effect.restore},
    )
    try:
        target = RESOURCE_STATE_MACHINE.fire(resource.current_status, trigger, ctx)
    except InvalidTransitionError as error:
        return (
            resources,
            None,
            SkippedTransition(entry.world_event_id, effect.resource_id, trigger, error.reason),
        )
    update: dict[str, object] = {
        "current_status": target,
        "status_changed_at_offset_ms": entry.at_ms,
    }
    if effect.eta_multiplier != 1.0:
        update["eta"] = _scaled(resource.eta, effect.eta_multiplier)
    moved = resource.model_copy(update=update)
    updated = dict(resources)
    updated[key] = moved
    event = _event(
        EventType.RESOURCE_STATUS_CHANGED,
        entry.at_ms,
        {
            "resource_id": resource.resource_id,
            "callsign": resource.callsign,
            "previous_status": resource.current_status.value,
            "new_status": target.value,
            "trigger": trigger,
            "source_world_event_id": entry.world_event_id,
            "at_offset_ms": entry.at_ms,
        },
    )
    return updated, event, None
