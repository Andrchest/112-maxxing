"""`deselectDdsResource` — take one unit back off the work item (`openapi.yaml`, §10.7).

`SELECTED --deselect--> AVAILABLE`, guard "the resource is not yet dispatched". The guard reads
the leg's `dispatched_resource_ids`, which is projected from the append-only
`resource_state_changes` history rather than from the live attachment — so a unit that was sent
and has since been released still cannot be un-sent, which is the point of the guard.

`x-emits` is `[RESOURCE_DESELECTED, RESOURCE_STATUS_CHANGED]`, in that order. Deselecting clears
`emergency_resources.assignment_id`: the unit is no longer part of this work item, so the stage
guards must stop seeing it (E9 analyst R4/R6).

The leg used is the one the unit is **actually attached to**, read off the board, not `leg_for`'s
answer — they agree for every unit this codebase attached, and reading the stored value means a
deselect can never detach a unit from a leg other than the one it was selected under.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import (
    DdsCommandContext,
    DdsCommandGate,
    fire_resource_transition,
    state_change_row,
    status_changed_event,
)
from app.application.dds.leg_for import leg_for
from app.application.dds.views import DdsStageView
from app.domain.common.ids import ResourceId, SessionId
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.resources import EmergencyResource
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "DeselectDdsResource"]

ACTION_ID = "deselect_resource"
"""`openapi.yaml`'s `x-action` for `deselectDdsResource`."""

TRIGGER = "deselect"
"""The `RESOURCE_STATUS_TRANSITIONS` trigger this command fires (§10.7)."""


class DeselectDdsResource:
    """`deselectDdsResource` (`openapi.yaml`): `SELECTED -> AVAILABLE`, detached from its leg."""

    def __init__(self, gate: DdsCommandGate) -> None:
        self._gate = gate

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, resource_id: ResourceId
    ) -> DdsStageView:
        """Deselect one unit, detach it, append the two events."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            stored = ctx.resource(resource_id)
            resource = stored.resource
            leg = _attached_leg(ctx, stored.assignment_id, resource)
            new_status = fire_resource_transition(ctx, resource, _with_history(ctx, leg), TRIGGER)

            moved = resource.model_copy(
                update={
                    "current_status": new_status,
                    "status_changed_at_offset_ms": ctx.sim_now_ms,
                }
            )
            stored = await ctx.save_resource(stored, moved)
            await ctx.attach(stored, None)

            appended = await ctx.append(
                [
                    _deselected(ctx, moved, leg),
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


def _attached_leg(
    ctx: DdsCommandContext, assignment_id: object, resource: EmergencyResource
) -> DDSAssignment:
    """The leg the unit is attached to, falling back to `leg_for` for an unattached one.

    An unattached unit is not in `SELECTED` — attachment and selection are written together — so
    the fallback exists only so that the machine, rather than this function, produces the refusal.
    """
    for leg in ctx.legs:
        if leg.assignment_id == assignment_id:
            return leg
    return leg_for(resource, ctx.legs, ctx.snapshot)


def _with_history(ctx: DdsCommandContext, leg: DDSAssignment) -> DDSAssignment:
    """`leg` with its projected `dispatched_resource_ids`, which the deselect guard reads."""
    for projected in ctx.projected_legs:
        if projected.assignment_id == leg.assignment_id:
            return projected
    return leg  # pragma: no cover - every leg of the stage is projected


def _deselected(
    ctx: DdsCommandContext, resource: EmergencyResource, leg: DDSAssignment
) -> DomainEvent:
    """`RESOURCE_DESELECTED` (TRAINEE)."""
    return DomainEvent(
        event_type=EventType.RESOURCE_DESELECTED,
        actor=ctx.actor,
        monotonic_offset_ms=ctx.now_ms,
        payload={
            "assignment_id": UUID(str(leg.assignment_id)),
            "resource_id": UUID(str(resource.resource_id)),
            "callsign": resource.callsign,
            "at_offset_ms": ctx.now_ms,
        },
    )
