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
**no** stage trigger and mirrors nothing: the legs move by the trainee (and, from E5b, by scripted
responders), and the stage leaves `ACKNOWLEDGED` only through the trainee's `close`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.application.dds.command_context import dds_stage_of, history_entries, is_memo
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.sessions.guard_context import build_guard_runtime
from app.application.simulation.sim_time import running_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import SessionId
from app.domain.dds.assignment import DDSAssignment, fire_response_trigger
from app.domain.dds.card_status import mirror_leg_status
from app.domain.dds.response import ServiceResponseStatus, StatusSource
from app.domain.enums import ActorType, DDSStageState, SessionState

__all__ = ["SIMULATION_TRIGGER_BY_STATE", "DdsStageAutomation", "ResolutionProbe"]

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


class DdsStageAutomation:
    """Fire the DDS stage's SIMULATION triggers for one session (an `after_tick` hook)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        resolution_probe: ResolutionProbe,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._resolution_probe = resolution_probe

    async def __call__(self, session_id: SessionId) -> bool:
        """Advance the DDS stage as far as the board allows; `True` when anything fired."""
        resolution_met: bool | None = None
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None or session.state is not SessionState.ACTIVE:
                await uow.commit()
                return False
            now_ms = running_ms(session, self._clock.now())
            flushed = await uow.events.flush_deadlines(session_id, now_ms)
            stage = dds_stage_of(session)
            if stage is None:
                await uow.commit()
                return bool(flushed)

            legs = await uow.dds_assignments.list_for_stage(stage.role_stage_id)
            if not legs or is_memo(session):
                # Memo mode: stage automation drives legs only, never the stage (§70.4.4); the
                # scripted responders that will drive them arrive with E5b.
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
