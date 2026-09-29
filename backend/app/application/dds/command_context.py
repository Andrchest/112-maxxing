"""The ONE DDS command pipeline (D5, D8, SPEC §11; §10.7-§10.9).

Eight commands, one gate. Every `/dds/*` write but `acknowledgeNotification` — which both trainee
roles may issue and which therefore has its own, smaller pipeline — goes through
`DdsCommandGate.open`, which runs
D5's single Unit of Work transaction and D8's two-gate authorisation in the same fixed order
`app.application.operator.command_context` uses for the 112 side:

1. `SessionRepository.get_for_update` — the `SELECT … FOR UPDATE` row lock of §20.8, taken first,
   which is what serialises two concurrent commands on one session. A missing session is
   `404 NOT_FOUND`;
2. the session is `ACTIVE`, else `409 SESSION_NOT_ACTIVE`;
3. `resolve_participant` — D8's first gate, `403 PARTICIPANT_NOT_ASSIGNED`;
4. the caller is a `TRAINEE` account **and** is the participant bound to the session's active
   `RoleStage` — in memo mode any ДДС participant of the session (`may_command`, I3 E5b) —
   **and** that stage's role is `DDS`, else `403 FORBIDDEN_FOR_ROLE`. An instructor
   may read the work item and the board; they may never issue a command here (SPEC §7);
5. the command's action id — `openapi.yaml`'s `x-action` — is a member of
   `DDSModule.available_actions(stage_state, variants=session.variants)`, else
   `409 ACTION_NOT_AVAILABLE` — the memo table under `dds_mode: MEMO_STATUSES` (I3 E5a);
6. the use case runs: it calls the domain, persists only what changed and appends its
   `DomainEvent`s through this context;
7. `commit()`. Publishing happens inside the Unit of Work, after the commit (§20.8, §40.6).

`tick_after_command` (D7) is deliberately **not** here, for the same reason as on the 112 side: it
must run after the transaction commits, so the endpoint awaits it.

**Everything the stage is about is loaded once, here**: the N `dds_assignments` legs, the frozen
`HandoffSnapshot` they point at, the resource board and the event log. A command reads them off
the context rather than issuing its own query, so no two commands can disagree about what the
stage currently is.

**Two clocks, deliberately.** `now_ms` is the session offset every *event* is stamped with
(SPEC §39), exactly as on the 112 side. `sim_now_ms` is that offset scaled by `time_scale`, i.e. the
same simulated milliseconds the tick stamps `emergency_resources.status_changed_at_offset_ms` with
and the same scale `ResourceAvailability` windows are written in (§30.5). Resource-machine guards
and resource timestamps therefore use `sim_now_ms`; stage transitions and event payloads use
`now_ms`. At the default `time_scale` of 1.0 the two are equal, which is why nothing before this
epic had to distinguish them.

**Nothing here can reach `WorldTruth`, `CallerBelief` or the live `OperatorCard`** (D3, SPEC §42
test 3): the gate is constructed from a Unit of Work factory, a clock and the reference pack, and no
module in this package names any of those layers, their ports or their adapters. The reference pack
gives the work item its `field_specs` (I3 E3a, HLD 70 §70.5.4): the card schema of the pack
`SESSION_CREATED.reference_pack` recorded — the log, never the `ScenarioVersion`. The same pack's
service catalog gives each leg its name and its status policy (`NO_REFUSAL` for 103; I3 E5a).

**Leg statuses (I3 E5a, HLD 70 §70.4).** `append_status_events` is how a command records
`DDS_SERVICE_STATUS_SET`s: the events are appended and the matching `dds_service_status_history`
rows are written from the *stored* events (their ids and `seq_no`s) in the same transaction.
`guard_runtime` projects `all_legs_terminal` from the legs for `memo_all_legs_terminal`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.leg_for import project_legs
from app.application.dds.views import DdsStageView, dds_stage_view
from app.application.handoff.work_item import (
    DdsWorkItemView,
    for_viewer,
    legs_in_recipient_order,
    primary_leg,
    with_card_schema,
    with_dds_marks,
    work_item_view,
)
from app.application.operator.command_context import SessionNotActiveError
from app.application.ports.clock import Clock
from app.application.ports.dds_assignment_repository import StatusHistoryEntry
from app.application.ports.reference import ReferencePort
from app.application.ports.resource_repository import (
    DispatchRecord,
    ResourceStateChange,
    StoredResource,
)
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.user_repository import UserRole
from app.application.reference.card_schemas import pack_card_schema, session_pack_id
from app.application.reference.queries import reference_catalog
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.guard_context import build_guard_runtime
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.application.simulation.sim_time import running_ms, sim_now_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import AssignmentId, IncidentId, ResourceId, SessionId, UserId
from app.domain.common.state_machine import GuardContext, GuardRuntime
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.personas import PersonaCatalog
from app.domain.dds.policy import StatusPolicy, policy_of
from app.domain.dds.resources import RESOURCE_STATE_MACHINE, EmergencyResource
from app.domain.dds.response import (
    CLOSABLE_RESPONSE_STATUSES,
    ServiceResponseStatus,
    StatusSource,
)
from app.domain.enums import ActorType, DDSStageState, ResourceStatus, RoleType, SessionState
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.card_schema import CardSchema
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import CARD_SCHEMA_V1
from app.domain.roles.dds import DDSModule
from app.domain.routing.catalog import ServiceCatalog
from app.domain.session.session import RoleStage, SimulationSession
from app.domain.session.variants import DdsMode

__all__ = [
    "ActionNotAvailableError",
    "DdsCommandContext",
    "DdsCommandGate",
    "LegNotFoundError",
    "ResourceNotFoundError",
    "ResourceUnavailableError",
    "WorkItemNotFoundError",
    "dds_stage_of",
    "fire_resource_transition",
    "history_entries",
    "is_memo",
    "load_legs",
    "may_command",
    "state_change_row",
    "status_changed_event",
    "work_item_of",
]

_DDS_MODULE = DDSModule()
"""One module instance: `DDSModule` is stateless and its tables are module-level."""


class ActionNotAvailableError(DomainError):
    """D8's second gate: the DDS stage does not offer this action now (`409`)."""

    code = "ACTION_NOT_AVAILABLE"

    def __init__(self, action_id: str, stage_state: DDSStageState) -> None:
        self.action_id = action_id
        self.stage_state = stage_state
        super().__init__(
            f"action {action_id!r} is not available in DDS stage state {stage_state.value}"
        )


class WorkItemNotFoundError(DomainError):
    """The DDS stage has no `dds_assignments` leg — nothing has been handed to it (`404`).

    Reachable only before `createHandoff`: a DDS stage becomes the session's active stage through
    the role transition, which `completeOperatorStage` can only reach after the handoff.
    """

    code = "NOT_FOUND"

    def __init__(self, session_id: SessionId) -> None:
        self.session_id = session_id
        super().__init__(f"session {session_id} has no DDS work item yet")


class LegNotFoundError(DomainError):
    """No leg with this `assignment_id` in this session's DDS stage (`404`)."""

    code = "NOT_FOUND"

    def __init__(self, assignment_id: AssignmentId) -> None:
        self.assignment_id = assignment_id
        super().__init__(f"assignment {assignment_id} is not a leg of this session's DDS stage")


def is_memo(session: SimulationSession) -> bool:
    """The session runs `dds_mode: MEMO_STATUSES` (HLD 70 §70.4.4)."""
    return session.variants.dds_mode is DdsMode.MEMO_STATUSES


def may_command(session: SimulationSession, stage: RoleStage, user_id: UserId) -> bool:
    """D8's first gate for a DDS command: the participant bound to the active DDS stage — or, in
    memo mode, **any** ДДС participant of the session (several ДДС trainees share the one DDS
    stage, each bound to a service; HLD 70 §70.4.4 `DDS_GUARDS_MEMO`, §70.4.5, I3 E5b). Which leg
    a trainee may move is the leg's own question (`guard_leg_actor_bound`)."""
    if stage.participant_user_id == user_id:
        return True
    return is_memo(session) and session.plays_dds(user_id)


def history_entries(
    session_id: SessionId, stored: Sequence[SessionEvent]
) -> list[StatusHistoryEntry]:
    """The `dds_service_status_history` rows of the stored `DDS_SERVICE_STATUS_SET`s among
    `stored` (HLD 70 §70.4.3) — each carries its event's id and `seq_no`."""
    rows: list[StatusHistoryEntry] = []
    for event in stored:
        if event.event_type is not EventType.DDS_SERVICE_STATUS_SET:
            continue
        payload = event.payload
        actor_user_id = payload.get("actor_user_id")
        completion = payload.get("completion_reason")
        rows.append(
            StatusHistoryEntry(
                session_id=session_id,
                assignment_id=AssignmentId(UUID(str(payload["assignment_id"]))),
                event_id=UUID(str(event.id)),
                seq_no=event.seq_no,
                previous_status=ServiceResponseStatus(str(payload["previous_status"])),
                new_status=ServiceResponseStatus(str(payload["new_status"])),
                order_number=payload.get("order_number"),
                comment_ru=payload.get("comment_ru"),
                completion_reason=None if completion is None else str(completion),
                source=StatusSource(str(payload["source"])),
                actor_type=event.actor_type,
                actor_user_id=None if actor_user_id is None else UUID(str(actor_user_id)),
                at_offset_ms=int(payload.get("at_offset_ms", event.monotonic_offset_ms)),
            )
        )
    return rows


class ResourceNotFoundError(DomainError):
    """No such resource on this session's board (`404`)."""

    code = "NOT_FOUND"

    def __init__(self, resource_id: ResourceId) -> None:
        self.resource_id = resource_id
        super().__init__(f"resource {resource_id} is not on this session's board")


class ResourceUnavailableError(DomainError):
    """The resource machine refused `select` (`409 RESOURCE_UNAVAILABLE`, `openapi.yaml`).

    The contract gives this operation its own code rather than the generic `INVALID_TRANSITION`,
    so the console can say "эта единица сейчас недоступна" instead of "недопустимый переход".
    """

    code = "RESOURCE_UNAVAILABLE"

    def __init__(self, resource_id: ResourceId, reason: str) -> None:
        self.resource_id = resource_id
        super().__init__(f"resource {resource_id} cannot be selected: {reason}")


def work_item_of(
    snapshot: HandoffSnapshot,
    legs: Sequence[DDSAssignment],
    schema: CardSchema = CARD_SCHEMA_V1,
) -> DdsWorkItemView:
    """The stage-wide work-item projection, legs in the operator's recipient order (R3), with the
    field specs of the session's card `schema`."""
    return with_card_schema(
        work_item_view(snapshot, legs_in_recipient_order(snapshot, legs)), snapshot, schema
    )


def dds_stage_of(session: SimulationSession) -> RoleStage | None:
    """The session's active stage, if it is a `DDS` one; `None` otherwise.

    An `OPERATOR_112` active stage returns `None`, which the caller renders as
    `403 FORBIDDEN_FOR_ROLE`: the DDS endpoints are simply not that stage's endpoints.
    """
    stage = session.current_stage
    if stage is None or stage.role_type is not RoleType.DDS:
        return None
    return stage


# ---------------------------------------------------------------------------------------------
# The context
# ---------------------------------------------------------------------------------------------


@dataclass
class DdsCommandContext:
    """Everything one DDS command acts on, inside its open transaction."""

    uow: UnitOfWork
    session: SimulationSession
    stage: RoleStage
    actor: ActorRef
    now_ms: int
    sim_now_ms: int
    log: tuple[SessionEvent, ...]
    snapshot: HandoffSnapshot
    legs: tuple[DDSAssignment, ...]
    board: tuple[StoredResource, ...]
    dispatched: tuple[DispatchRecord, ...]
    card_schema: CardSchema = CARD_SCHEMA_V1
    service_catalog: ServiceCatalog | None = None
    """The service catalog of the session's recorded reference pack (names, status policies)."""
    personas: PersonaCatalog | None = None
    """The ДДС phone's personas of the same pack (HLD 80 §80.4.1, I3 E6c); `None` without them."""
    _appended: list[SessionEvent] = field(default_factory=list)

    # -- projections ---------------------------------------------------------------------------

    @property
    def session_id(self) -> SessionId:
        """The session this command is about."""
        return self.session.id

    @property
    def incident_id(self) -> IncidentId:
        """The incident the stage's work item belongs to."""
        return self.session.incident.incident_id

    @property
    def stage_state(self) -> DDSStageState:
        """The active stage's DDS state — the single authority for the workflow (R1)."""
        state = self.stage.state
        assert isinstance(state, DDSStageState)
        return state

    @property
    def full_log(self) -> tuple[SessionEvent, ...]:
        """The log as it stands *including* what this command has appended so far."""
        return (*self.log, *self._appended)

    @property
    def last_seq_no(self) -> int:
        """The highest `seq_no` in the session's log after this command's appends."""
        events = self.full_log
        return events[-1].seq_no if events else 0

    @property
    def projected_legs(self) -> tuple[DDSAssignment, ...]:
        """The legs with their two resource lists filled (`project_legs`)."""
        return project_legs(self.legs, self.board, self.dispatched)

    @property
    def primary(self) -> DDSAssignment:
        """The leg one trainee event carries the `assignment_id` of (R5)."""
        return primary_leg(self.legs, self.snapshot)

    @property
    def memo(self) -> bool:
        """`dds_mode: MEMO_STATUSES` (I3 E5a)."""
        return is_memo(self.session)

    def leg(self, assignment_id: AssignmentId) -> DDSAssignment:
        """One leg of this stage by id; `404` when the id is not one of them."""
        for leg in self.legs:
            if leg.assignment_id == assignment_id:
                return leg
        raise LegNotFoundError(assignment_id)

    def status_policy(self, leg: DDSAssignment) -> StatusPolicy:
        """The leg's service status policy, from the pack's catalog (§70.6.3)."""
        return policy_of(self.service_catalog, leg.service_type)

    def resource(self, resource_id: ResourceId) -> StoredResource:
        """One unit of the board; `404` when the id is not this session's."""
        for stored in self.board:
            if stored.resource.resource_id == resource_id:
                return stored
        raise ResourceNotFoundError(resource_id)

    def attached_units(self) -> Mapping[str, EmergencyResource]:
        """The units attached to **this stage's** legs, as the stage guards' board (R6).

        Not the whole board: `guard_any_dispatched_reached(...)` counts any unit at or past a
        status, and `ResourceAvailability.initial_status` may be any status, so a scenario unit
        that starts `WORKING` somewhere else would otherwise satisfy `first_en_route` on its own.
        "Dispatched" is in the guard's name; attachment is how the application knows it.
        """
        ids = {leg.assignment_id for leg in self.legs}
        return {
            str(stored.resource.resource_id): stored.resource
            for stored in self.board
            if stored.assignment_id in ids
        }

    def guard_runtime(self, *, resolution_condition_met: bool = False) -> GuardRuntime:
        """`GuardRuntime` for this command, projected from the log.

        `scenario_valid` / `inference_ready` are `True` because no DDS *stage* guard reads either
        (they belong to `validate` / `start`, which this pipeline never fires), and
        `transport_ready` is `False` because the DDS stage has no call. `resolution_condition_met`
        is `False` for every trainee command — `incident_resolved` is a SIMULATION trigger and
        only `stage_automation` supplies a real verdict for it.
        """
        runtime = build_guard_runtime(
            self.full_log,
            scenario_valid=True,
            inference_ready=True,
            resolution_condition_met=resolution_condition_met,
        )
        return runtime.model_copy(
            update={
                "all_legs_terminal": bool(self.legs)
                and all(leg.response_status in CLOSABLE_RESPONSE_STATUSES for leg in self.legs)
            }
        )

    # -- writes --------------------------------------------------------------------------------

    async def append(self, events: Sequence[DomainEvent]) -> list[SessionEvent]:
        """Append `events` to the session's log, in order, inside this transaction."""
        stored = await self.uow.events.append(self.session_id, events)
        self._appended.extend(stored)
        return stored

    async def save_session(self, session: SimulationSession) -> None:
        """Persist a session the domain returned and make it this context's session."""
        await self.uow.sessions.save(session)
        self.session = session
        self.stage = session.stage(self.stage.role_stage_id)

    async def mirror_legs(self, **fields: object) -> None:
        """Write `role_stages.state` onto every leg, plus any per-leg fact fields given (R1).

        `dds_assignments.state` is a mirror and nothing else writes it. The per-leg *fact* fields
        this takes — `acknowledged_at_offset_ms`, `closed_at_offset_ms`, `closure_reason` — are
        identical on every leg because the trainee acknowledged or closed the one work item.
        `dispatched_at_offset_ms` is deliberately **not** passed here: it is per leg, and `dispatch`
        stamps only the legs that actually received a unit (R1b).
        """
        updated: list[DDSAssignment] = []
        for leg in self.legs:
            moved = leg.model_copy(update={"state": self.stage_state, **fields})
            await self.uow.dds_assignments.save(moved)
            updated.append(moved)
        self.legs = tuple(updated)

    async def save_leg(self, leg: DDSAssignment) -> DDSAssignment:
        """Persist one moved leg and put it back on this context's leg list."""
        await self.uow.dds_assignments.save(leg)
        self.legs = tuple(
            leg if item.assignment_id == leg.assignment_id else item for item in self.legs
        )
        return leg

    async def append_status_events(self, events: Sequence[DomainEvent]) -> list[SessionEvent]:
        """Append events and write the history row of every `DDS_SERVICE_STATUS_SET` among them
        (HLD 70 §70.4.3), in this transaction."""
        stored = await self.append(events)
        await self.uow.dds_assignments.add_history(history_entries(self.session_id, stored))
        return stored

    async def save_resource(
        self, stored: StoredResource, resource: EmergencyResource
    ) -> StoredResource:
        """Persist a moved unit and put it back on this context's board."""
        await self.uow.resources.save(self.session_id, resource)
        return self._replace(stored.model_copy(update={"resource": resource}))

    async def attach(
        self, stored: StoredResource, assignment_id: AssignmentId | None
    ) -> StoredResource:
        """Attach (or detach) a unit and put it back on this context's board."""
        await self.uow.resources.attach(self.session_id, stored.resource.resource_id, assignment_id)
        return self._replace(stored.model_copy(update={"assignment_id": assignment_id}))

    def _replace(self, stored: StoredResource) -> StoredResource:
        self.board = tuple(
            stored if item.resource.resource_id == stored.resource.resource_id else item
            for item in self.board
        )
        return stored

    # -- the view ------------------------------------------------------------------------------

    def work_item(self) -> DdsWorkItemView:
        """The stage-wide `DdsWorkItem` as it stands now, as this command's trainee reads it
        (`for_viewer`: the 03 service's 100-character description, I7 E55)."""
        view = work_item_of(self.snapshot, self.projected_legs, self.card_schema)
        return for_viewer(with_dds_marks(view, self.full_log), self.legs, self.actor.actor_id)

    async def stage_view(self) -> DdsStageView:
        """The `DdsStageView` this command answers with (D8)."""
        unacknowledged = await self.uow.notifications.unacknowledged_count(
            self.incident_id, audience_role=RoleType.DDS
        )
        return dds_stage_view(
            self.session,
            self.stage,
            work_item=self.work_item(),
            board=self.board,
            unacknowledged_notification_count=unacknowledged,
            now_ms=self.sim_now_ms,
            last_seq_no=self.last_seq_no,
        )


class DdsCommandGate:
    """Opens the one transaction every DDS command runs in (see the module docstring)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._reference = reference

    @asynccontextmanager
    async def open(
        self, session_id: SessionId, user: AuthenticatedUser, action_id: str | Sequence[str]
    ) -> AsyncIterator[DdsCommandContext]:
        """Run the seven steps of the module docstring around the caller's block.

        Leaving the block normally commits; an exception rolls back and publishes nothing, so a
        rejected command leaves neither a materialized change nor an event behind (D5).

        `action_id` may be several ids, which means "any of these is enough". Exactly one endpoint
        needs it: `dispatchDdsResources` is `dispatch` in `RESOURCE_SELECTION` and
        `dispatch_additional` in the three states units are already moving in — two
        `available_actions` entries of one operation, as `openapi.yaml` describes it. The
        rejection then names the first id, which is the one the contract puts in `x-action`.
        """
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if session.state is not SessionState.ACTIVE:
                raise SessionNotActiveError(session_id, session.state)

            participant = resolve_participant(session, user)
            stage = dds_stage_of(session)
            if stage is None or not may_command(session, stage, participant.user_id):
                raise ForbiddenForRoleError(
                    f"the caller is not the DDS participant of the active stage of "
                    f"session {session_id}"
                )
            if user.user_role is not UserRole.TRAINEE:
                # SPEC §7: the instructor observes and intervenes; they never complete a trainee
                # action. Reading the work item, the board and the radio log stays open to them.
                raise ForbiddenForRoleError(
                    "a trainee stage command may only be issued by a TRAINEE account"
                )

            stage_state = stage.state
            assert isinstance(stage_state, DDSStageState)
            wanted = (action_id,) if isinstance(action_id, str) else tuple(action_id)
            available = {
                action.action_id
                for action in _DDS_MODULE.available_actions(stage_state, variants=session.variants)
            }
            if not available & set(wanted):
                raise ActionNotAvailableError(wanted[0], stage_state)

            legs, snapshot = await load_legs(uow, session_id, stage)
            wall_now = self._clock.now()
            now_ms = running_ms(session, wall_now)
            log = tuple(await uow.events.read(session_id))
            catalog = reference_catalog(self._reference)
            context = DdsCommandContext(
                uow=uow,
                session=session,
                stage=stage,
                actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=user.user_id),
                now_ms=now_ms,
                sim_now_ms=sim_now_ms(session, wall_now),
                log=log,
                snapshot=snapshot,
                legs=legs,
                board=tuple(await uow.resources.list_for_session(session_id)),
                dispatched=tuple(await uow.resources.dispatch_history(session_id)),
                card_schema=pack_card_schema(catalog, log),
                service_catalog=catalog.services(session_pack_id(log)),
                personas=catalog.personas(session_pack_id(log)),
            )
            yield context
            await uow.commit()


async def load_legs(
    uow: UnitOfWork, session_id: SessionId, stage: RoleStage
) -> tuple[tuple[DDSAssignment, ...], HandoffSnapshot]:
    """The stage's legs in the operator's recipient order, and the snapshot they share.

    Every leg of one handoff points at the same `handoff_snapshots` row (the fan-out is by service,
    not by content), so one read serves them all, and the order comes from the snapshot rather than
    from the table — the legs share a `received_at_offset_ms`, so storage cannot supply it.
    """
    legs = await uow.dds_assignments.list_for_stage(stage.role_stage_id)
    if not legs:
        raise WorkItemNotFoundError(session_id)
    snapshot = await uow.handoffs.get(legs[0].snapshot_id)
    if snapshot is None:  # pragma: no cover - the FK is RESTRICT, so the row cannot vanish
        raise WorkItemNotFoundError(session_id)
    return tuple(legs_in_recipient_order(snapshot, legs)), snapshot


# ---------------------------------------------------------------------------------------------
# The resource machine step, shared by `select`, `deselect` and `dispatch`
# ---------------------------------------------------------------------------------------------


def fire_resource_transition(
    ctx: DdsCommandContext,
    resource: EmergencyResource,
    leg: DDSAssignment,
    trigger: str,
    *,
    state: DDSStageState | None = None,
) -> ResourceStatus:
    """Fire one trainee trigger on `RESOURCE_STATUS_TRANSITIONS`; raise what the machine raises.

    Two context conventions of that machine are honoured here and nowhere else (§10.7):
    `GuardContext.resources` carries **exactly one** entry — the unit being moved — and
    `GuardContext.assignment` carries the leg it hangs on, whose `state` the two unit-level guards
    read. The leg is copied with `state` first, because `dds_assignments.state` is a mirror and
    the authority is `role_stages.state` (R1); `state` overrides it for the one case where the
    stage has already moved inside this very command (`dispatch`, which fires the stage trigger
    before the units so that `guard_at_least_one_selected_available` still sees them `SELECTED`).

    `now_ms` is `sim_now_ms`: availability windows and `status_changed_at_offset_ms` are both in
    simulated milliseconds (see the module docstring).
    """
    guard_leg = leg.model_copy(
        update={"state": ctx.stage_state if state is None else state},
    )
    guard_ctx = GuardContext(
        actor=ctx.actor,
        role_type=RoleType.DDS,
        now_ms=ctx.sim_now_ms,
        session=ctx.session,
        stage=ctx.stage,
        assignment=guard_leg,
        resources={str(resource.resource_id): resource},
    )
    return RESOURCE_STATE_MACHINE.fire(resource.current_status, trigger, guard_ctx)


def status_changed_event(
    previous: EmergencyResource,
    new_status: ResourceStatus,
    trigger: str,
    at_offset_ms: int,
    assignment_id: AssignmentId | None,
) -> DomainEvent:
    """`RESOURCE_STATUS_CHANGED` for a trainee-fired unit transition (§10.13).

    The actor is `SIMULATION`, not the trainee. §10.13 types this event `actor_types =
    {SIMULATION}` while `openapi.yaml` lists it in the `x-emits` of three TRAINEE commands
    (E9 analyst §7 #10); the catalog is the typed artefact, so it wins, and the trainee's own
    action is already recorded by the `RESOURCE_SELECTED` / `RESOURCE_DESELECTED` /
    `RESOURCE_DISPATCHED` event beside it. The payload is shaped exactly like the one
    `world/resource_movement.py` emits, plus the `assignment_id` the catalog declares.
    """
    return DomainEvent(
        event_type=EventType.RESOURCE_STATUS_CHANGED,
        actor=ActorRef(actor_type=ActorType.SIMULATION),
        monotonic_offset_ms=at_offset_ms,
        payload={
            "resource_id": UUID(str(previous.resource_id)),
            "callsign": previous.callsign,
            "previous_status": previous.current_status.value,
            "new_status": new_status.value,
            "trigger": trigger,
            "assignment_id": None if assignment_id is None else UUID(str(assignment_id)),
            "source_world_event_id": None,
            "at_offset_ms": at_offset_ms,
        },
    )


def state_change_row(
    previous: EmergencyResource,
    moved: EmergencyResource,
    trigger: str,
    at_offset_ms: int,
    assignment_id: AssignmentId | None,
    session_event_id: UUID | None,
) -> ResourceStateChange:
    """The `resource_state_changes` row that goes with `status_changed_event` (§20.5, SPEC §29)."""
    return ResourceStateChange(
        resource=moved,
        previous_status=previous.current_status,
        new_status=moved.current_status,
        trigger=trigger,
        source_world_event_id=None,
        at_offset_ms=at_offset_ms,
        assignment_id=assignment_id,
        session_event_id=session_event_id,
    )
