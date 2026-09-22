"""`advance_resources` — scenario-driven resource movement (HLD `10-domain-model.md` §10.7, D7).

D7: "Resource movement (turnout delay, travel time, on-scene work) is scheduled by the same engine
from scenario-defined ETA data through a local `EtaModel` port." This module is that scheduler, and
it is pure: `now_ms` is simulated time, every duration comes from the `EtaModel`, and no clock,
randomness or I/O is involved.

Every "X_at" of §10.7's guard column is `EmergencyResource.status_changed_at_offset_ms` (see
`dds/resources.py`), so a transition's due time is
`status_changed_at_offset_ms + <duration>·1000`. One call fires **every** transition already due —
a long tick can walk a resource `DISPATCHED → EN_ROUTE → ON_SCENE → WORKING` in one go — and each
firing is stamped with **its own due time**, not with `now_ms`, so the result of one 4-second tick
equals the result of eight 500-ms ticks. The availability window is applied the same way, with the
window boundary as the due time.

Deterministic order: resources are walked by ascending **`callsign`**, and every fired transition
emits `RESOURCE_STATUS_CHANGED` (§10.7).

The walk order is load-bearing for determinism rule 5 / INV 7 — it *is* the order the events of
one tick are appended in — so it may not depend on anything that differs between two runs of the
same scenario. The runtime `ResourceId` does: `emergency_resources.id` is `gen_random_uuid()` per
session (`20-db-schema.md` §20.5), so walking by it made two identical runs emit the same
transitions in a different sequence. `callsign` is the scenario's own handle on a unit and is
unique within a scenario (`30-scenario-format.md` §30.8 rule 15), so it is stable across runs; the
runtime id remains only as the tie-break that keeps the ordering total.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import ResourceId
from app.domain.common.state_machine import GuardContext, StateMachine
from app.domain.dds.resources import (
    RESOURCE_STATUS_TRANSITIONS,
    EmergencyResource,
    build_resource_guards,
)
from app.domain.enums import ActorType, ResourceStatus
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.world.eta import EtaModel

__all__ = ["advance_resources"]

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)

_FORWARD_TRIGGER: Mapping[ResourceStatus, str] = {
    ResourceStatus.DISPATCHED: "depart",
    ResourceStatus.EN_ROUTE: "arrive",
    ResourceStatus.ON_SCENE: "start_work",
    ResourceStatus.WORKING: "finish_work",
    ResourceStatus.RETURNING: "return_to_base",
}
"""The one SIMULATION-fired forward trigger of each moving status (§10.7)."""


def _due_ms(resource: EmergencyResource, eta_model: EtaModel) -> int | None:
    """When the current status's forward transition becomes due, or `None` when there is none."""
    status = resource.current_status
    entered = resource.status_changed_at_offset_ms
    if status is ResourceStatus.DISPATCHED:
        return entered + eta_model.turnout_delay_ms(resource)
    if status is ResourceStatus.EN_ROUTE:
        return entered + eta_model.travel_time_ms(resource)
    if status is ResourceStatus.ON_SCENE:
        return entered + eta_model.setup_ms(resource)
    if status is ResourceStatus.WORKING:
        return entered + eta_model.on_scene_work_ms(resource)
    if status is ResourceStatus.RETURNING:
        return entered + eta_model.return_time_ms(resource)
    return None


def _status_event(
    previous: EmergencyResource, new_status: ResourceStatus, trigger: str, at_ms: int
) -> DomainEvent:
    return DomainEvent(
        event_type=EventType.RESOURCE_STATUS_CHANGED,
        actor=_SIMULATION,
        monotonic_offset_ms=at_ms,
        payload={
            "resource_id": previous.resource_id,
            "callsign": previous.callsign,
            "previous_status": previous.current_status.value,
            "new_status": new_status.value,
            "trigger": trigger,
            "source_world_event_id": None,
            "at_offset_ms": at_ms,
        },
    )


def _window_step(resource: EmergencyResource, now_ms: int) -> tuple[str, int] | None:
    """The availability-window transition due at or before `now_ms`, with its own due time."""
    window = resource.availability
    if resource.current_status is ResourceStatus.AVAILABLE:
        if window.available_until_ms is not None and now_ms >= window.available_until_ms:
            return "make_unavailable", window.available_until_ms
        if now_ms < window.available_from_ms:  # pragma: no cover - guarded by the machine anyway
            return "make_unavailable", now_ms
        return None
    if resource.current_status is ResourceStatus.UNAVAILABLE:
        inside_from = now_ms >= window.available_from_ms
        inside_until = window.available_until_ms is None or now_ms < window.available_until_ms
        if inside_from and inside_until:
            return "make_available", max(
                window.available_from_ms, resource.status_changed_at_offset_ms
            )
    return None


def advance_resources(
    resources: Mapping[ResourceId, EmergencyResource],
    now_ms: int,
    eta_model: EtaModel,
    *,
    assignment_resolved: bool,
) -> tuple[Mapping[ResourceId, EmergencyResource], list[DomainEvent]]:
    """Fire every SIMULATION resource transition that is due at `now_ms` (§10.7, D7).

    Returns the new board and one `RESOURCE_STATUS_CHANGED` per fired transition, in ascending
    `callsign` order (see the module docstring — the runtime `resource_id` is random per session
    and cannot order a deterministic stream). Never raises: a transition the machine refuses
    simply does not fire.
    """
    machine: StateMachine[ResourceStatus] = StateMachine(
        RESOURCE_STATUS_TRANSITIONS, build_resource_guards(eta_model)
    )
    moved: dict[ResourceId, EmergencyResource] = dict(resources)
    events: list[DomainEvent] = []

    for key in sorted(resources, key=lambda key: (resources[key].callsign, str(key))):
        resource = moved[key]
        # The forward chain DISPATCHED -> ... -> AVAILABLE is five steps long, so this loop is
        # bounded by construction; the explicit cap only documents that.
        for _step in range(len(_FORWARD_TRIGGER)):
            trigger = _FORWARD_TRIGGER.get(resource.current_status)
            if trigger is None:
                break
            due = _due_ms(resource, eta_model)
            if due is None:
                break
            if assignment_resolved and resource.current_status is ResourceStatus.WORKING:
                due = min(due, now_ms)
            if due > now_ms:
                break
            ctx = GuardContext(
                actor=_SIMULATION,
                now_ms=due,
                resources={str(key): resource},
                world_flags={"assignment_resolved": assignment_resolved},
            )
            try:
                target = machine.fire(resource.current_status, trigger, ctx)
            except InvalidTransitionError:  # pragma: no cover - the guard was checked above
                break
            events.append(_status_event(resource, target, trigger, due))
            resource = resource.model_copy(
                update={"current_status": target, "status_changed_at_offset_ms": due}
            )
            moved[key] = resource

        step = _window_step(resource, now_ms)
        if step is None:
            continue
        trigger, at_ms = step
        ctx = GuardContext(actor=_SIMULATION, now_ms=at_ms, resources={str(key): resource})
        try:
            target = machine.fire(resource.current_status, trigger, ctx)
        except InvalidTransitionError:
            continue
        events.append(_status_event(resource, target, trigger, at_ms))
        moved[key] = resource.model_copy(
            update={"current_status": target, "status_changed_at_offset_ms": at_ms}
        )

    return moved, events
