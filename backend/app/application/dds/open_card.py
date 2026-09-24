"""`openDdsCard` — the ДДС opens the card on one leg («Получена службой», I3 E5a, HLD 70 §70.4.2,
§70.4.4).

`ADDED --receive--> RECEIVED` is a SIMULATION row: opening the card is the trainee's act
(`DDS_CARD_OPENED`, TRAINEE) and the technical status that follows is the system's
(`DDS_SERVICE_STATUS_SET`, SIMULATION, `source: SYSTEM`). Idempotent: on a leg past `ADDED` it
appends nothing and answers the leg (`openapi.yaml`).

**When it is offered.** §70.4.4 lists `open_card` in the memo `RECEIVED` state. The card of a
second leg is still opened after the first decision has moved the stage to `ACKNOWLEDGED`; there
the table offers `set_service_status`, whose first step on an `ADDED` leg is exactly this
`receive`, so the gate accepts either action id (`DdsCommandGate.open`'s "any of these").

**The stage.** `acknowledge` is fired here only when the trainee owns no leg of this card
(§70.4.4) — until E5b binds services every leg is unbound, so every ДДС participant owns every leg
and the first primary decision (`setDdsServiceStatus`) acknowledges instead.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import DdsCommandContext, DdsCommandGate
from app.application.dds.set_service_status import (
    acknowledge_stage,
    check_leg_bound,
    leg_view_of,
)
from app.application.dds.views import DdsLegView
from app.domain.common.actors import ActorRef
from app.domain.common.ids import AssignmentId, SessionId
from app.domain.dds.assignment import DDSAssignment, fire_response_trigger
from app.domain.dds.response import ServiceResponseStatus, StatusSource
from app.domain.enums import ActorType, DDSStageState
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "OpenDdsCard"]

ACTION_ID = "open_card"
"""`openapi.yaml`'s `x-action` for `openDdsCard`."""

_ACTION_IDS = (ACTION_ID, "set_service_status")
_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)


class OpenDdsCard:
    """`openDdsCard` (`openapi.yaml`): `DDS_CARD_OPENED` and the leg's `receive`."""

    def __init__(self, gate: DdsCommandGate) -> None:
        self._gate = gate

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, assignment_id: AssignmentId
    ) -> DdsLegView:
        """Open the card on the leg; a leg already past `ADDED` is answered unchanged."""
        async with self._gate.open(session_id, user, _ACTION_IDS) as ctx:
            leg = ctx.leg(assignment_id)
            check_leg_bound(leg, user.user_id)
            if leg.response_status is ServiceResponseStatus.ADDED:
                moved, received = fire_response_trigger(
                    leg,
                    "receive",
                    actor=_SIMULATION,
                    now_ms=ctx.now_ms,
                    source=StatusSource.SYSTEM,
                    status_policy=ctx.status_policy(leg),
                )
                await ctx.save_leg(moved)
                events: list[DomainEvent] = [_opened(ctx, leg), received]
                if ctx.stage_state is DDSStageState.RECEIVED and not _owns_a_leg(ctx, user):
                    events.extend(await acknowledge_stage(ctx, moved))
                await ctx.append_status_events(events)
            return await leg_view_of(ctx, assignment_id, user)


def _owns_a_leg(ctx: DdsCommandContext, user: AuthenticatedUser) -> bool:
    """The trainee plays at least one leg of this card (unbound, or bound to them)."""
    return any(leg.bound_user_id in (None, user.user_id) for leg in ctx.legs)


def _opened(ctx: DdsCommandContext, leg: DDSAssignment) -> DomainEvent:
    """`DDS_CARD_OPENED` (TRAINEE, HLD 70 §70.7)."""
    return DomainEvent(
        event_type=EventType.DDS_CARD_OPENED,
        actor=ctx.actor,
        monotonic_offset_ms=ctx.now_ms,
        payload={
            "assignment_id": UUID(str(leg.assignment_id)),
            "service_type": leg.service_type,
            "actor_user_id": UUID(str(ctx.actor.actor_id)),
            "at_offset_ms": ctx.now_ms,
        },
    )
