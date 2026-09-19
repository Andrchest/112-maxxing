"""The `Condition` expression language (HLD `10-domain-model.md` §10.11, `30-scenario-format.md`
§30.6.1).

A small closed declarative structure: two combinators (`all`, `any`, `not`) and five leaves
(`fact`, `resource`, `stage`, `sim_time`, `action`). No `eval`, no code strings, no lambdas in
scenario data. Every node is exactly one kind; `model_config = ConfigDict(extra="forbid")`
rejects unknown keys, and a model validator rejects a node naming more than one kind at once.

Only the data structure lives here. `evaluate_condition` and `ConditionContext` interpret it and
are out of scope for this slice.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.common.values import FactValue
from app.domain.enums import ResourceStatus
from app.domain.events.types import EventType

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


# TODO(E6): evaluate_condition / ConditionContext (HLD 10.11)
