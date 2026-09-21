"""`dispatchDdsResources` — send every currently selected unit (`openapi.yaml`, §10.7-§10.9).

One command, two machines, one transaction, and a deliberate order between them:

1. the **stage** machine fires `dispatch` (`RESOURCE_SELECTION -> DISPATCHED`) the first time and
   `dispatch_additional` (a self-transition from `EN_ROUTE` / `ARRIVED` / `WORKING`) afterwards.
   Its guard is `guard_at_least_one_selected_available`, which needs to *see* the units still in
   `SELECTED` — so the stage moves first, while they are;
2. the **resource** machine then fires `SELECTED --dispatch--> DISPATCHED` for each of them. Its
   own guard reads the assignment state, and the assignment state it is given is the one the
   command *started* in, not the one step 1 just produced: both guards judge the same instant,
   because one trainee click is one atomic step.

`x-emits` is `[RESOURCE_DISPATCHED, RESOURCE_STATUS_CHANGED, STAGE_STATE_CHANGED]` and that is the
append order — one `RESOURCE_DISPATCHED` covering every unit of every leg (E9 analyst R5: one
trainee action, one trainee event), then one `RESOURCE_STATUS_CHANGED` per unit, then the stage
event.

**Per-leg bookkeeping (R1b).** `dds_assignments.state` mirrors the stage on every leg, but
`dispatched_at_offset_ms` is stamped only on the legs that actually received a unit, and only the
first time. A recipient service that got nothing therefore reads `state = DISPATCHED,
dispatched_at = null`, which is exactly the fact the instructor overview and the report need:
"AMBULANCE was a recipient, zero units were sent".

**`service_type_by_resource` (additive, E9).** Each dispatched unit's own `service_type`. It is
not derivable from `assignment_id`, because a unit whose service received no leg attaches to the
primary one (`leg_for`), so `min_units_by_service` scoring may never go through the leg.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import (
    DdsCommandContext,
    DdsCommandGate,
    fire_resource_transition,
    state_change_row,
    status_changed_event,
)
from app.application.dds.views import DispatchResultView
from app.application.ports.resource_repository import DispatchRecord, StoredResource
from app.domain.common.ids import AssignmentId, SessionId
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.resources import EmergencyResource
from app.domain.enums import DDSStageState, ResourceStatus
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "ADDITIONAL_ACTION_ID", "DispatchDdsResources", "eta_seconds"]

ACTION_ID = "dispatch"
"""`openapi.yaml`'s `x-action` for `dispatchDdsResources` — the first dispatch."""

ADDITIONAL_ACTION_ID = "dispatch_additional"
"""The same endpoint's action once units are already moving (§10.9; the E9 repair made it
reachable by allowing `select_resource` in `EN_ROUTE` / `ARRIVED` / `WORKING`)."""

TRIGGER = "dispatch"
"""The `RESOURCE_STATUS_TRANSITIONS` trigger each unit fires (§10.7)."""


def eta_seconds(resource: EmergencyResource) -> int:
    """The unit's estimated time of **arrival**, in seconds (`eta_seconds_by_resource`).

    Turnout delay plus travel time: the two durations that elapse between `dispatch` and the unit
    being `ON_SCENE`. `setup_seconds`, `on_scene_work_seconds` and `return_time_seconds` describe
    what happens after it arrives and are not part of an ETA. `openapi.yaml` calls the value
    "total ETA seconds" without defining the sum — see this task's report under "HLD gaps".
    """
    return resource.eta.turnout_delay_seconds + resource.eta.travel_time_seconds


class DispatchDdsResources:
    """`dispatchDdsResources` (`openapi.yaml`): send everything selected, under its own leg."""

    def __init__(self, gate: DdsCommandGate) -> None:
        self._gate = gate

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, note_ru: str | None = None
    ) -> DispatchResultView:
        """Fire the stage trigger, then every selected unit; answer with `DispatchResultView`.

        `note_ru` is accepted because `DispatchRequest` declares it, and it is deliberately not
        recorded: neither `RESOURCE_DISPATCHED` nor any table has a field for it, and inventing
        one would put a value in the audit log that §10.13 does not type. TODO(E16): the
        instructor timeline is where a dispatch note would belong if the owner wants one.
        """
        async with self._gate.open(session_id, user, (ACTION_ID, ADDITIONAL_ACTION_ID)) as ctx:
            started_in = ctx.stage_state
            is_additional = started_in is not DDSStageState.RESOURCE_SELECTION
            stage_trigger = ADDITIONAL_ACTION_ID if is_additional else ACTION_ID
            selected = _selected_units(ctx)

            session, stage_events = ctx.session.fire_stage_trigger(
                ctx.stage.role_stage_id,
                stage_trigger,
                actor=ctx.actor,
                now_ms=ctx.now_ms,
                runtime=ctx.guard_runtime(),
                assignment=ctx.primary,
                resources=ctx.attached_units(),
            )
            await ctx.save_session(session)

            moved = await self._move(ctx, selected, started_in)
            await self._stamp_legs(ctx, {leg_id for leg_id, _ in moved})

            appended = await ctx.append(
                [
                    _dispatched(
                        ctx,
                        [resource for _leg_id, resource in moved],
                        is_additional=is_additional,
                    ),
                    *(
                        status_changed_event(
                            before, ResourceStatus.DISPATCHED, TRIGGER, ctx.now_ms, leg_id
                        )
                        for (leg_id, _after), before in zip(moved, selected, strict=True)
                    ),
                    *stage_events,
                ]
            )
            await self._record(ctx, selected, moved, appended)

            return DispatchResultView(
                stage=await ctx.stage_view(),
                dispatched_resource_ids=tuple(
                    UUID(str(resource.resource_id)) for _leg_id, resource in moved
                ),
                eta_seconds_by_resource={
                    UUID(str(resource.resource_id)): eta_seconds(resource)
                    for _leg_id, resource in moved
                },
                is_additional=is_additional,
            )

    # -- steps ---------------------------------------------------------------------------------

    async def _move(
        self,
        ctx: DdsCommandContext,
        selected: Sequence[EmergencyResource],
        started_in: DDSStageState,
    ) -> list[tuple[AssignmentId, EmergencyResource]]:
        """Fire `dispatch` on each selected unit, against the state the command started in."""
        moved: list[tuple[AssignmentId, EmergencyResource]] = []
        for resource in selected:
            stored = ctx.resource(resource.resource_id)
            leg = _leg_of(ctx, stored)
            new_status = fire_resource_transition(ctx, resource, leg, TRIGGER, state=started_in)
            after = resource.model_copy(
                update={
                    "current_status": new_status,
                    "status_changed_at_offset_ms": ctx.sim_now_ms,
                }
            )
            await ctx.save_resource(stored, after)
            moved.append((leg.assignment_id, after))
        return moved

    async def _stamp_legs(self, ctx: DdsCommandContext, receiving: set[AssignmentId]) -> None:
        """Mirror the stage state onto every leg; stamp `dispatched_at` on the receiving ones."""
        updated: list[DDSAssignment] = []
        for leg in ctx.legs:
            fields: dict[str, object] = {"state": ctx.stage_state}
            if leg.assignment_id in receiving and leg.dispatched_at_offset_ms is None:
                fields["dispatched_at_offset_ms"] = ctx.now_ms
            moved = leg.model_copy(update=fields)
            await ctx.uow.dds_assignments.save(moved)
            updated.append(moved)
        ctx.legs = tuple(updated)

    async def _record(
        self,
        ctx: DdsCommandContext,
        before: Sequence[EmergencyResource],
        moved: Sequence[tuple[AssignmentId, EmergencyResource]],
        appended: Sequence[SessionEvent],
    ) -> None:
        """One `resource_state_changes` row per unit, carrying its `session_event_id` (§20.5).

        The status events start at index 1 of the append (index 0 is `RESOURCE_DISPATCHED`), in
        the same order the units were moved in, so the pairing is positional and exact. The new
        rows also go onto the context's dispatch history, so the `DispatchResultView` it is about
        to build already shows them in each leg's `dispatched_resource_ids`.
        """
        history = list(ctx.dispatched)
        for index, ((leg_id, after), previous) in enumerate(zip(moved, before, strict=True)):
            event = appended[index + 1]
            await ctx.uow.resources.record_state_change(
                state_change_row(
                    previous,
                    after,
                    TRIGGER,
                    ctx.sim_now_ms,
                    leg_id,
                    event.id,
                )
            )
            history.append(
                DispatchRecord(
                    assignment_id=leg_id,
                    resource_id=after.resource_id,
                    at_offset_ms=ctx.sim_now_ms,
                )
            )
        ctx.dispatched = tuple(history)


def _selected_units(ctx: DdsCommandContext) -> tuple[EmergencyResource, ...]:
    """Every unit attached to this stage and currently `SELECTED`, in `callsign` order.

    "Dispatch every currently selected resource" (`openapi.yaml`). Attached, because a unit in
    `SELECTED` that hangs on no leg of this stage is not part of this work item.
    """
    ids = {leg.assignment_id for leg in ctx.legs}
    return tuple(
        sorted(
            (
                stored.resource
                for stored in ctx.board
                if stored.assignment_id in ids
                and stored.resource.current_status is ResourceStatus.SELECTED
            ),
            key=lambda resource: resource.callsign,
        )
    )


def _leg_of(ctx: DdsCommandContext, stored: StoredResource) -> DDSAssignment:
    """The leg a selected unit is attached to (it always has one — `select` attaches it)."""
    for leg in ctx.legs:
        if leg.assignment_id == stored.assignment_id:
            return leg
    return ctx.primary  # pragma: no cover - a selected unit is always attached


def _dispatched(
    ctx: DdsCommandContext, resources: Sequence[EmergencyResource], *, is_additional: bool
) -> DomainEvent:
    """`RESOURCE_DISPATCHED` (TRAINEE) — one event for the whole click (R5)."""
    capabilities: set[str] = set()
    for resource in resources:
        capabilities.update(item.value for item in resource.capabilities)
    return DomainEvent(
        event_type=EventType.RESOURCE_DISPATCHED,
        actor=ctx.actor,
        monotonic_offset_ms=ctx.now_ms,
        payload={
            "assignment_id": UUID(str(ctx.primary.assignment_id)),
            "resource_ids": [str(resource.resource_id) for resource in resources],
            "callsigns": [resource.callsign for resource in resources],
            "capabilities_union": sorted(capabilities),
            "eta_seconds_by_resource": {
                str(resource.resource_id): eta_seconds(resource) for resource in resources
            },
            "service_type_by_resource": {
                str(resource.resource_id): resource.service_type.value for resource in resources
            },
            "at_offset_ms": ctx.now_ms,
            "is_additional": is_additional,
        },
    )
