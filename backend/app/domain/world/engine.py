"""`PendingAction`, `ScheduledTrigger`, `WorldState`, `FiredEvent`, `advance`
(HLD `10-domain-model.md` §10.11, D7, SPEC §12, §42 item 7).

`advance` is the pure core of the world event engine: no clock, no `random` module state, no
`uuid4`, no environment, no I/O. Simulated time is the `now_ms` argument; randomness arrives only
through `rng_factory` (`world/rng.py`). The four determinism rules of §10.11 are implemented
literally:

1. `pending_actions` are folded into `event_index` first, in `(at_offset_ms, event_type, seq)`
   order (`EventIndex.fold`).
2. Candidates are collected in the fixed order *due `ScheduledTrigger`s → `TimedEvent`s →
   `ActionTriggeredEvent`s matched this tick → `ConditionalEvent`s → `SeededRandomEvent`s*, and
   within each group by ascending `world_event_id`.
3. `SeededRandomEvent` draws `rng_factory(...).random() < probability`.
4. Effects are returned in candidate order; `TriggerEvent` appends to `scheduled` instead of
   recursing, so one call is finite. `MutateCallerBelief` is dropped with no trace when the owning
   event has `caller_observable = false`.

Two gaps §10.11 leaves open are closed here without touching `advance`'s signature (see this
task's report, "HLD gaps"):

- **Which** events fired. `WORLD_EVENT_TRIGGERED` needs `world_event_id`/`occurrence` and each
  effect's owner decides `caller_observable`, but the flat `tuple[Effect, ...]` return carries
  neither. `WorldState.fired` therefore holds the `FiredEvent`s of **this call only** (it is reset
  at the start of every `advance`), and `WorldState.definitions` holds the scenario's event
  definitions, set at instantiation and never mutated. The flat effect tuple stays exactly as
  §10.11 prints it.
- **How a `SeededRandomEvent`'s draws are indexed.** A draw belongs to an *absolute* check tick
  `k`, the tick at `window_start_ms + k · check_every_ms`; a call draws for every `k` whose tick
  time lies in `(last_tick_ms, now_ms]` and inside the window. The draw index travels inside
  `rng_factory`'s `event_id` argument as `"<world_event_id>#<k>"`, so rule 3's hash formula is
  unchanged while the draw depends only on absolute simulation time — never on how the run was
  partitioned into ticks, nor on how many draws came before it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from random import Random

from pydantic import BaseModel, ConfigDict, Field

from app.domain.caller.emotion import EmotionRule
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import IncidentId, ResourceId
from app.domain.common.values import FactValue
from app.domain.dds.resources import EmergencyResource
from app.domain.enums import RoleType
from app.domain.events.types import EventType
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.world_truth import WorldTruth
from app.domain.world.conditions import ConditionContext, EventIndex, evaluate_condition
from app.domain.world.effects import Effect, MutateCallerBelief, TriggerEvent
from app.domain.world.events import (
    ActionTriggeredEvent,
    ConditionalEvent,
    SeededRandomEvent,
    TimedEvent,
    WorldEventDefinition,
)

__all__ = [
    "FiredEvent",
    "PendingAction",
    "ScheduledTrigger",
    "WorldState",
    "advance",
]


class PendingAction(BaseModel):
    """One action appended since the previous tick, as §10.11 prints it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: EventType
    at_offset_ms: int
    payload: Mapping[str, FactValue]
    actor: ActorRef


class ScheduledTrigger(BaseModel):
    """A future firing queued by a `TriggerEvent` effect or a delayed `ActionTriggeredEvent`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_event_id: str
    due_ms: int
    source_world_event_id: str | None = None


class FiredEvent(BaseModel):
    """One world event fired by the current `advance` call (see the module docstring).

    `effects` is the event's effect tuple **after** the `caller_observable` drop of rule 4, so
    `world/apply.py` never has to re-decide it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_event_id: str
    occurrence: int
    at_ms: int
    caller_observable: bool
    effects: tuple[Effect, ...]


class WorldState(BaseModel):
    """The engine's whole state, as §10.11 prints it plus `definitions`/`fired`/`emotion_rules`.

    `resource_keys` maps a scenario-local resource id to the runtime `ResourceId` that keys
    `resources` (see `ConditionContext`). `emotion_rules` is the caller profile's rule tuple, which
    `world/apply.py` runs through `apply_emotion_rules`; like `definitions` it is set at
    instantiation and never mutated.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    incident_id: IncidentId
    world_truth: WorldTruth
    caller_belief: CallerBelief
    resources: Mapping[ResourceId, EmergencyResource] = Field(default_factory=dict)
    resource_keys: Mapping[str, ResourceId] = Field(default_factory=dict)
    stage_states: Mapping[RoleType, str] = Field(default_factory=dict)
    reached_states: Mapping[RoleType, frozenset[str]] = Field(default_factory=dict)
    last_tick_ms: int = 0
    occurrences: Mapping[str, int] = Field(default_factory=dict)
    last_fired_ms: Mapping[str, int] = Field(default_factory=dict)
    scheduled: tuple[ScheduledTrigger, ...] = ()
    event_index: EventIndex = EventIndex()
    emotion_applications: Mapping[str, int] = Field(default_factory=dict)
    definitions: tuple[WorldEventDefinition, ...] = ()
    emotion_rules: tuple[EmotionRule, ...] = ()
    fired: tuple[FiredEvent, ...] = ()


def _definitions_by_id(state: WorldState) -> dict[str, WorldEventDefinition]:
    return {definition.world_event_id: definition for definition in state.definitions}


def _payload_matches(payload: Mapping[str, FactValue], match: Mapping[str, FactValue]) -> bool:
    return all(payload.get(key) == value for key, value in match.items())


def _seeded_random_tick_indices(
    event: SeededRandomEvent, last_tick_ms: int, now_ms: int
) -> list[int]:
    """Absolute check-tick indices `k` whose tick time lies in `(last_tick_ms, now_ms]` (rule 3).

    The indices are derived from absolute simulation time only, so they do not depend on how the
    interval was partitioned into `advance` calls.
    """
    start = event.window_start_ms
    end = now_ms if event.window_end_ms is None else min(now_ms, event.window_end_ms)
    if end < start:
        return []
    lowest = max(0, -(-(last_tick_ms + 1 - start) // event.check_every_ms))
    highest = (end - start) // event.check_every_ms
    return list(range(lowest, highest + 1)) if highest >= lowest else []


def _condition_context(state: WorldState, now_ms: int, event_index: EventIndex) -> ConditionContext:
    return ConditionContext(
        world_truth=state.world_truth,
        caller_belief=state.caller_belief,
        resources=state.resources,
        resource_keys=state.resource_keys,
        stage_states=state.stage_states,
        reached_states=state.reached_states,
        now_ms=now_ms,
        event_index=event_index,
    )


def _collect_candidates(
    state: WorldState,
    now_ms: int,
    pending_actions: Sequence[PendingAction],
    rng_factory: Callable[[str, int], Random],
    ctx: ConditionContext,
) -> tuple[list[WorldEventDefinition], list[ScheduledTrigger]]:
    """The fired candidates in determinism-rule-2 order, plus the triggers queued on the way."""
    by_id = _definitions_by_id(state)
    occurrences = state.occurrences
    candidates: list[WorldEventDefinition] = []
    queued: list[ScheduledTrigger] = []
    planned: dict[str, int] = {}

    def exhausted(definition: WorldEventDefinition) -> bool:
        already = occurrences.get(definition.world_event_id, 0)
        already += planned.get(definition.world_event_id, 0)
        return already >= definition.max_occurrences

    def elect(definition: WorldEventDefinition) -> None:
        candidates.append(definition)
        planned[definition.world_event_id] = planned.get(definition.world_event_id, 0) + 1

    # 1. due ScheduledTriggers
    due = sorted(
        (trigger for trigger in state.scheduled if trigger.due_ms <= now_ms),
        key=lambda trigger: (trigger.due_ms, trigger.world_event_id),
    )
    for trigger in due:
        definition = by_id.get(trigger.world_event_id)
        if definition is not None and not exhausted(definition):
            elect(definition)

    # 2. TimedEvents whose at_ms has passed. `at_ms` is one point in simulation time, so a
    #    TimedEvent fires at most once however large `max_occurrences` is (§30.6.3 #1).
    for definition in sorted(state.definitions, key=lambda event: event.world_event_id):
        if (
            isinstance(definition, TimedEvent)
            and definition.at_ms <= now_ms
            and not exhausted(definition)
        ):
            elect(definition)

    # 3. ActionTriggeredEvents matched by an action appended in this call
    for definition in sorted(state.definitions, key=lambda event: event.world_event_id):
        if not isinstance(definition, ActionTriggeredEvent) or exhausted(definition):
            continue
        matches = [
            action
            for action in pending_actions
            if action.event_type == definition.on_event_type
            and (
                definition.payload_match is None
                or _payload_matches(action.payload, definition.payload_match)
            )
        ]
        if not matches:
            continue
        if definition.delay_ms > 0:
            queued.extend(
                ScheduledTrigger(
                    world_event_id=definition.world_event_id,
                    due_ms=action.at_offset_ms + definition.delay_ms,
                    source_world_event_id=None,
                )
                for action in sorted(matches, key=lambda action: action.at_offset_ms)
            )
            continue
        elect(definition)

    # 4. ConditionalEvents whose condition holds
    for definition in sorted(state.definitions, key=lambda event: event.world_event_id):
        if not isinstance(definition, ConditionalEvent) or exhausted(definition):
            continue
        if now_ms < definition.check_after_ms:
            continue
        previous = state.last_fired_ms.get(definition.world_event_id)
        if previous is not None and now_ms < previous + definition.cooldown_ms:
            continue
        if evaluate_condition(definition.condition, ctx):
            elect(definition)

    # 5. SeededRandomEvents whose check tick elapsed
    for definition in sorted(state.definitions, key=lambda event: event.world_event_id):
        if not isinstance(definition, SeededRandomEvent) or exhausted(definition):
            continue
        if definition.condition is not None and not evaluate_condition(definition.condition, ctx):
            continue
        occurrence = occurrences.get(definition.world_event_id, 0)
        indices = _seeded_random_tick_indices(definition, state.last_tick_ms, now_ms)
        for index in indices:
            draw = rng_factory(f"{definition.world_event_id}#{index}", occurrence).random()
            if draw < definition.probability:
                elect(definition)
                break

    return candidates, queued


def advance(
    state: WorldState,
    now_ms: int,
    pending_actions: Sequence[PendingAction],
    rng_factory: Callable[[str, int], Random],
) -> tuple[WorldState, tuple[Effect, ...]]:
    """Advance the world to `now_ms` (§10.11 determinism rules 1-4).

    Returns the new state — whose `fired` holds the `FiredEvent`s of this call only — and the flat
    effect tuple in candidate order, with non-observable `MutateCallerBelief` effects already
    dropped. Raises `DomainError` when `now_ms` is before `state.last_tick_ms`: simulated time
    never goes back.
    """
    if now_ms < state.last_tick_ms:
        raise DomainError(
            f"advance: now_ms {now_ms} is before last_tick_ms {state.last_tick_ms}; "
            f"simulated time never goes back"
        )

    event_index = EventIndex.fold(pending_actions, base=state.event_index)
    ctx = _condition_context(state, now_ms, event_index)
    candidates, queued = _collect_candidates(state, now_ms, pending_actions, rng_factory, ctx)

    occurrences = dict(state.occurrences)
    last_fired_ms = dict(state.last_fired_ms)
    scheduled = [trigger for trigger in state.scheduled if trigger.due_ms > now_ms]
    scheduled.extend(queued)
    fired: list[FiredEvent] = []
    effects: list[Effect] = []

    for definition in candidates:
        occurrence = occurrences.get(definition.world_event_id, 0)
        kept = tuple(
            effect
            for effect in definition.effects
            if definition.caller_observable or not isinstance(effect, MutateCallerBelief)
        )
        occurrences[definition.world_event_id] = occurrence + 1
        last_fired_ms[definition.world_event_id] = now_ms
        fired.append(
            FiredEvent(
                world_event_id=definition.world_event_id,
                occurrence=occurrence,
                at_ms=now_ms,
                caller_observable=definition.caller_observable,
                effects=kept,
            )
        )
        effects.extend(kept)
        scheduled.extend(
            ScheduledTrigger(
                world_event_id=effect.world_event_id,
                due_ms=now_ms + effect.delay_ms,
                source_world_event_id=definition.world_event_id,
            )
            for effect in kept
            if isinstance(effect, TriggerEvent)
        )

    new_state = state.model_copy(
        update={
            "last_tick_ms": now_ms,
            "occurrences": occurrences,
            "last_fired_ms": last_fired_ms,
            "scheduled": tuple(
                sorted(scheduled, key=lambda trigger: (trigger.due_ms, trigger.world_event_id))
            ),
            "event_index": event_index,
            "fired": tuple(fired),
        }
    )
    return new_state, tuple(effects)
