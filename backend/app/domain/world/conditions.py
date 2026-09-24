"""The `Condition` expression language (HLD `10-domain-model.md` §10.11, `30-scenario-format.md`
§30.6.1).

A small closed declarative structure: two combinators (`all`, `any`, `not`) and five leaves
(`fact`, `resource`, `stage`, `sim_time`, `action`). No `eval`, no code strings, no lambdas in
scenario data. Every node is exactly one kind; `model_config = ConfigDict(extra="forbid")`
rejects unknown keys, and a model validator rejects a node naming more than one kind at once.

`evaluate_condition(cond, ctx) -> bool` is **total and pure**: it never raises and never reads a
clock, a repository or `random`. An unknown fact, an unknown resource and an unknown role all
evaluate `False` (with the one documented exception that `IS_NULL` is `True` for an absent fact —
"the fact has no value" is exactly what an absent fact means).

`EventIndex` is the folded projection of the session's actions that the `action` leaf reads: per
`EventType` a count, the first and last offset, and the per-occurrence `(at_offset_ms, payload)`
pairs that `within_ms` and `payload_equals` need. It is immutable and is built only by folding
actions (`EventIndex.fold`), so two runs that saw the same timestamped actions hold the same index
whatever the tick partition was.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.common.ids import ResourceId
from app.domain.common.values import FactValue
from app.domain.dds.resources import EmergencyResource
from app.domain.enums import ResourceStatus, RoleType
from app.domain.events.types import EventType
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.world_truth import WorldTruth

FactOp = Literal["EQ", "NEQ", "GT", "GTE", "LT", "LTE", "IN", "IS_NULL", "IS_NOT_NULL"]
FactLayer = Literal["WORLD", "CALLER"]
ResourceOp = Literal["ANY_IS", "ALL_ARE", "NONE_IS", "COUNT_GTE"]
StageRole = Literal["OPERATOR_112", "DDS", "EDDS"]
StageOp = Literal["IS", "IS_NOT", "REACHED"]
SimTimeOp = Literal["GTE", "LT"]
ActionOp = Literal["OCCURRED", "NOT_OCCURRED", "COUNT_GTE"]


class FactCondition(BaseModel):
    """`{"fact": {"fact_id", "layer", "op", "value"}}` (§10.11)."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str
    layer: FactLayer
    op: FactOp
    value: FactValue | list[FactValue] | None = None


class ResourceSelectorById(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str


class ResourceSelectorByCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str


class ResourceSelectorByServiceType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_type: str


class ResourceSelector(BaseModel):
    """`{"resource_id": str} | {"capability": str} | {"service_type": str}` (§10.11).

    Exactly one of the three keys, enforced the same way as `Condition` itself.
    """

    model_config = ConfigDict(extra="forbid")

    resource_id: str | None = None
    capability: str | None = None
    service_type: str | None = None

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> ResourceSelector:
        chosen = [self.resource_id, self.capability, self.service_type]
        if sum(1 for value in chosen if value is not None) != 1:
            raise ValueError(
                "resource selector must set exactly one of resource_id, capability, service_type"
            )
        return self


class ResourceCondition(BaseModel):
    """`{"resource": {"selector", "op", "status", "count"}}` (§10.11)."""

    model_config = ConfigDict(extra="forbid")

    selector: ResourceSelector
    op: ResourceOp
    status: ResourceStatus
    count: int | None = None


class StageCondition(BaseModel):
    """`{"stage": {"role", "op", "state"}}` (§10.11)."""

    model_config = ConfigDict(extra="forbid")

    role: StageRole
    op: StageOp
    state: str


class SimTimeCondition(BaseModel):
    """`{"sim_time": {"op", "ms"}}` (§10.11)."""

    model_config = ConfigDict(extra="forbid")

    op: SimTimeOp
    ms: int


class ActionCondition(BaseModel):
    """`{"action": {"event_type", "op", "count", "within_ms", "payload_equals"}}` (§10.11)."""

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    op: ActionOp
    count: int | None = None
    within_ms: int | None = None
    payload_equals: Mapping[str, FactValue] | None = None


class Condition(BaseModel):
    """The closed `Condition` structure (§10.11).

    Exactly one of the combinators (`all`, `any`, `not`) or leaves (`fact`, `resource`, `stage`,
    `sim_time`, `action`) may be set on a given node. `not` is aliased to the field `not_` because
    `not` is a Python keyword.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    all: list[Condition] | None = None
    any: list[Condition] | None = None
    not_: Condition | None = Field(default=None, alias="not")
    fact: FactCondition | None = None
    resource: ResourceCondition | None = None
    stage: StageCondition | None = None
    sim_time: SimTimeCondition | None = None
    action: ActionCondition | None = None

    @model_validator(mode="after")
    def _exactly_one_kind(self) -> Condition:
        kinds = (
            self.all,
            self.any,
            self.not_,
            self.fact,
            self.resource,
            self.stage,
            self.sim_time,
            self.action,
        )
        chosen = sum(1 for kind in kinds if kind is not None)
        if chosen != 1:
            raise ValueError(
                f"Condition node must set exactly one of all/any/not/fact/resource/stage/"
                f"sim_time/action, got {chosen}"
            )
        return self


# ---------------------------------------------------------------------------------------------
# EventIndex — the folded action projection the `action` leaf reads (§10.11)
# ---------------------------------------------------------------------------------------------


class IndexableAction(Protocol):
    """The three attributes `EventIndex.fold` reads off an action.

    `engine.PendingAction` satisfies it structurally; typing it as a `Protocol` keeps
    `conditions.py` free of an import back from `engine.py` (which imports this module).
    """

    @property
    def event_type(self) -> EventType: ...

    @property
    def at_offset_ms(self) -> int: ...

    @property
    def payload(self) -> Mapping[str, FactValue]: ...


class ActionOccurrence(BaseModel):
    """One folded action: when it happened and the payload `payload_equals` compares against."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    at_offset_ms: int
    payload: Mapping[str, FactValue]


class EventIndex(BaseModel):
    """Counts, first/last offsets and per-occurrence payloads per `EventType` (§10.11).

    Immutable, and built only by folding actions. `fold` sorts its input by
    `(at_offset_ms, event_type, seq)` — determinism rule 1 — and appends it to `base`, so folding
    the same actions in two different tick partitions yields the same index.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    occurrences: Mapping[EventType, tuple[ActionOccurrence, ...]] = Field(default_factory=dict)

    @classmethod
    def fold(cls, actions: Sequence[IndexableAction], base: EventIndex | None = None) -> EventIndex:
        """Fold `actions` into `base` (an empty index by default), in determinism-rule-1 order."""
        folded: dict[EventType, tuple[ActionOccurrence, ...]] = (
            dict(base.occurrences) if base is not None else {}
        )
        ordered = sorted(
            enumerate(actions), key=lambda pair: (pair[1].at_offset_ms, pair[1].event_type, pair[0])
        )
        for _seq, action in ordered:
            occurrence = ActionOccurrence(
                at_offset_ms=action.at_offset_ms, payload=dict(action.payload)
            )
            folded[action.event_type] = (*folded.get(action.event_type, ()), occurrence)
        return cls(occurrences=folded)

    def count(self, event_type: EventType) -> int:
        """How many times `event_type` was appended."""
        return len(self.occurrences.get(event_type, ()))

    def first_offset_ms(self, event_type: EventType) -> int | None:
        """The offset of the first `event_type` occurrence, or `None` when there is none."""
        found = self.occurrences.get(event_type, ())
        return found[0].at_offset_ms if found else None

    def last_offset_ms(self, event_type: EventType) -> int | None:
        """The offset of the last `event_type` occurrence, or `None` when there is none."""
        found = self.occurrences.get(event_type, ())
        return found[-1].at_offset_ms if found else None


# ---------------------------------------------------------------------------------------------
# ConditionContext
# ---------------------------------------------------------------------------------------------


class LoggedAction(BaseModel):
    """An `IndexableAction` built straight from a persisted event (E17 R3).

    The one shape both builders of an `EventIndex` produce: `world_state_loader`, which folds the
    session's log for the world engine, and `dialogue_context`, which folds it for the fact gate.
    Having it here rather than in either of them is what keeps the two from drifting — and what
    lets the second one exist at all, since D3 forbids the dialogue slice from importing the
    module that holds the world-truth repository.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: EventType
    at_offset_ms: int
    payload: Mapping[str, FactValue] = Field(default_factory=dict)


def fact_payload(payload: Mapping[str, object]) -> dict[str, FactValue]:
    """The `FactValue`-shaped subset of a persisted payload (§10.11 `payload_match`).

    `session_events.payload` is free-form jsonb and several event types carry nested structures
    (`WORLD_TRUTH_MUTATED.changes`, for instance), while a `payload_match` and an `action`
    condition's `payload_equals` are `Mapping[str, FactValue]` — scalars and string lists. Keeping
    only the entries a match could ever compare against is lossless for the engine and keeps the
    action inside its declared type.
    """
    kept: dict[str, FactValue] = {}
    for key, value in payload.items():
        if value is None or isinstance(value, str | int | float | bool):
            kept[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            kept[key] = list(value)
    return kept


class ConditionContext(BaseModel):
    """Everything `evaluate_condition` may read (§10.11). Never carries a repository or a clock.

    `resource_keys` maps a **scenario-local** resource id (the `resource_id` a `ResourceSelector`
    or an `AlterResourceAvailability` effect names, e.g. `"ac2"`) to the runtime `ResourceId` that
    keys `resources`. §10.7's `EmergencyResource` has no scenario-local id field although
    `emergency_resources.scenario_resource_id` exists at rest (`20-db-schema.md` §20.5), so the
    mapping has to travel beside the board — see this task's report, "HLD gaps". When it does not
    hold a selector's id, the id is tried as a runtime `ResourceId` rendered as text before the
    selector is declared unknown (and an unknown selector evaluates `False`).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    world_truth: WorldTruth | None = None
    caller_belief: CallerBelief | None = None
    """The two information layers, **optional since E17 R3**.

    A context assembled from the session event log alone — the one the fact gate's `available_after`
    is evaluated in (`app.application.dialogue.dialogue_context`) — legitimately holds no
    `WorldTruth`: D3 forbids the dialogue slice from reaching one at all. An absent layer makes
    every `fact` condition against it `False`, for every operator including `IS_NULL`: "I cannot
    see this layer" is not "this fact has no value", and a gate must not open a fact on a
    layer it never read. Scenario validation (§30.8 rule 31) refuses an `available_after` that
    would depend on a layer the gate cannot see, so no scenario can reach that `False` by
    accident."""
    resources: Mapping[ResourceId, EmergencyResource] = Field(default_factory=dict)
    resource_keys: Mapping[str, ResourceId] = Field(default_factory=dict)
    stage_states: Mapping[RoleType, str] = Field(default_factory=dict)
    reached_states: Mapping[RoleType, frozenset[str]] = Field(default_factory=dict)
    now_ms: int = 0
    event_index: EventIndex = EventIndex()


# ---------------------------------------------------------------------------------------------
# evaluate_condition
# ---------------------------------------------------------------------------------------------


def _as_number(value: object) -> float | None:
    """`value` as a float for an ordering comparison, or `None` when it is not ordered."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _evaluate_fact(cond: FactCondition, ctx: ConditionContext) -> bool:
    layer = ctx.world_truth if cond.layer == "WORLD" else ctx.caller_belief
    if layer is None:
        # The context was not given this layer at all (E17 R3) — see `ConditionContext`.
        return False
    facts: Mapping[str, FactValue] = layer.facts
    present = cond.fact_id in facts
    actual = facts.get(cond.fact_id)
    if cond.op == "IS_NULL":
        return not present or actual is None
    if cond.op == "IS_NOT_NULL":
        return present and actual is not None
    if not present:
        return False
    if cond.op == "EQ":
        return bool(actual == cond.value)
    if cond.op == "NEQ":
        return bool(actual != cond.value)
    if cond.op == "IN":
        if not isinstance(cond.value, list):
            return False
        return actual in cond.value
    left = _as_number(actual)
    right = _as_number(cond.value)
    if left is None or right is None:
        return False
    if cond.op == "GT":
        return left > right
    if cond.op == "GTE":
        return left >= right
    if cond.op == "LT":
        return left < right
    return left <= right  # "LTE" — the ops literal is closed


def _select_resources(
    selector: ResourceSelector, ctx: ConditionContext
) -> tuple[EmergencyResource, ...]:
    """Every resource `selector` names, in ascending runtime id order (never raises)."""
    if selector.resource_id is not None:
        resolved = resolve_resource_id(selector.resource_id, ctx.resources, ctx.resource_keys)
        if resolved is None:
            return ()
        return (ctx.resources[resolved],)
    ordered = tuple(
        resource for _key, resource in sorted(ctx.resources.items(), key=lambda item: str(item[0]))
    )
    if selector.capability is not None:
        wanted_capability = selector.capability
        return tuple(
            resource
            for resource in ordered
            if any(capability.value == wanted_capability for capability in resource.capabilities)
        )
    wanted_service = selector.service_type
    return tuple(resource for resource in ordered if resource.service_type == wanted_service)


def resolve_resource_id(
    scenario_resource_id: str,
    resources: Mapping[ResourceId, EmergencyResource],
    resource_keys: Mapping[str, ResourceId],
) -> ResourceId | None:
    """Resolve a scenario-local resource id to a key of `resources`, or `None` when unknown.

    `resource_keys` wins; otherwise the id is tried as a runtime `ResourceId` rendered as text.
    Shared by `evaluate_condition` and by `AlterResourceAvailability` in `world/apply.py`.
    """
    mapped = resource_keys.get(scenario_resource_id)
    if mapped is not None and mapped in resources:
        return mapped
    for key in resources:
        if str(key) == scenario_resource_id:
            return key
    return None


def _evaluate_resource(cond: ResourceCondition, ctx: ConditionContext) -> bool:
    selected = _select_resources(cond.selector, ctx)
    if not selected:
        # An unknown or empty selection is False for every operator, `NONE_IS` included: the
        # engine must never fire on a vacuous truth about resources that are not on the board.
        return False
    matching = sum(1 for resource in selected if resource.current_status == cond.status)
    if cond.op == "ANY_IS":
        return matching >= 1
    if cond.op == "ALL_ARE":
        return matching == len(selected)
    if cond.op == "NONE_IS":
        return matching == 0
    return matching >= (cond.count if cond.count is not None else 1)  # "COUNT_GTE"


def _evaluate_stage(cond: StageCondition, ctx: ConditionContext) -> bool:
    try:
        role = RoleType(cond.role)
    except ValueError:  # pragma: no cover - `StageRole` is exactly `RoleType`'s member set
        return False
    if role not in ctx.stage_states:
        return False
    current = ctx.stage_states[role]
    if cond.op == "IS":
        return current == cond.state
    if cond.op == "IS_NOT":
        return current != cond.state
    return current == cond.state or cond.state in ctx.reached_states.get(role, frozenset())


def _evaluate_action(cond: ActionCondition, ctx: ConditionContext) -> bool:
    occurrences = ctx.event_index.occurrences.get(cond.event_type, ())
    if cond.within_ms is not None:
        horizon = ctx.now_ms - cond.within_ms
        occurrences = tuple(
            occurrence for occurrence in occurrences if occurrence.at_offset_ms >= horizon
        )
    if cond.payload_equals is not None:
        wanted = cond.payload_equals
        occurrences = tuple(
            occurrence
            for occurrence in occurrences
            if all(occurrence.payload.get(key) == value for key, value in wanted.items())
        )
    matched = len(occurrences)
    if cond.op == "OCCURRED":
        return matched >= 1
    if cond.op == "NOT_OCCURRED":
        return matched == 0
    return matched >= (cond.count if cond.count is not None else 1)  # "COUNT_GTE"


def evaluate_condition(cond: Condition, ctx: ConditionContext) -> bool:
    """Evaluate one `Condition` against `ctx` (§10.11). Total and pure: it never raises.

    An unknown fact, an unknown resource and an unknown role evaluate `False`; the single
    exception is `IS_NULL`, which is `True` for a fact the layer does not hold at all.
    """
    if cond.all is not None:
        return all(evaluate_condition(child, ctx) for child in cond.all)
    if cond.any is not None:
        return any(evaluate_condition(child, ctx) for child in cond.any)
    if cond.not_ is not None:
        return not evaluate_condition(cond.not_, ctx)
    if cond.fact is not None:
        return _evaluate_fact(cond.fact, ctx)
    if cond.resource is not None:
        return _evaluate_resource(cond.resource, ctx)
    if cond.stage is not None:
        return _evaluate_stage(cond.stage, ctx)
    if cond.sim_time is not None:
        if cond.sim_time.op == "GTE":
            return ctx.now_ms >= cond.sim_time.ms
        return ctx.now_ms < cond.sim_time.ms
    if cond.action is not None:
        return _evaluate_action(cond.action, ctx)
    return False  # pragma: no cover - `_exactly_one_kind` makes this unreachable
