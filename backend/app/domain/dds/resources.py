"""`ResourceCapability`, `EtaProfile`, `ResourceAvailability`, `EmergencyResource`,
`RESOURCE_STATUS_TRANSITIONS` (HLD `10-domain-model.md` §10.7, SPEC §11).

Guard *callables* for `RESOURCE_STATUS_TRANSITIONS`'s `guard_name`s are not implemented here: most
depend on per-resource event timestamps (`dispatched_at`, `departed_at`, `arrived_at`,
`work_started_at`, `returning_at`) that §10.7's `EmergencyResource` field table does not list and
no read HLD document assigns a home to — see this task's report, "HLD gaps".
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import ResourceId
from app.domain.common.state_machine import Transition, TransitionTable
from app.domain.enums import ActorType, ResourceStatus, ResourceType, RoleType, ServiceType
from app.domain.events.types import EventType

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
    service_type: ServiceType
    resource_type: ResourceType
    callsign: str
    name_ru: str
    capabilities: frozenset[ResourceCapability]
    current_status: ResourceStatus
    availability: ResourceAvailability
    eta: EtaProfile
    home_station_ru: str
    crew_size: int


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
