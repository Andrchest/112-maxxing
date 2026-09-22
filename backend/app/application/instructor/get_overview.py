"""`getInstructorSessionOverview` — the live instructor payload (E17 R4; D3, D11).

`openapi.yaml`'s own words: "The one live endpoint that exposes `WorldTruth`, `CallerBelief` and
`FactAccessGate` decisions." `INSTRUCTOR`/`ADMIN` only, in **every** session state after creation
(including `COMPLETED`/`ABORTED` — there is no report-style `409 REPORT_NOT_READY` gate here,
because this is not the report: it is the live console's own read, and an instructor reviewing a
finished session still wants it). It is a pure read: no event is appended, no row is written
(`backend/tests/api/instructor/test_overview.py` asserts the event count and every relevant row
count are unchanged across a call).

**Reuse, not reinvention.** `assemble_session_detail` gives `session`/`stages` (the same
`RoleStageView` list `SessionDetail.stages` already carries — the API mapper takes it from there,
so this module does not re-derive it). `resource_views`/`project_legs`/`legs_in_recipient_order`/
`missing_field_paths` are the exact functions `getDdsWorkItem` and `getSessionSnapshot` already
use; this module calls them with a different fold, never reimplements them.

**`assignments` is the *other* documented reading of `DdsWorkItem` (`openapi.yaml`, `DdsWorkItem`
description).** The trainee's `getDdsWorkItem` answers with ONE work item — the primary leg's
`assignment_id`/`service_type`, dispatched-at as the *minimum* over the legs, resource lists as
their *union* (`app.application.handoff.work_item.work_item_view`). The instructor's `assignments`
answers with the **N legs verbatim**: one `DdsWorkItem` per `DDSAssignment` row, each with its own
`dispatched_at_offset_ms` and its own resource lists — `openapi.yaml`: "the per-service
`dds_assignments` rows verbatim... `null` on a recipient service that received no unit." That is
why this module builds its own per-leg projection (`_leg_work_item`) rather than reusing
`work_item_view`, which by construction answers the other question.

Note this is a **different** reading from `app.application.reports.dds_decisions.DdsDecision`
(`openapi.yaml`'s `DdsDecisionView`, `SessionReport.dds_decisions`): both are "the N legs", but
`DdsDecisionView` groups dispatch **acts** (`dispatch_events`, one per click) and status updates,
while `DdsWorkItem` (this field's type) carries the *current* resource-id lists and a single
`dispatched_at_offset_ms` per leg. They are two different contract schemas for two different
questions and neither is built from the other.

**`world_truth`/`caller_belief` are never `None` in practice.** `create_session.py` writes both
rows in the same transaction that creates the session (`instantiate_world_truth`/
`instantiate_caller_belief`), so every session this endpoint can be called on already has them;
a missing row would be a storage bug, not a request error, hence `WorldStateMissingError` rather
than a 404-mapped `DomainError`.

**`gate_turns` is folded from the log, not read from a projection table.** Each
`FACT_GATE_EVALUATED` event already carries exactly `GateTurnView`'s shape
(`app.application.dialogue.events.fact_gate_evaluated_payload`); this module's `_gate_turns` is
the inverse of that builder.

**`inference_health` is deliberately not assembled here.** `app.api.routers.health` says why the
health fold "lives [in the API layer] rather than in the application layer: it is nothing but a
precedence rule over `ComponentReading`s the port already produced." `app.api.routers.instructor`
runs the same probes and the same fold for this endpoint, and this view has no field for it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import dds_stage_of
from app.application.dds.leg_for import project_legs
from app.application.dds.views import EmergencyResourceView, resource_views
from app.application.handoff.work_item import (
    DdsWorkItemView,
    legs_in_recipient_order,
    missing_field_paths,
)
from app.application.operator.views import CallStateView, project_call_state
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.sessions.queries import (
    ForbiddenForRoleError,
    SessionDetailView,
    assemble_session_detail,
)
from app.application.sessions.start_session import SessionNotFoundError
from app.application.simulation.sim_time import sim_now_ms
from app.domain.common.ids import SessionId, SnapshotId
from app.domain.dds.assignment import DDSAssignment
from app.domain.enums import DDSStageState, GateOutcome, GateReason, RoleType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import OperatorCard
from app.domain.layers.world_truth import WorldTruth
from app.domain.session.session import SimulationSession

__all__ = [
    "GateDecisionEntry",
    "GateTurnEntry",
    "GetInstructorSessionOverview",
    "InstructorSessionOverviewView",
    "WorldStateMissingError",
]


class WorldStateMissingError(RuntimeError):
    """The incident's `WorldTruth`/`CallerBelief` row is gone — a storage bug (both are written
    inside `createSession`'s own transaction, D3), never a request error."""


@dataclass(frozen=True, slots=True)
class GateDecisionEntry:
    """`openapi.yaml`'s `GateDecisionView` — one fact's verdict within a `GateTurnEntry`."""

    fact_id: str
    outcome: GateOutcome
    reason: GateReason


@dataclass(frozen=True, slots=True)
class GateTurnEntry:
    """`openapi.yaml`'s `GateTurnView` — one `FACT_GATE_EVALUATED` row, folded from the log."""

    turn_index: int
    at_offset_ms: int
    decisions: tuple[GateDecisionEntry, ...]
    allowed_fact_ids: tuple[str, ...]
    spontaneous_attached: tuple[str, ...]
    withheld_count: int


@dataclass(frozen=True, slots=True)
class InstructorSessionOverviewView:
    """`openapi.yaml`'s `InstructorSessionOverview` as application data.

    `app.api.schemas.instructor` maps this to the wire model, adding `inference_health` (the one
    field this view does not carry — see the module docstring) and reading `stages` off
    `session.session.stages` rather than a second field here.
    """

    session: SessionDetailView
    world_truth: WorldTruth
    caller_belief: CallerBelief
    gate_turns: tuple[GateTurnEntry, ...]
    card: OperatorCard | None
    handoff: HandoffSnapshot | None
    assignments: tuple[DdsWorkItemView, ...]
    resources: tuple[EmergencyResourceView, ...]
    call_state: CallStateView
    last_seq_no: int


class GetInstructorSessionOverview:
    """`getInstructorSessionOverview` (`openapi.yaml`): `INSTRUCTOR`/`ADMIN` only, a pure read."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser
    ) -> InstructorSessionOverviewView:
        if not user.is_instructor_or_admin:
            raise ForbiddenForRoleError(
                f"the caller may not read the instructor overview of session {session_id}: "
                "INSTRUCTOR/ADMIN only"
            )
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)

            detail = await assemble_session_detail(uow, session, viewer=user, clock=self._clock)
            events = tuple(await uow.events.read(session_id))
            last_seq_no = events[-1].seq_no if events else 0

            incident_id = session.incident.incident_id
            world_truth = await uow.world_truth.get(incident_id)
            if world_truth is None:  # pragma: no cover - written inside createSession (D3)
                raise WorldStateMissingError(f"incident {incident_id} has no WorldTruth row")
            caller_belief = await uow.caller_beliefs.get(incident_id)
            if caller_belief is None:  # pragma: no cover - written inside createSession (D3)
                raise WorldStateMissingError(f"incident {incident_id} has no CallerBelief row")

            card = await uow.operator_cards.get(incident_id)
            handoff = await _handoff(uow, events)
            assignments = await _assignments(uow, session)
            resources = await _resources(uow, session, self._clock)

            await uow.commit()

        return InstructorSessionOverviewView(
            session=detail,
            world_truth=world_truth,
            caller_belief=caller_belief,
            gate_turns=_gate_turns(events),
            card=card,
            handoff=handoff,
            assignments=assignments,
            resources=resources,
            call_state=project_call_state(events),
            last_seq_no=last_seq_no,
        )


# -------------------------------------------------------------------------------------------
# Reads and folds
# -------------------------------------------------------------------------------------------


async def _handoff(uow: UnitOfWork, events: Sequence[SessionEvent]) -> HandoffSnapshot | None:
    """The snapshot the log names, or `None` for a session that has not handed off yet.

    Same read `app.application.reports.assemble_report._handoff` does, over the same
    `HANDOFF_CREATED` event: the snapshot id the log carries, nothing else.
    """
    for event in events:
        if event.event_type is EventType.HANDOFF_CREATED:
            snapshot_id = event.payload.get("snapshot_id")
            if snapshot_id is not None:
                return await uow.handoffs.get(SnapshotId(UUID(str(snapshot_id))))
    return None


async def _assignments(uow: UnitOfWork, session: SimulationSession) -> tuple[DdsWorkItemView, ...]:
    """Every leg of every DDS stage, verbatim (the instructor's reading of `DdsWorkItem`, see the
    module docstring). At most one DDS stage exists today (SPEC §13); the loop is written for the
    role chain the domain model already allows."""
    items: list[DdsWorkItemView] = []
    for stage in session.stages:
        if stage.role_type is not RoleType.DDS:
            continue
        legs = await uow.dds_assignments.list_for_stage(stage.role_stage_id)
        if not legs:
            continue
        snapshot = await uow.handoffs.get(legs[0].snapshot_id)
        if snapshot is None:  # pragma: no cover - `dds_assignments.snapshot_id` is RESTRICT
            continue
        projected = project_legs(
            legs_in_recipient_order(snapshot, legs),
            await uow.resources.list_for_session(session.id),
            await uow.resources.dispatch_history(session.id),
        )
        missing = missing_field_paths(snapshot)
        items.extend(_leg_work_item(leg, snapshot, missing) for leg in projected)
    return tuple(items)


def _leg_work_item(
    leg: DDSAssignment, snapshot: HandoffSnapshot, missing: tuple[str, ...]
) -> DdsWorkItemView:
    """One `DdsWorkItem` per leg, every field the leg's own — the mirror image of
    `work_item_view`'s primary-leg/min/union projection (see the module docstring)."""
    return DdsWorkItemView(
        assignment_id=UUID(str(leg.assignment_id)),
        incident_id=UUID(str(snapshot.incident_id)),
        role_stage_id=UUID(str(leg.role_stage_id)),
        snapshot_id=UUID(str(snapshot.snapshot_id)),
        service_type=leg.service_type,
        state=leg.state,
        card_values=dict(snapshot.card_values),
        recipient_services=tuple(snapshot.recipient_services),
        handoff_content_sha256=snapshot.content_sha256,
        received_at_offset_ms=leg.received_at_offset_ms,
        acknowledged_at_offset_ms=leg.acknowledged_at_offset_ms,
        dispatched_at_offset_ms=leg.dispatched_at_offset_ms,
        closed_at_offset_ms=leg.closed_at_offset_ms,
        closure_reason=leg.closure_reason,
        selected_resource_ids=tuple(UUID(str(value)) for value in leg.selected_resource_ids),
        dispatched_resource_ids=tuple(UUID(str(value)) for value in leg.dispatched_resource_ids),
        missing_field_paths=missing,
    )


async def _resources(
    uow: UnitOfWork, session: SimulationSession, clock: Clock
) -> tuple[EmergencyResourceView, ...]:
    """The whole resource board, exactly as `listDdsResources` projects it (SPEC §11)."""
    board = await uow.resources.list_for_session(session.id)
    return resource_views(
        board, stage_state=_stage_state(session), now_ms=sim_now_ms(session, clock.now())
    )


def _stage_state(session: SimulationSession) -> DDSStageState:
    """The DDS stage's state, which `EmergencyResourceView.selectable` is relative to — the same
    fallback `app.application.dds.list_resources._stage_state` uses: `RECEIVED` (nothing
    selectable) while no DDS stage is active, so the instructor watching the 112 half still gets
    an honest board rather than an error."""
    stage = dds_stage_of(session)
    if stage is not None and isinstance(stage.state, DDSStageState):
        return stage.state
    for other in session.stages:
        if other.role_type is RoleType.DDS and isinstance(other.state, DDSStageState):
            return other.state
    return DDSStageState.RECEIVED


def _gate_turns(events: Sequence[SessionEvent]) -> tuple[GateTurnEntry, ...]:
    """One `GateTurnEntry` per `FACT_GATE_EVALUATED` event, in log order — the inverse of
    `app.application.dialogue.events.fact_gate_evaluated_payload`."""
    turns: list[GateTurnEntry] = []
    for event in events:
        if event.event_type is not EventType.FACT_GATE_EVALUATED:
            continue
        payload = event.payload
        decisions = tuple(
            GateDecisionEntry(
                fact_id=str(item["fact_id"]),
                outcome=GateOutcome(str(item["outcome"])),
                reason=GateReason(str(item["reason"])),
            )
            for item in payload.get("decisions") or ()
        )
        turns.append(
            GateTurnEntry(
                turn_index=int(payload.get("turn_index", 0)),
                at_offset_ms=int(payload.get("at_offset_ms", event.monotonic_offset_ms)),
                decisions=decisions,
                allowed_fact_ids=tuple(
                    str(value) for value in payload.get("allowed_fact_ids") or ()
                ),
                spontaneous_attached=tuple(
                    str(value) for value in payload.get("spontaneous_attached") or ()
                ),
                withheld_count=int(payload.get("withheld_count", 0)),
            )
        )
    return tuple(turns)
