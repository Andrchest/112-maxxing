"""`DDSAssignment` — the DDS work item created from a `HandoffSnapshot` (HLD `10-domain-model.md`
§10.7, D3).

One assignment per recipient service. Exposes no accessor to `WorldTruth`: per D3 the DDS
application service is constructed without a world-truth repository, so this type is never even
given one to hold.

**Response status (I3 E5a, HLD `70-i3-alignment.md` §70.4.3).** Each leg also carries the memo's
per-service `ServiceResponseStatus` (`dds/response.py`), the offset it was entered at, the last
entry's «Номер наряда» and comment, the sticky `accept_missed` flag, and who plays it
(`responder`, `bound_user_id` — set at creation by `dds/responders.py`'s `assign_responders`, E5b).
`fire_response_trigger` is the one way the status moves: it runs `SERVICE_RESPONSE_MACHINE` and
returns the moved leg with its `DDS_SERVICE_STATUS_SET`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.actors import ActorRef
from app.domain.common.ids import (
    AssignmentId,
    IncidentId,
    ResourceId,
    RoleStageId,
    SnapshotId,
    UserId,
)
from app.domain.common.state_machine import GuardContext
from app.domain.dds.policy import StatusPolicy
from app.domain.dds.response import (
    SERVICE_RESPONSE_MACHINE,
    CompletionReason,
    LegGuardSubject,
    LegResponder,
    ServiceResponseStatus,
    StatusSource,
)
from app.domain.enums import ActorType, ClosureReason, DDSStageState, RoleType, ServiceId
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["DDSAssignment", "fire_response_trigger", "handoff_received_keys"]


class DDSAssignment(BaseModel):
    """The DDS work item for one recipient service (§10.7)."""

    model_config = ConfigDict(extra="forbid")

    assignment_id: AssignmentId
    incident_id: IncidentId
    role_stage_id: RoleStageId
    snapshot_id: SnapshotId
    service_type: ServiceId
    state: DDSStageState
    received_at_offset_ms: int
    acknowledged_at_offset_ms: int | None = None
    dispatched_at_offset_ms: int | None = None
    closed_at_offset_ms: int | None = None
    closure_reason: ClosureReason | None = None
    selected_resource_ids: tuple[ResourceId, ...] = ()
    dispatched_resource_ids: tuple[ResourceId, ...] = ()
    # -- I3 E5a (§70.4.3) ----------------------------------------------------------------------
    response_status: ServiceResponseStatus = ServiceResponseStatus.ADDED
    response_status_at_offset_ms: int | None = None
    order_number: str | None = None
    """«Номер наряда» of the last entry (free text, optional — A-2)."""
    last_comment_ru: str | None = None
    accept_missed: bool = False
    """Sticky once the accept deadline passed without a primary decision (§70.3.5)."""
    responder: LegResponder = LegResponder.TRAINEE
    bound_user_id: UserId | None = None


def fire_response_trigger(
    leg: DDSAssignment,
    trigger: str,
    *,
    actor: ActorRef,
    now_ms: int,
    source: StatusSource,
    status_policy: StatusPolicy = StatusPolicy.DEFAULT,
    order_number: str | None = None,
    comment_ru: str | None = None,
) -> tuple[DDSAssignment, DomainEvent]:
    """Fire one `SERVICE_RESPONSE_TRANSITIONS` trigger on `leg` (§70.4.2).

    Raises `InvalidTransitionError` exactly as the machine does (an out-of-sequence status, a
    denied guard, an actor the row does not allow). On success returns the moved leg — its
    status, offset, «Номер наряда» and comment are those of this entry — and the one
    `DDS_SERVICE_STATUS_SET` recording it. The history row is the application's to materialise
    from the stored event.
    """
    ctx = GuardContext(
        actor=actor,
        role_type=RoleType.DDS if actor.actor_type is ActorType.TRAINEE else None,
        now_ms=now_ms,
        assignment=LegGuardSubject(
            status_policy=status_policy,
            comment_ru=comment_ru,
            bound_user_id=leg.bound_user_id,
            responder=leg.responder,
        ),
    )
    previous = leg.response_status
    target = SERVICE_RESPONSE_MACHINE.fire(previous, trigger, ctx)
    completion = (
        CompletionReason.WITHOUT_BRIGADE.value if trigger == "complete_without_brigade" else None
    )
    moved = leg.model_copy(
        update={
            "response_status": target,
            "response_status_at_offset_ms": now_ms,
            "order_number": order_number,
            "last_comment_ru": comment_ru,
        }
    )
    payload = {
        "assignment_id": UUID(str(leg.assignment_id)),
        "service_type": leg.service_type,
        "previous_status": previous.value,
        "new_status": target.value,
        "trigger": trigger,
        "order_number": order_number,
        "comment_ru": comment_ru,
        "completion_reason": completion,
        "source": source.value,
        "actor_user_id": None if actor.actor_id is None else UUID(str(actor.actor_id)),
        "at_offset_ms": now_ms,
    }
    validate_payload(EventType.DDS_SERVICE_STATUS_SET, payload)
    event = DomainEvent(
        event_type=EventType.DDS_SERVICE_STATUS_SET,
        actor=actor,
        monotonic_offset_ms=now_ms,
        payload=payload,
    )
    return moved, event


def handoff_received_keys(leg: DDSAssignment) -> dict[str, object]:
    """`HANDOFF_RECEIVED`'s additive keys (I3 E5a, HLD 70 §70.7): who plays the leg and the status
    it starts in. Every `HANDOFF_RECEIVED` emitter spreads these into its payload."""
    return {
        "responder": leg.responder.value,
        "bound_user_id": None if leg.bound_user_id is None else UUID(str(leg.bound_user_id)),
        "initial_response_status": leg.response_status.value,
    }
