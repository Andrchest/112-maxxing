"""`selectDdsResource` — put one unit on the work item (`openapi.yaml`, §10.7).

`AVAILABLE --select--> SELECTED` on `RESOURCE_STATUS_TRANSITIONS`, guarded by "the assignment is
in a state where selection is open **and** the unit is inside its availability window". A refused
guard is `409 RESOURCE_UNAVAILABLE` — the contract gives this operation its own code rather than
the generic `INVALID_TRANSITION`, so the console can say which of the two it was.

`x-emits` is `[RESOURCE_SELECTED, RESOURCE_STATUS_CHANGED]`, in that order.

**Selection is what attaches a unit to a leg** (E9 analyst R4): `emergency_resources.assignment_id`
is set here and cleared by `deselectDdsResource`, and the leg is chosen by `leg_for` — the unit's
own service's leg, else the primary one. Attachment is load-bearing twice over: the event catalog
types `RESOURCE_SELECTED.assignment_id` non-null, and the DDS stage guards are shown only the
attached units, so a scenario unit moving elsewhere on the board cannot drive this stage.

Selecting a unit whose service received no handoff leg is **allowed** — see `leg_for` for the
whole argument. It is a scored mistake, not a blocked one.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import (
    DdsCommandContext,
    DdsCommandGate,
    ResourceUnavailableError,
    fire_resource_transition,
    state_change_row,
    status_changed_event,
)
from app.application.dds.leg_for import leg_for
from app.application.dds.views import DdsStageView
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import ResourceId, SessionId
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.resources import EmergencyResource
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "SelectDdsResource"]

ACTION_ID = "select_resource"
"""`openapi.yaml`'s `x-action` for `selectDdsResource`."""

TRIGGER = "select"
"""The `RESOURCE_STATUS_TRANSITIONS` trigger this command fires (§10.7)."""


class SelectDdsResource:
    """`selectDdsResource` (`openapi.yaml`): `AVAILABLE -> SELECTED`, attached to a leg."""

    def __init__(self, gate: DdsCommandGate) -> None:
        self._gate = gate

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, resource_id: ResourceId
    ) -> DdsStageView:
        """Select one unit, attach it to its leg, append the two events."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            stored = ctx.resource(resource_id)
            resource = stored.resource
            leg = leg_for(resource, ctx.legs, ctx.snapshot)
            try:
                new_status = fire_resource_transition(ctx, resource, leg, TRIGGER)
            except InvalidTransitionError as error:
                raise ResourceUnavailableError(resource_id, error.reason) from error

            moved = resource.model_copy(
                update={
                    "current_status": new_status,
                    "status_changed_at_offset_ms": ctx.sim_now_ms,
                }
            )
            stored = await ctx.save_resource(stored, moved)
            await ctx.attach(stored, leg.assignment_id)

            appended = await ctx.append(
                [
                    _selected(ctx, moved, leg),
                    status_changed_event(
                        resource, new_status, TRIGGER, ctx.now_ms, leg.assignment_id
                    ),
                ]
            )
            await ctx.uow.resources.record_state_change(
                state_change_row(
                    resource,
                    moved,
                    TRIGGER,
                    ctx.sim_now_ms,
                    leg.assignment_id,
                    appended[-1].id,
                )
            )
            return await ctx.stage_view()


def _selected(
    ctx: DdsCommandContext, resource: EmergencyResource, leg: DDSAssignment
) -> DomainEvent:
    """`RESOURCE_SELECTED` (TRAINEE) — the log's record of *which* leg this unit hangs on.

    `service_type` is the **unit's own**, which is what makes an off-service selection visible in
    the log: it differs from the `service_type` the leg's `HANDOFF_RECEIVED` carries.
    """
    return DomainEvent(
        event_type=EventType.RESOURCE_SELECTED,
        actor=ctx.actor,
        monotonic_offset_ms=ctx.now_ms,
        payload={
            "assignment_id": UUID(str(leg.assignment_id)),
            "resource_id": UUID(str(resource.resource_id)),
            "callsign": resource.callsign,
            "service_type": resource.service_type.value,
            "resource_type": resource.resource_type.value,
            "capabilities": sorted(item.value for item in resource.capabilities),
            "at_offset_ms": ctx.now_ms,
        },
    )
