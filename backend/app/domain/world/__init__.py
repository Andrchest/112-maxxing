"""World event engine (HLD `10-domain-model.md` §10.11): conditions, effects, events, `advance`."""

from app.domain.world.apply import ApplyResult, SkippedTransition, apply_effects
from app.domain.world.conditions import (
    ActionCondition,
    ActionOccurrence,
    Condition,
    ConditionContext,
    EventIndex,
    FactCondition,
    ResourceCondition,
    ResourceSelector,
    SimTimeCondition,
    StageCondition,
    evaluate_condition,
)
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
from app.domain.world.engine import (
    FiredEvent,
    PendingAction,
    ScheduledTrigger,
    WorldState,
    advance,
)
from app.domain.world.eta import EtaModel, ScenarioDefinedEta
from app.domain.world.events import (
    ActionTriggeredEvent,
    ConditionalEvent,
    SeededRandomEvent,
    TimedEvent,
    WorldEventDefinition,
)
from app.domain.world.resource_movement import advance_resources
from app.domain.world.rng import rng_for

__all__ = [
    "ActionCondition",
    "ActionOccurrence",
    "ActionTriggeredEvent",
    "AlterResourceAvailability",
    "ApplyResult",
    "CallerFactChange",
    "ChangeCallerEmotion",
    "Condition",
    "ConditionContext",
    "ConditionalEvent",
    "CreateNotification",
    "CreateRadioMessage",
    "Effect",
    "EtaModel",
    "EventIndex",
    "FactCondition",
    "FiredEvent",
    "MutateCallerBelief",
    "MutateWorldTruth",
    "PendingAction",
    "ResourceCondition",
    "ResourceSelector",
    "ScenarioDefinedEta",
    "ScheduledTrigger",
    "SeededRandomEvent",
    "SimTimeCondition",
    "SkippedTransition",
    "StageCondition",
    "TimedEvent",
    "TriggerEvent",
    "WorldEventDefinition",
    "WorldState",
    "advance",
    "advance_resources",
    "apply_effects",
    "evaluate_condition",
    "rng_for",
]
