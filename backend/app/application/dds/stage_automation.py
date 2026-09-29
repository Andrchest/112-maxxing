"""The DDS stage's SIMULATION triggers, fired after every tick (D6, D7, §10.8).

D6: *"simulation → `first_en_route`, `first_arrived`, `work_started`, `incident_resolved`.
Simulation triggers pass through the same state machine and are rejected the same way when
invalid."* This module is the application shell that fires them, and it is wired as one more
`after_tick` hook of the `SimulationRunner`, beside `advance_call_flow` — the same seam, for the
same reason: the loop drives the stage, and the loop must not import a role slice.

The rules it obeys:

* **actor `SIMULATION`**, never the trainee. A unit arriving is not something the trainee did;
* **its own transaction**, opened after the tick's has committed, taking the same `SELECT … FOR
  UPDATE` row lock. It never runs inside the tick, which would deadlock against it;
* **idempotent.** It fires only what the machine accepts from the current state, so running it
  twice fires nothing the second time and a tick in which nothing moved writes nothing at all;
* **one tick may cross several states.** A long tick can walk a unit `DISPATCHED -> EN_ROUTE ->
  ON_SCENE -> WORKING` in one go (`world/resource_movement.py` fires every due transition), so the
  loop below keeps firing while the machine accepts, and the stage arrives where the board is;
* **the guards see only the units attached to this stage's legs** (E9 analyst R6).
  `guard_any_dispatched_reached(...)` counts any unit at or past a status and
  `ResourceAvailability.initial_status` may be any status, so an unattached scenario unit must not
  be able to drive this stage.

**`incident_resolved` and the resolution condition.** Its guard reads
`GuardRuntime.resolution_condition_met`, which is a *verdict*, not a query. Evaluating the
scenario's `expected_response.resolution_condition` needs the live `WorldState` — world truth,
caller belief, the board and the folded `EventIndex` — and D3 forbids this package from holding
any path to the first two. So the evaluation happens where the `WorldState` already is
(`app.application.simulation.tick_session.TickSession.resolution_condition_met`) and arrives here
as a **boolean**, through a callable the composition root injects. This module therefore asks for
the verdict only in `WORKING`, the one state `incident_resolved` fires from, and never learns
anything else about the world.

**Card-status deadlines (HLD 70 §70.3.5, I3 E4a).** The same hook, in the same transaction and
before anything else, asks the event store to flush the card-status deadlines due at the running
offset (`EventStore.flush_deadlines`): a leg that has not been accepted within
`timers.accept_within_ms` of its `HANDOFF_RECEIVED` turns the card `NOT_NOTIFIED`, a card whose
legs are not all completed `timers.not_completed_after_ms` after the handoff turns it
`NOT_COMPLETED`. Each such `DDS_CARD_STATUS_CHANGED` is SIMULATION-authored and stamped with its
**deadline** offset, not with this tick's, so the stream does not depend on the tick rate (INV 7):
a trainee command in between flushes the same events through the same rule before its own. The
flush runs for every ACTIVE session — a lesson card waiting in a queue times like any other — and
writes nothing when no deadline changes the status.

**Leg statuses (I3 E5a, HLD 70 §70.4.4).** In `RESOURCE_PICKER` mode the same hook mirrors every
leg's `ServiceResponseStatus` from its `state` by the picker map (`mirror_leg_status`: `RECEIVED →
RECEIVED`, `ACKNOWLEDGED`/`RESOURCE_SELECTION`/`DISPATCHED → ACCEPTED`, `EN_ROUTE →
RESPONSE_STARTED`, …, `RESOLVED → COMPLETED`), one `SERVICE_RESPONSE_TRANSITIONS` step at a time,
as SIMULATION with `source: PICKER_MIRROR`, each step one `DDS_SERVICE_STATUS_SET` and one history
row — after every stage trigger it fires and once per run to catch up with the trainee's commands,
so the report and the lists speak one vocabulary in both modes. In `MEMO_STATUSES` mode it fires
**no** stage trigger and mirrors nothing: the legs move by the trainee and by scripted responders,
and the stage leaves `ACKNOWLEDGED` only through the trainee's `close`.

**Scripted responders (I3 E5b, HLD 70 §70.4.5).** In memo mode a `SCRIPTED` leg — a notified
service no ДДС participant is bound to — walks the scenario's `expected_response.responders` script
(`DEFAULT` or its own, `app.domain.dds.responders`): every step due by the running offset is fired
as SIMULATION (`source: SCRIPTED_RESPONDER`), one `SERVICE_RESPONSE_TRANSITIONS` step at a time, and
**stamped with its due offset** (`HANDOFF_RECEIVED` + `after_ms`), not with this tick's. The due
steps of every scripted leg are appended in due-offset order, one append per due offset, *before*
the deadline flush, so the event store's flush-before-append rule interleaves the card-status
deadlines — and settles the card status each step causes — exactly where they fall: the stream is
the same at any tick rate (INV 7). The script is scenario data, so it
reaches this module only through `ResponderProbe`, bound by the composition root to the runner-side
`app.application.simulation.responder_scripts` (INV 3); the service's status policy comes from the
reference pack the session recorded, like every DDS read. A step the machine refuses (a script the
session's catalog no longer allows) stops that leg's script and is logged — never raised into the
runner.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from itertools import groupby
from uuid import NAMESPACE_URL, UUID, uuid5

from app.application.dds.call_endpoint import BROWSER_ONLY, CallEndpointChooser
from app.application.dds.command_context import dds_stage_of, history_entries, is_memo
from app.application.ports.clock import Clock
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.reference.card_schemas import session_pack_id
from app.application.reference.queries import reference_catalog
from app.application.sessions.guard_context import build_guard_runtime
from app.application.simulation.sim_time import running_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import SessionId, UserId
from app.domain.dds.assignment import DDSAssignment, fire_response_trigger
from app.domain.dds.call import (
    CallEndpoint,
    CallSelectionReason,
    DdsCall,
    DdsCallDirection,
    DdsCallKind,
    start_call,
)
from app.domain.dds.card_status import mirror_leg_status
from app.domain.dds.personas import resolve_persona
from app.domain.dds.policy import StatusPolicy, policy_of
from app.domain.dds.responders import (
    ScriptedResponders,
    ScriptedStep,
    ScriptReport,
    due_scripted_steps,
    persona_override_for,
    script_for,
    step_trigger,
)
from app.domain.dds.response import (
    TERMINAL_RESPONSE_STATUSES,
    LegResponder,
    ServiceResponseStatus,
    StatusSource,
)
from app.domain.enums import ActorType, DDSStageState, SessionState
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.routing.dial_plan import phone_extension
from app.domain.session.session import RoleStage, SimulationSession
from app.domain.session.variants import DdsBrigadeCall

__all__ = [
    "SIMULATION_TRIGGER_BY_STATE",
    "DdsStageAutomation",
    "ResolutionProbe",
    "ResponderProbe",
    "fire_due_scripted_steps",
    "inbound_call_id",
]

logger = logging.getLogger(__name__)

SIMULATION_TRIGGER_BY_STATE: dict[DDSStageState, str] = {
    DDSStageState.DISPATCHED: "first_en_route",
    DDSStageState.EN_ROUTE: "first_arrived",
    DDSStageState.ARRIVED: "work_started",
    DDSStageState.WORKING: "incident_resolved",
}
"""§10.8's four SIMULATION rows of `DDS_TRANSITIONS`, keyed by the state each fires from.

Exactly one trigger per state, which is what makes the loop below terminate: every fired trigger
moves the stage to a state further along the mapping, and `RESOLVED` is not a key.
"""

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)

type ResolutionProbe = Callable[[SessionId], Awaitable[bool]]
"""`expected_response.resolution_condition`, evaluated elsewhere and handed here as a boolean."""

type ResponderProbe = Callable[[SessionId], Awaitable[ScriptedResponders | None]]
"""`expected_response.responders`, read runner-side and handed here (INV 3, I3 E5b)."""


async def _no_responders(_session_id: SessionId) -> ScriptedResponders | None:
    return None


class DdsStageAutomation:
    """Fire the DDS stage's SIMULATION triggers for one session (an `after_tick` hook)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        resolution_probe: ResolutionProbe,
        responder_probe: ResponderProbe = _no_responders,
        reference: ReferencePort | None = None,
        endpoints: CallEndpointChooser = BROWSER_ONLY,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._resolution_probe = resolution_probe
        self._responder_probe = responder_probe
        self._reference = reference
        #: I3 E6e (§80.3.7): a brigade's INBOUND call rings the callee's softphone when it has a
        #: live registration, else the browser widget.
        self._endpoints = endpoints

    async def __call__(self, session_id: SessionId) -> bool:
        """Advance the DDS stage as far as the board allows; `True` when anything fired."""
        resolution_met: bool | None = None
        # I7 E48: the probe opens a Unit of Work of its own, so it is asked here — before this
        # hook's transaction takes a pooled connection — and never from inside it. Asked inside,
        # every ticking memo session held one connection while waiting for a second, and twenty
        # sessions ticking at once exhausted the pool: every tick and every request then waited
        # the pool's 30 s timeout (docs/benchmarks/load.md §4). The probe caches per session.
        responders = await self._responder_probe(session_id)
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None or session.state is not SessionState.ACTIVE:
                await uow.commit()
                return False
            now_ms = running_ms(session, self._clock.now())
            stage = dds_stage_of(session)
            if stage is not None and is_memo(session):
                # Memo mode: stage automation drives legs only, never the stage (§70.4.4) — the
                # scripted legs first, so the deadline flush below sees their due-stamped steps.
                legs = await uow.dds_assignments.list_for_stage(stage.role_stage_id)
                scripted = await self._play_scripts(uow, session_id, legs, now_ms, responders)
                flushed = await uow.events.flush_deadlines(session_id, now_ms)
                rang = await self._ring_call_in_steps(uow, session, stage, legs, now_ms, responders)
                moved = scripted or bool(flushed) or rang
                # I7 E48: an idle tick wrote nothing but the row lock, so it ends without a commit
                # (rolled back on exit) and spares a WAL flush — unless the flush above set a leg's
                # sticky `accept_missed`, the one write it can make without an event.
                if moved or await _accept_missed_marked(uow, stage, legs):
                    await uow.commit()
                return moved
            flushed = await uow.events.flush_deadlines(session_id, now_ms)
            if stage is None:
                await uow.commit()
                return bool(flushed)

            legs = await uow.dds_assignments.list_for_stage(stage.role_stage_id)
            if not legs:
                await uow.commit()
                return bool(flushed)
            legs, mirrored = await _mirror_responses(uow, session_id, legs, now_ms)

            board = await uow.resources.list_for_session(session_id)
            leg_ids = {leg.assignment_id for leg in legs}
            attached = {
                str(stored.resource.resource_id): stored.resource
                for stored in board
                if stored.assignment_id in leg_ids
            }
            log = await uow.events.read(session_id)

            fired = bool(flushed) or mirrored
            while True:
                state = session.stage(stage.role_stage_id).state
                assert isinstance(state, DDSStageState)
                trigger = SIMULATION_TRIGGER_BY_STATE.get(state)
                if trigger is None:
                    break
                if trigger == "incident_resolved" and resolution_met is None:
                    resolution_met = await self._resolution_probe(session_id)
                runtime = build_guard_runtime(
                    log,
                    scenario_valid=True,
                    inference_ready=True,
                    resolution_condition_met=bool(resolution_met),
                )
                try:
                    session, events = session.fire_stage_trigger(
                        stage.role_stage_id,
                        trigger,
                        actor=_SIMULATION,
                        now_ms=now_ms,
                        runtime=runtime,
                        assignment=legs[0],
                        resources=attached,
                    )
                except InvalidTransitionError:
                    # The board has not reached what this trigger needs yet. Not an error: the
                    # next tick asks again, which is what "idempotent" means here.
                    break
                await uow.sessions.save(session)
                stored_events = await uow.events.append(session_id, events)
                log = [*log, *stored_events]
                moved_state = session.stage(stage.role_stage_id).state
                assert isinstance(moved_state, DDSStageState)
                legs = await _mirror(uow, legs, moved_state)
                legs, _mirrored = await _mirror_responses(uow, session_id, legs, now_ms)
                fired = True

            await uow.commit()

        if fired:
            logger.debug("DDS stage automation advanced session %s", session_id)
        return fired

    async def _play_scripts(
        self,
        uow: UnitOfWork,
        session_id: SessionId,
        legs: list[DDSAssignment],
        now_ms: int,
        responders: ScriptedResponders | None,
    ) -> bool:
        """Fire every due scripted step of the session's `SCRIPTED` legs (see the module
        docstring); `True` when any was fired."""
        open_scripted = [
            leg
            for leg in legs
            if leg.responder is LegResponder.SCRIPTED
            and leg.response_status not in TERMINAL_RESPONSE_STATUSES
        ]
        if not open_scripted:
            return False
        log = await uow.events.read(session_id)
        catalog = reference_catalog(self._reference).services(session_pack_id(log))
        moved, events = fire_due_scripted_steps(
            open_scripted,
            responders,
            now_ms,
            policy=lambda leg: policy_of(catalog, leg.service_type),
        )
        if not events:
            return False
        for leg in moved:
            await uow.dds_assignments.save(leg)
        # One append per due offset: the store settles the card status a status event causes at
        # the end of each append, so appending a whole tick's steps at once would stamp that
        # change with the batch's last offset — and a slower tick would batch more (INV 7).
        stored = []
        for _offset, group in groupby(events, key=lambda event: event.monotonic_offset_ms):
            stored.extend(await uow.events.append(session_id, list(group)))
        await uow.dds_assignments.add_history(history_entries(session_id, stored))
        return True

    async def _ring_call_in_steps(
        self,
        uow: UnitOfWork,
        session: SimulationSession,
        stage: RoleStage,
        legs: Sequence[DDSAssignment],
        now_ms: int,
        responders: ScriptedResponders | None,
    ) -> bool:
        """Start an INBOUND call for each due, not yet rung `report: CALL_IN` step of a leg the
        trainee plays (see the module docstring); `True` when one was started."""
        if session.variants.dds_brigade_call is not DdsBrigadeCall.ON:
            return False
        if stage.state not in _CALL_HOLDING_STATES:
            return False
        trainee_legs = [
            leg
            for leg in sorted(
                legs, key=lambda item: (item.received_at_offset_ms, item.service_type)
            )
            if leg.responder is LegResponder.TRAINEE
            and leg.response_status not in TERMINAL_RESPONSE_STATUSES
        ]
        if not trainee_legs:
            return False
        log: list[SessionEvent] | None = None
        started = False
        for leg in trainee_legs:
            script = script_for(responders, leg.service_type)
            due = due_scripted_steps(leg.response_status, leg.received_at_offset_ms, script, now_ms)
            for step, due_at in due:
                if step.report is not ScriptReport.CALL_IN:
                    continue
                call_id = inbound_call_id(session.id, leg, script.index(step))
                if await uow.dds_calls.get(session.id, call_id) is not None:
                    continue
                callee = _callee_of(session, stage, leg)
                if callee is None:
                    break
                if await uow.dds_calls.live_for_user(session.id, callee) is not None:
                    break  # the line is busy: the step rings once it is free
                if log is None:
                    log = list(await uow.events.read(session.id))
                at = max(due_at, _line_free_at(log, callee))
                callee_user = await uow.users.get(callee)
                endpoint = await self._endpoints.choose(
                    None if callee_user is None else callee_user.username
                )
                call, event = self._inbound_call(
                    log, session, leg, call_id, callee, at, responders, endpoint
                )
                stored = await uow.events.append(session.id, [event])
                log.extend(stored)
                started_id = next(
                    item.id for item in stored if item.event_type is EventType.DDS_CALL_STARTED
                )
                await uow.dds_calls.add(call, started_event_id=UUID(str(started_id)))
                started = True
                break  # one line per workstation: the next due CALL_IN waits for this one
        return started

    def _inbound_call(
        self,
        log: Sequence[SessionEvent],
        session: SimulationSession,
        leg: DDSAssignment,
        call_id: UUID,
        callee: UserId,
        at: int,
        responders: ScriptedResponders | None,
        endpoint: CallEndpoint = CallEndpoint.BROWSER,
    ) -> tuple[DdsCall, DomainEvent]:
        """`[*] --start--> DIALING` of the brigade's INBOUND call (§80.3.2)."""
        catalog = reference_catalog(self._reference)
        pack_id = session_pack_id(log)
        services = catalog.services(pack_id)
        entry = None if services is None else services.get(leg.service_type)
        persona = resolve_persona(
            catalog.personas(pack_id),
            code=None if entry is None else entry.code,
            kind=None if entry is None else entry.kind.value,
            override=persona_override_for(responders, leg.service_type),
        )
        extension = None if services is None else phone_extension(services, leg.service_type)
        return start_call(
            call_id=call_id,
            session_id=session.id,
            kind=DdsCallKind.SERVICE_HEAD,
            direction=DdsCallDirection.INBOUND,
            dialed=extension or str(leg.service_type),
            endpoint=endpoint,
            actor=_SIMULATION,
            now_ms=at,
            selection_reason=CallSelectionReason.INBOUND_SCRIPT,
            assignment_id=leg.assignment_id,
            service_type=leg.service_type,
            persona_id=None if persona is None else persona.id,
            callee_user_id=callee,
        )


async def _accept_missed_marked(
    uow: UnitOfWork, stage: RoleStage, before: Sequence[DDSAssignment]
) -> bool:
    """Whether this transaction's deadline flush set `accept_missed` on any of the stage's legs."""
    was = {leg.assignment_id: leg.accept_missed for leg in before}
    after = await uow.dds_assignments.list_for_stage(stage.role_stage_id)
    return any(leg.accept_missed and not was.get(leg.assignment_id, False) for leg in after)


_CALL_HOLDING_STATES = frozenset({DDSStageState.RECEIVED, DDSStageState.ACKNOWLEDGED})
"""The memo states a ДДС call may be live in (`dds_call_flow`): the ones a brigade rings in."""


def _leg_order(leg: DDSAssignment) -> tuple[int, str]:
    """A stable leg order: the legs of one handoff share the offset and their ids are random."""
    return leg.received_at_offset_ms, leg.service_type


def inbound_call_id(session_id: SessionId, leg: DDSAssignment, step_index: int) -> UUID:
    """The INBOUND call of one `report: CALL_IN` step — the same id on every tick (INV 7)."""
    return uuid5(NAMESPACE_URL, f"sim-112:call-in:{session_id}:{leg.assignment_id}:{step_index}")


def _callee_of(session: SimulationSession, stage: RoleStage, leg: DDSAssignment) -> UserId | None:
    """The workstation a brigade's call rings: the leg's participant, else the DDS stage's, else
    the first ДДС participant of the session."""
    if leg.bound_user_id is not None:
        return leg.bound_user_id
    if stage.participant_user_id is not None:
        return stage.participant_user_id
    for participant in session.participants:
        if session.plays_dds(participant.user_id):
            return participant.user_id
    return None


def _line_free_at(log: Sequence[SessionEvent], user_id: UserId) -> int:
    """When `user_id`'s line last became free: their latest `DDS_CALL_ENDED`, else 0."""
    wanted = str(user_id).lower()
    mine = {
        str(event.payload.get("call_id", "")).lower()
        for event in log
        if event.event_type is EventType.DDS_CALL_STARTED
        and str(event.payload.get("actor_user_id", "")).lower() == wanted
    }
    ended = [
        int(event.payload.get("at_offset_ms", event.monotonic_offset_ms))
        for event in log
        if event.event_type is EventType.DDS_CALL_ENDED
        and str(event.payload.get("call_id", "")).lower() in mine
    ]
    return max(ended, default=0)


def fire_due_scripted_steps(
    legs: Sequence[DDSAssignment],
    responders: ScriptedResponders | None,
    now_ms: int,
    *,
    policy: Callable[[DDSAssignment], StatusPolicy],
) -> tuple[list[DDSAssignment], list[DomainEvent]]:
    """The scripted legs moved by every step due by `now_ms`, and their `DDS_SERVICE_STATUS_SET`s
    in due-offset order (ties: leg order, then script order). Pure — the INV 7 unit of this module.

    Legs are taken in a stable order (`received_at_offset_ms`, `service_type`: the legs of one
    handoff share the offset and their ids are random). A leg still `ADDED` whose next step is not
    `RECEIVED` gets the implicit `receive` at the same offset first (§70.4.2). A step the machine
    refuses stops that leg's script (logged).
    """
    ordered = sorted(legs, key=lambda item: (item.received_at_offset_ms, item.service_type))
    planned: list[tuple[int, int, int, DDSAssignment, ScriptedStep]] = []
    for leg_index, leg in enumerate(ordered):
        script = script_for(responders, leg.service_type)
        due = due_scripted_steps(leg.response_status, leg.received_at_offset_ms, script, now_ms)
        for step_index, (step, at) in enumerate(due):
            planned.append((at, leg_index, step_index, leg, step))
    planned.sort(key=lambda item: (item[0], item[1], item[2]))

    current = {leg.assignment_id: leg for leg in ordered}
    stopped: set[object] = set()
    events: list[DomainEvent] = []
    for at, _leg_index, _step_index, original, step in planned:
        if original.assignment_id in stopped:
            continue
        leg = current[original.assignment_id]
        leg_policy = policy(leg)
        try:
            if leg.response_status is ServiceResponseStatus.ADDED and (
                step.status is not ServiceResponseStatus.RECEIVED
            ):
                leg, received = fire_response_trigger(
                    leg,
                    "receive",
                    actor=_SIMULATION,
                    now_ms=at,
                    source=StatusSource.SCRIPTED_RESPONDER,
                    status_policy=leg_policy,
                )
                events.append(received)
            trigger = step_trigger(leg.response_status, step.status, leg_policy)
            if trigger is None:
                raise InvalidTransitionError(
                    "ServiceResponseStatus",
                    leg.response_status.value,
                    f"script {step.status.value}",
                    "not one scripted step",
                    to_state=step.status.value,
                )
            leg, event = fire_response_trigger(
                leg,
                trigger,
                actor=_SIMULATION,
                now_ms=at,
                source=StatusSource.SCRIPTED_RESPONDER,
                status_policy=leg_policy,
                order_number=step.order_number,
                comment_ru=step.comment_ru,
            )
        except InvalidTransitionError:
            logger.warning(
                "scripted responder of leg %s (%s) stopped at %s: %s is not playable",
                leg.assignment_id,
                leg.service_type,
                leg.response_status.value,
                step.status.value,
            )
            stopped.add(original.assignment_id)
            current[original.assignment_id] = leg
            continue
        events.append(event)
        current[original.assignment_id] = leg
    moved = [current[leg.assignment_id] for leg in ordered if current[leg.assignment_id] is not leg]
    return moved, events


async def _mirror(
    uow: UnitOfWork, legs: list[DDSAssignment], state: DDSStageState
) -> list[DDSAssignment]:
    """Write the stage's new state onto every leg (R1) and return them as saved."""
    updated: list[DDSAssignment] = []
    for leg in legs:
        moved = leg.model_copy(update={"state": state})
        await uow.dds_assignments.save(moved)
        updated.append(moved)
    return updated


_PICKER_PATH: tuple[ServiceResponseStatus, ...] = (
    ServiceResponseStatus.ADDED,
    ServiceResponseStatus.RECEIVED,
    ServiceResponseStatus.ACCEPTED,
    ServiceResponseStatus.RESPONSE_STARTED,
    ServiceResponseStatus.ARRIVED,
    ServiceResponseStatus.WORKING,
    ServiceResponseStatus.COMPLETED,
)
"""The statuses the picker map reaches, in `SERVICE_RESPONSE_TRANSITIONS` order."""

_PICKER_STEP: dict[ServiceResponseStatus, str] = {
    ServiceResponseStatus.ADDED: "receive",
    ServiceResponseStatus.RECEIVED: "accept",
    ServiceResponseStatus.ACCEPTED: "start_response",
    ServiceResponseStatus.RESPONSE_STARTED: "arrive",
    ServiceResponseStatus.ARRIVED: "start_work",
    ServiceResponseStatus.WORKING: "complete",
}
"""The one trigger that moves a picker leg one step along `_PICKER_PATH`."""


async def _mirror_responses(
    uow: UnitOfWork, session_id: SessionId, legs: list[DDSAssignment], now_ms: int
) -> tuple[list[DDSAssignment], bool]:
    """Walk every leg's response status up to the picker map of its `state` (see the module
    docstring); `True` when any step was taken. A status the map is behind (never the case for a
    monotonic stage) is left alone."""
    events = []
    moved_by_id: dict[object, DDSAssignment] = {}
    # A stable order — the legs share `received_at_offset_ms` and their ids are random — so the
    # mirrored stream is the same in every run of the same actions (INV 7).
    for leg in sorted(legs, key=lambda item: (item.received_at_offset_ms, item.service_type)):
        target = ServiceResponseStatus(
            mirror_leg_status(leg.state, leg.closure_reason, leg.response_status.value)
        )
        moved = leg
        while (
            moved.response_status in _PICKER_PATH
            and target in _PICKER_PATH
            and _PICKER_PATH.index(moved.response_status) < _PICKER_PATH.index(target)
        ):
            moved, event = fire_response_trigger(
                moved,
                _PICKER_STEP[moved.response_status],
                actor=_SIMULATION,
                now_ms=now_ms,
                source=StatusSource.PICKER_MIRROR,
            )
            events.append(event)
        if moved is not leg:
            await uow.dds_assignments.save(moved)
        moved_by_id[leg.assignment_id] = moved
    updated = [moved_by_id[leg.assignment_id] for leg in legs]
    if events:
        stored = await uow.events.append(session_id, events)
        await uow.dds_assignments.add_history(history_entries(session_id, stored))
    return updated, bool(events)
