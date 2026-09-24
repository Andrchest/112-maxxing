"""`ResourceCapability`, `EtaProfile`, `ResourceAvailability`, `EmergencyResource`,
`RESOURCE_STATUS_TRANSITIONS`, `RESOURCE_GUARDS`, `RESOURCE_STATE_MACHINE`
(HLD `10-domain-model.md` §10.7, SPEC §11).

The per-resource event timestamps §10.7's guard column names (`dispatched_at`, `departed_at`,
`arrived_at`, `work_started_at`, `returning_at`) have exactly one home: **each of them is the
moment the resource entered its current status**, so one field — `status_changed_at_offset_ms`,
which `emergency_resources` already carries at rest (`20-db-schema.md` §20.5) — expresses all
five, and every timed guard reads `now_ms >= status_changed_at_offset_ms + <duration>·1000`. A
resource can only be in one of `DISPATCHED`/`EN_ROUTE`/`ON_SCENE`/`WORKING`/`RETURNING` at a time,
so no second timestamp can ever be the one a guard needs.

`RESOURCE_GUARDS` registers a callable for **every** `guard_name` in
`RESOURCE_STATUS_TRANSITIONS` (`StateMachine` denies a transition whose named guard is missing, so
an unregistered name would silently freeze the board), exactly as `session/guards.py` does for the
three session machines. Two context conventions are specific to this machine and are the reason a
resource guard is never mixed with a session guard:

- `GuardContext.resources` carries **exactly one** entry: the resource whose transition is being
  fired. (`session/guards.py` reads the same field as the whole board; the two machines are
  never given the same context.)
- `GuardContext.world_flags` carries the simulation-side verdicts the domain cannot derive from
  the resource alone: `availability_effect` / `restore_effect` (an `AlterResourceAvailability`
  effect targeted this resource, with `restore = true`) and `assignment_resolved` (the DDS
  assignment reached `RESOLVED`).

Durations come from an `EtaModel` (`world/eta.py`, D7); `build_resource_guards(eta_model)` binds
one, and the default `RESOURCE_GUARDS` reads `EmergencyResource.eta` verbatim — the same five
values `ScenarioDefinedEta` reads. `world/eta.py` is imported under `TYPE_CHECKING` only, because
`app.domain.world.__init__` imports the engine, which imports this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import ResourceId
from app.domain.common.state_machine import (
    GuardContext,
    StateMachine,
    Transition,
    TransitionTable,
)
from app.domain.enums import (
    ActorType,
    DDSStageState,
    ResourceStatus,
    ResourceType,
    RoleType,
    ServiceId,
)
from app.domain.events.types import EventType

if TYPE_CHECKING:  # pragma: no cover - typing only; see the module docstring
    from app.domain.world.eta import EtaModel

_TRAINEE_DDS = frozenset({ActorType.TRAINEE})
_DDS_ROLE = frozenset({RoleType.DDS})
_SIMULATION = frozenset({ActorType.SIMULATION})


class ResourceCapability(str, Enum):
    """§10.7, exact."""

    FIRE_SUPPRESSION = "FIRE_SUPPRESSION"
    HIGH_RISE_ACCESS = "HIGH_RISE_ACCESS"
    LADDER_RESCUE = "LADDER_RESCUE"
    TECHNICAL_RESCUE = "TECHNICAL_RESCUE"
    SMOKE_DIVING = "SMOKE_DIVING"
    BASIC_LIFE_SUPPORT = "BASIC_LIFE_SUPPORT"
    ADVANCED_LIFE_SUPPORT = "ADVANCED_LIFE_SUPPORT"
    BURN_CARE = "BURN_CARE"
    PUBLIC_ORDER = "PUBLIC_ORDER"
    TRAFFIC_CONTROL = "TRAFFIC_CONTROL"
    AREA_CORDON = "AREA_CORDON"
    GAS_SHUTOFF = "GAS_SHUTOFF"
    GAS_LEAK_DETECTION = "GAS_LEAK_DETECTION"
    POWER_SHUTOFF = "POWER_SHUTOFF"
    WATER_SUPPLY = "WATER_SUPPLY"
    COMMAND_AND_CONTROL = "COMMAND_AND_CONTROL"


class EtaProfile(BaseModel):
    """The five ETA inputs `ScenarioDefinedEta` reads verbatim (§10.7)."""

    model_config = ConfigDict(frozen=True)

    turnout_delay_seconds: int
    travel_time_seconds: int
    setup_seconds: int
    on_scene_work_seconds: int
    return_time_seconds: int


class ResourceAvailability(BaseModel):
    """Scenario-defined availability window (§10.7)."""

    model_config = ConfigDict(frozen=True)

    available_from_ms: int = 0
    available_until_ms: int | None = None
    initial_status: ResourceStatus = ResourceStatus.AVAILABLE


class EmergencyResource(BaseModel):
    """SPEC §11's minimum `EmergencyResource` fields, exactly as §10.7 lists them."""

    model_config = ConfigDict(frozen=True)

    resource_id: ResourceId
    service_type: ServiceId
    resource_type: ResourceType
    callsign: str
    name_ru: str
    capabilities: frozenset[ResourceCapability]
    current_status: ResourceStatus
    availability: ResourceAvailability
    eta: EtaProfile
    home_station_ru: str
    crew_size: int
    status_changed_at_offset_ms: int = 0
    """When `current_status` was entered — the one home of §10.7's `dispatched_at`, `departed_at`,
    `arrived_at`, `work_started_at` and `returning_at` (see the module docstring)."""


# ---------------------------------------------------------------------------------------------
# Resource status state machine (§10.7 "Resource status state machine")
# ---------------------------------------------------------------------------------------------

_BREAKDOWN_SOURCE_STATES: tuple[ResourceStatus, ...] = (
    ResourceStatus.DISPATCHED,
    ResourceStatus.EN_ROUTE,
    ResourceStatus.ON_SCENE,
    ResourceStatus.WORKING,
)

_RESOURCE_STATUS_ROWS: tuple[Transition[ResourceStatus], ...] = (
    Transition(
        source=ResourceStatus.AVAILABLE,
        trigger="select",
        target=ResourceStatus.SELECTED,
        allowed_actors=_TRAINEE_DDS,
        allowed_roles=_DDS_ROLE,
        guard_name="guard_selection_open_and_within_availability_window",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
    Transition(
        source=ResourceStatus.SELECTED,
        trigger="deselect",
        target=ResourceStatus.AVAILABLE,
        allowed_actors=_TRAINEE_DDS,
        allowed_roles=_DDS_ROLE,
        guard_name="guard_not_yet_dispatched",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
    Transition(
        source=ResourceStatus.SELECTED,
        trigger="dispatch",
        target=ResourceStatus.DISPATCHED,
        allowed_actors=_TRAINEE_DDS,
        allowed_roles=_DDS_ROLE,
        guard_name="guard_selection_open",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
    Transition(
        source=ResourceStatus.DISPATCHED,
        trigger="depart",
        target=ResourceStatus.EN_ROUTE,
        allowed_actors=_SIMULATION,
        guard_name="guard_turnout_delay_elapsed",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
    Transition(
        source=ResourceStatus.EN_ROUTE,
        trigger="arrive",
        target=ResourceStatus.ON_SCENE,
        allowed_actors=_SIMULATION,
        guard_name="guard_travel_time_elapsed",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
    Transition(
        source=ResourceStatus.ON_SCENE,
        trigger="start_work",
        target=ResourceStatus.WORKING,
        allowed_actors=_SIMULATION,
        guard_name="guard_setup_time_elapsed",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
    Transition(
        source=ResourceStatus.WORKING,
        trigger="finish_work",
        target=ResourceStatus.RETURNING,
        allowed_actors=_SIMULATION,
        guard_name="guard_work_time_elapsed_or_assignment_resolved",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
    Transition(
        source=ResourceStatus.RETURNING,
        trigger="return_to_base",
        target=ResourceStatus.AVAILABLE,
        allowed_actors=_SIMULATION,
        guard_name="guard_return_time_elapsed",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
    *(
        Transition(
            source=state,
            trigger="breakdown",
            target=ResourceStatus.OUT_OF_SERVICE,
            allowed_actors=_SIMULATION,
            guard_name="guard_availability_effect_applied",
            emits=EventType.RESOURCE_STATUS_CHANGED,
        )
        for state in _BREAKDOWN_SOURCE_STATES
    ),
    Transition(
        source=ResourceStatus.OUT_OF_SERVICE,
        trigger="repair",
        target=ResourceStatus.AVAILABLE,
        allowed_actors=_SIMULATION,
        guard_name="guard_restore_effect_applied",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
    Transition(
        source=ResourceStatus.AVAILABLE,
        trigger="make_unavailable",
        target=ResourceStatus.UNAVAILABLE,
        allowed_actors=_SIMULATION,
        guard_name="guard_outside_availability_window_or_effect",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
    Transition(
        source=ResourceStatus.UNAVAILABLE,
        trigger="make_available",
        target=ResourceStatus.AVAILABLE,
        allowed_actors=_SIMULATION,
        guard_name="guard_inside_availability_window_or_effect",
        emits=EventType.RESOURCE_STATUS_CHANGED,
    ),
)

RESOURCE_STATUS_TRANSITIONS: TransitionTable[ResourceStatus] = {
    (row.source, row.trigger): row for row in _RESOURCE_STATUS_ROWS
}


# ---------------------------------------------------------------------------------------------
# Guard callables and the wired machine (§10.7 guard column; same idiom as `session/guards.py`)
# ---------------------------------------------------------------------------------------------


class _DefaultEta:
    """`ScenarioDefinedEta`'s reading of `EmergencyResource.eta`, without importing it (§10.7)."""

    def turnout_delay_ms(self, resource: EmergencyResource) -> int:
        return resource.eta.turnout_delay_seconds * 1000

    def travel_time_ms(self, resource: EmergencyResource) -> int:
        return resource.eta.travel_time_seconds * 1000

    def setup_ms(self, resource: EmergencyResource) -> int:
        return resource.eta.setup_seconds * 1000

    def on_scene_work_ms(self, resource: EmergencyResource) -> int:
        return resource.eta.on_scene_work_seconds * 1000

    def return_time_ms(self, resource: EmergencyResource) -> int:
        return resource.eta.return_time_seconds * 1000


def subject_resource(ctx: GuardContext) -> EmergencyResource | None:
    """The single resource `ctx` is about, or `None` when the context does not name exactly one."""
    board = ctx.resources
    if board is None or len(board) != 1:
        return None
    only = next(iter(board.values()))
    return only if isinstance(only, EmergencyResource) else None


def within_availability_window(resource: EmergencyResource, now_ms: int) -> bool:
    """`now_ms` lies inside the scenario-defined availability window (§10.7)."""
    window = resource.availability
    if now_ms < window.available_from_ms:
        return False
    return window.available_until_ms is None or now_ms < window.available_until_ms


SELECTION_OPEN_STATES: frozenset[DDSStageState] = frozenset(
    {
        DDSStageState.RESOURCE_SELECTION,
        DDSStageState.EN_ROUTE,
        DDSStageState.ARRIVED,
        DDSStageState.WORKING,
    }
)
"""The assignment states in which a unit may be selected and dispatched (§10.7, repair E9).

§10.7 originally named `RESOURCE_SELECTION` alone, which made `dispatch_additional` unreachable:
its guard needs a `SELECTED` unit, and no unit could become `SELECTED` in `EN_ROUTE` / `ARRIVED` /
`WORKING`, the three states it fires from. The repair widens these two unit-level guards and adds
`select_resource` / `deselect_resource` to §10.9's `available_actions` for those states
(`roles/dds.py`); `deselect` is untouched, so a unit already dispatched still cannot be un-sent.
"""


def _assignment_state(ctx: GuardContext) -> Any:
    """`ctx.assignment.state`, read loosely — `assignment` is `Any` (§10.8, E3 ruling)."""
    return getattr(ctx.assignment, "state", None)


def _assignment_resolved(ctx: GuardContext) -> bool:
    if ctx.world_flags.get("assignment_resolved", False):
        return True
    return _assignment_state(ctx) in (DDSStageState.RESOLVED, DDSStageState.CLOSED)


def build_resource_guards(
    eta_model: EtaModel | None = None,
) -> Mapping[str, Callable[[GuardContext], bool]]:
    """Every `RESOURCE_STATUS_TRANSITIONS` guard, bound to `eta_model` (default: §10.7 verbatim)."""
    eta: EtaModel = _DefaultEta() if eta_model is None else eta_model

    def _elapsed(ctx: GuardContext, duration_ms: Callable[[EmergencyResource], int]) -> bool:
        resource = subject_resource(ctx)
        if resource is None:
            return False
        return ctx.now_ms >= resource.status_changed_at_offset_ms + duration_ms(resource)

    def guard_selection_open_and_within_availability_window(ctx: GuardContext) -> bool:
        """`AVAILABLE --select--> SELECTED` (§10.7)."""
        resource = subject_resource(ctx)
        if resource is None:
            return False
        if _assignment_state(ctx) not in SELECTION_OPEN_STATES:
            return False
        return within_availability_window(resource, ctx.now_ms)

    def guard_not_yet_dispatched(ctx: GuardContext) -> bool:
        """`SELECTED --deselect--> AVAILABLE`: the resource is not in `dispatched_resource_ids`."""
        resource = subject_resource(ctx)
        if resource is None:
            return False
        dispatched = getattr(ctx.assignment, "dispatched_resource_ids", ())
        return resource.resource_id not in tuple(dispatched)

    def guard_selection_open(ctx: GuardContext) -> bool:
        """`SELECTED --dispatch--> DISPATCHED` (§10.7, widened by the E9 repair)."""
        return _assignment_state(ctx) in SELECTION_OPEN_STATES

    def guard_turnout_delay_elapsed(ctx: GuardContext) -> bool:
        """`DISPATCHED --depart--> EN_ROUTE`."""
        return _elapsed(ctx, eta.turnout_delay_ms)

    def guard_travel_time_elapsed(ctx: GuardContext) -> bool:
        """`EN_ROUTE --arrive--> ON_SCENE`."""
        return _elapsed(ctx, eta.travel_time_ms)

    def guard_setup_time_elapsed(ctx: GuardContext) -> bool:
        """`ON_SCENE --start_work--> WORKING`."""
        return _elapsed(ctx, eta.setup_ms)

    def guard_work_time_elapsed_or_assignment_resolved(ctx: GuardContext) -> bool:
        """`WORKING --finish_work--> RETURNING`."""
        return _elapsed(ctx, eta.on_scene_work_ms) or _assignment_resolved(ctx)

    def guard_return_time_elapsed(ctx: GuardContext) -> bool:
        """`RETURNING --return_to_base--> AVAILABLE`."""
        return _elapsed(ctx, eta.return_time_ms)

    def guard_availability_effect_applied(ctx: GuardContext) -> bool:
        """`… --breakdown--> OUT_OF_SERVICE`: an `AlterResourceAvailability` hit this resource."""
        return ctx.world_flags.get("availability_effect", False)

    def guard_restore_effect_applied(ctx: GuardContext) -> bool:
        """`OUT_OF_SERVICE --repair--> AVAILABLE`: the effect carried `restore = true`."""
        return ctx.world_flags.get("restore_effect", False)

    def guard_outside_availability_window_or_effect(ctx: GuardContext) -> bool:
        """`AVAILABLE --make_unavailable--> UNAVAILABLE`."""
        resource = subject_resource(ctx)
        if resource is None:
            return False
        if ctx.world_flags.get("availability_effect", False):
            return True
        return not within_availability_window(resource, ctx.now_ms)

    def guard_inside_availability_window_or_effect(ctx: GuardContext) -> bool:
        """`UNAVAILABLE --make_available--> AVAILABLE`."""
        resource = subject_resource(ctx)
        if resource is None:
            return False
        if ctx.world_flags.get("availability_effect", False):
            return True
        return within_availability_window(resource, ctx.now_ms)

    return {
        "guard_selection_open_and_within_availability_window": (
            guard_selection_open_and_within_availability_window
        ),
        "guard_not_yet_dispatched": guard_not_yet_dispatched,
        "guard_selection_open": guard_selection_open,
        "guard_turnout_delay_elapsed": guard_turnout_delay_elapsed,
        "guard_travel_time_elapsed": guard_travel_time_elapsed,
        "guard_setup_time_elapsed": guard_setup_time_elapsed,
        "guard_work_time_elapsed_or_assignment_resolved": (
            guard_work_time_elapsed_or_assignment_resolved
        ),
        "guard_return_time_elapsed": guard_return_time_elapsed,
        "guard_availability_effect_applied": guard_availability_effect_applied,
        "guard_restore_effect_applied": guard_restore_effect_applied,
        "guard_outside_availability_window_or_effect": (
            guard_outside_availability_window_or_effect
        ),
        "guard_inside_availability_window_or_effect": guard_inside_availability_window_or_effect,
    }


RESOURCE_GUARDS: Mapping[str, Callable[[GuardContext], bool]] = build_resource_guards()
"""Every `guard_name` of `RESOURCE_STATUS_TRANSITIONS`, bound to the §10.7 ETA reading."""

RESOURCE_STATE_MACHINE: StateMachine[ResourceStatus] = StateMachine(
    RESOURCE_STATUS_TRANSITIONS, RESOURCE_GUARDS
)
"""The wired resource machine (§10.7). `world/resource_movement.py` builds its own instance when
a different `EtaModel` is in play."""
