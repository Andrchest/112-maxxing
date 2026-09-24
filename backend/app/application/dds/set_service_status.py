"""`setDdsServiceStatus` — the memo's pencil: set the next status of one service's leg (I3 E5a,
HLD 70 §70.4.2, §70.4.4; D16).

One command, one step of `SERVICE_RESPONSE_TRANSITIONS`, in the fixed order below:

1. `DdsCommandGate.open` with `x-action` `set_service_status`, which the picker table does not
   offer — `dds_mode: RESOURCE_PICKER` is therefore `409 ACTION_NOT_AVAILABLE` (the contract's
   answer);
2. the leg must be one of this stage's (`404`) and the caller must play it: its `bound_user_id`,
   or any ДДС participant when it is unbound; a `SCRIPTED` leg is nobody's (§70.4.5,
   `403 FORBIDDEN_FOR_SERVICE`);
3. the requested status must be the leg's legal next one (`trigger_for`; an `ADDED` leg is read as
   `RECEIVED`, because it is moved there first) — else the ordinary `409 INVALID_TRANSITION`
   (INV 8, A-8: no step may be skipped);
4. «Не принята» and «Отказ» need a non-blank comment — `422 COMMENT_REQUIRED` (A-9: 104 included);
5. an `ADDED` leg is first moved to `RECEIVED` (`receive`, SIMULATION, `source: SYSTEM`), then the
   trainee's trigger fires (TRAINEE, `source: TRAINEE`) with the entry's «Номер наряда» and comment
   (A-2: one per entry, both kept in the history);
6. the trainee's **first primary decision** (Принята / Не принята) while the stage is still
   `RECEIVED` also fires the stage's `acknowledge` (§70.4.4), so `DDS_ACKNOWLEDGED` and every
   acknowledge `DEADLINE` rule keep working; no other stage trigger is ever fired from here.

**A status heard on a call (I3 E6c, HLD 80 §80.3.3, D24).** Under `dds_brigade_call: ON` the
service head *proposes* (`DDS_CALL_STATUS_PROPOSED`) and the trainee *commits* with this very
command, optionally naming the call with `proposed_by_call_id`: it must name a
`DDS_CALL_STATUS_PROPOSED` of this leg in the session's log, else `422 PROPOSAL_UNKNOWN` (checked
after the leg and before the machine). It is copied into `DDS_SERVICE_STATUS_SET` and changes
nothing else — the status written is the request's, never the proposal's (INV 4), and the leg
machine, `409`, `422 COMMENT_REQUIRED`, the history and the memo closure are exactly as above.

`x-emits` is `[DDS_CARD_STATUS_CHANGED, DDS_SERVICE_STATUS_SET, DDS_ACKNOWLEDGED,
STAGE_STATE_CHANGED]`: the event store merges the due card-status events in (flush-before-append,
§70.3.5), then the status event(s), then the acknowledgement when this was the first decision. The
history rows are written from the stored events in the same transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import DdsCommandContext, DdsCommandGate
from app.application.dds.list_legs import assemble_leg_views
from app.application.dds.views import DdsLegView
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError, InvalidTransitionError
from app.domain.common.ids import AssignmentId, SessionId, UserId
from app.domain.dds.assignment import DDSAssignment, fire_response_trigger
from app.domain.dds.responders import plays_leg
from app.domain.dds.response import (
    PRIMARY_DECISIONS,
    ServiceResponseStatus,
    StatusSource,
    trigger_for,
)
from app.domain.enums import ActorType, DDSStageState
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType

__all__ = [
    "ACTION_ID",
    "CommentRequiredError",
    "ForbiddenForServiceError",
    "ProposalUnknownError",
    "SetDdsServiceStatus",
    "acknowledged_event",
    "check_leg_bound",
    "leg_view_of",
]

ACTION_ID = "set_service_status"
"""`openapi.yaml`'s `x-action` for `setDdsServiceStatus`."""

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)
_COMMENT_REQUIRED = frozenset({ServiceResponseStatus.NOT_ACCEPTED, ServiceResponseStatus.REFUSED})


class CommentRequiredError(DomainError):
    """«Не принята» / «Отказ от выполнения работ» without a comment (`422`, REQ-5284/5289)."""

    code = "COMMENT_REQUIRED"

    def __init__(self, status: ServiceResponseStatus) -> None:
        self.status = status
        super().__init__(f"status {status.value} requires a non-blank comment_ru")


class ProposalUnknownError(DomainError):
    """`proposed_by_call_id` names no `DDS_CALL_STATUS_PROPOSED` of this leg (`422`, I3 E6c)."""

    code = "PROPOSAL_UNKNOWN"

    def __init__(self, call_id: UUID, assignment_id: AssignmentId) -> None:
        self.call_id = call_id
        self.assignment_id = assignment_id
        super().__init__(
            f"call {call_id} proposed no status for assignment {assignment_id} in this session"
        )


def check_proposal(log: Sequence[SessionEvent], call_id: UUID, assignment_id: AssignmentId) -> None:
    """`proposed_by_call_id` must name a `DDS_CALL_STATUS_PROPOSED` of this leg (§80.3.3)."""
    wanted_call = str(call_id).lower()
    wanted_leg = str(assignment_id).lower()
    for event in log:
        if event.event_type is not EventType.DDS_CALL_STATUS_PROPOSED:
            continue
        payload = event.payload
        if (
            str(payload.get("call_id", "")).lower() == wanted_call
            and str(payload.get("assignment_id", "")).lower() == wanted_leg
        ):
            return
    raise ProposalUnknownError(call_id, assignment_id)


class ForbiddenForServiceError(DomainError):
    """The leg is bound to another ДДС participant (`403`, HLD 70 §70.4.5)."""

    code = "FORBIDDEN_FOR_SERVICE"

    def __init__(self, assignment_id: AssignmentId) -> None:
        self.assignment_id = assignment_id
        super().__init__(f"assignment {assignment_id} is played by another ДДС participant")


def check_leg_bound(leg: DDSAssignment, user_id: UserId) -> None:
    """`guard_leg_actor_bound`'s gate half: a bound leg answers only its participant, and a
    `SCRIPTED` leg — a service no ДДС participant is bound to — answers no trainee at all (HLD 70
    §70.4.5, I3 E5b); both are `403 FORBIDDEN_FOR_SERVICE`."""
    if plays_leg(leg, user_id):
        return
    raise ForbiddenForServiceError(leg.assignment_id)


def acknowledged_event(ctx: DdsCommandContext, leg: DDSAssignment) -> DomainEvent:
    """`DDS_ACKNOWLEDGED` (TRAINEE) for the memo acknowledgement, carrying the deciding leg."""
    return DomainEvent(
        event_type=EventType.DDS_ACKNOWLEDGED,
        actor=ctx.actor,
        monotonic_offset_ms=ctx.now_ms,
        payload={
            "assignment_id": UUID(str(leg.assignment_id)),
            "at_offset_ms": ctx.now_ms,
            "latency_from_handoff_ms": max(0, ctx.now_ms - leg.received_at_offset_ms),
            "actor_user_id": UUID(str(ctx.actor.actor_id)),
        },
    )


async def acknowledge_stage(ctx: DdsCommandContext, leg: DDSAssignment) -> list[DomainEvent]:
    """Fire the stage's `acknowledge` (memo, §70.4.4) and mirror it onto every leg's `state`."""
    session, stage_events = ctx.session.fire_stage_trigger(
        ctx.stage.role_stage_id,
        "acknowledge",
        actor=ctx.actor,
        now_ms=ctx.now_ms,
        runtime=ctx.guard_runtime(),
        assignment=leg,
    )
    await ctx.save_session(session)
    await ctx.mirror_legs(acknowledged_at_offset_ms=ctx.now_ms)
    return [acknowledged_event(ctx, leg), *stage_events]


async def leg_view_of(
    ctx: DdsCommandContext, assignment_id: AssignmentId, user: AuthenticatedUser
) -> DdsLegView:
    """The one leg's `DdsLegView` as it stands after this command."""
    views = await assemble_leg_views(
        ctx.uow, ctx.session, ctx.stage, ctx.legs, ctx.service_catalog, user
    )
    wanted = UUID(str(assignment_id))
    return next(view for view in views if view.assignment_id == wanted)


class SetDdsServiceStatus:
    """`setDdsServiceStatus` (`openapi.yaml`): one leg, one step."""

    def __init__(self, gate: DdsCommandGate) -> None:
        self._gate = gate

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        assignment_id: AssignmentId,
        *,
        status: ServiceResponseStatus,
        order_number: str | None = None,
        comment_ru: str | None = None,
        proposed_by_call_id: UUID | None = None,
    ) -> DdsLegView:
        """Move the leg to `status` (see the module docstring for the order of the checks)."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            leg = ctx.leg(assignment_id)
            check_leg_bound(leg, user.user_id)
            if proposed_by_call_id is not None:
                check_proposal(ctx.full_log, proposed_by_call_id, assignment_id)
            policy = ctx.status_policy(leg)
            current = (
                ServiceResponseStatus.RECEIVED
                if leg.response_status is ServiceResponseStatus.ADDED
                else leg.response_status
            )
            trigger = trigger_for(current, status, policy)
            if trigger is None:
                raise InvalidTransitionError(
                    "ServiceResponseStatus",
                    current.value,
                    f"set {status.value}",
                    "no such transition (statuses are set one step at a time)",
                    to_state=status.value,
                )
            if status in _COMMENT_REQUIRED and (comment_ru is None or not comment_ru.strip()):
                raise CommentRequiredError(status)

            events: list[DomainEvent] = []
            if leg.response_status is ServiceResponseStatus.ADDED:
                leg, received = fire_response_trigger(
                    leg,
                    "receive",
                    actor=_SIMULATION,
                    now_ms=ctx.now_ms,
                    source=StatusSource.SYSTEM,
                    status_policy=policy,
                )
                events.append(received)
            moved, event = fire_response_trigger(
                leg,
                trigger,
                actor=ctx.actor,
                now_ms=ctx.now_ms,
                source=StatusSource.TRAINEE,
                status_policy=policy,
                order_number=order_number,
                comment_ru=comment_ru,
                proposed_by_call_id=proposed_by_call_id,
            )
            events.append(event)
            await ctx.save_leg(moved)
            if (
                ctx.stage_state is DDSStageState.RECEIVED
                and moved.response_status in PRIMARY_DECISIONS
            ):
                events.extend(await acknowledge_stage(ctx, moved))
            await ctx.append_status_events(events)
            return await leg_view_of(ctx, assignment_id, user)
