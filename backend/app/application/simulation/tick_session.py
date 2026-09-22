"""`TickSession` — one simulation tick, one Unit of Work transaction (SPEC §12, §39; D5, D7).

The use case is the application-side shell around the three pure functions of `app.domain.world`:

1. take the `SELECT … FOR UPDATE` row lock on the session (§20.8) — a session that is not `ACTIVE`
   is a no-op, and the lock is what serialises two concurrent ticks of one session;
2. derive simulated time from persisted state only: `app.application.simulation.sim_time.
   sim_now_ms(session, clock.now())`, never from a process-monotonic counter (SPEC §39, D7);
3. load the `WorldState` through `world_state_loader` and read the actions appended since the last
   tick (`seq_no > last_folded_seq_no`);
4. `advance` → `apply_effects` → `advance_resources`;
5. persist **only what changed** — the world-truth row, the caller-belief row, the moved resources
   plus one `resource_state_changes` row per fired transition, and the engine's bookkeeping;
6. append the `DomainEvent`s and commit. Publishing happens after the commit, inside the Unit of
   Work (§20.8, §40.6).

A tick in which nothing fired, nothing was folded and no resource moved writes **nothing at all**,
not even `last_tick_ms`. That is safe because every draw the engine makes is indexed by *absolute*
simulated time (`world/rng.py`, `world/engine.py`): re-examining the same check tick re-draws the
same number, so leaving `last_tick_ms` behind costs one repeated evaluation and never a different
outcome. It is also what makes the runner cheap — a session where nothing is happening produces no
write traffic at all.

Three things this tick owes the DDS side, all of them inside the same transaction as the movement
that caused them:

* `assignment_resolved` — §10.7's `WORKING --finish_work--> RETURNING` fires either when the work
  time elapsed **or** when the assignment reached `RESOLVED`. The authority for that is the DDS
  `RoleStage`'s state (E9 analyst R1), which is on the aggregate this tick already holds, so the
  flag is read from it rather than from `dds_assignments`;
* `RESOURCE_STATUS_CHANGED.assignment_id` — the pure mover (`world/resource_movement.py`) cannot
  know which DDS leg a unit hangs on, because attachment is an application fact
  (`emergency_resources.assignment_id`). The tick enriches each movement event with it, and writes
  the same value plus the `session_events.id` of that event into the `resource_state_changes` row;
* `notifications` — a `CreateNotification` effect emits `NOTIFICATION_CREATED`, and §20.5's table
  is materialized from it. The row is written here, in the tick's own Unit of Work, so the log and
  the table commit together and `listNotifications` can never read one without the other (D5).

The DDS *stage* triggers `first_en_route`, `first_arrived`, `work_started` and `incident_resolved`
are **not** fired here: they run after this transaction commits, as the
`app.application.dds.stage_automation` hook of the `SimulationRunner`, which takes the same row
lock afresh. `resolution_condition_met` is evaluated here, though — see
`TickSession.resolution_condition_met` — because only this module legitimately holds the
`WorldState` the condition reads (D3).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple
from uuid import UUID

from app.application.ports.clock import Clock
from app.application.ports.notification_repository import StoredNotification
from app.application.ports.resource_repository import ResourceStateChange
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.world_engine_state_repository import WorldEngineState
from app.application.simulation.sim_time import sim_now_ms
from app.application.simulation.world_state_loader import LoadedWorldState, load_world_state
from app.domain.common.ids import AssignmentId, ResourceId, SessionId
from app.domain.dds.resources import EmergencyResource
from app.domain.enums import (
    DDSStageState,
    NotificationSeverity,
    ResourceStatus,
    RoleType,
    SessionState,
)
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion
from app.domain.session.session import SimulationSession
from app.domain.world.apply import apply_effects
from app.domain.world.conditions import ConditionContext, evaluate_condition
from app.domain.world.engine import WorldState, advance
from app.domain.world.eta import EtaModel, ScenarioDefinedEta
from app.domain.world.resource_movement import advance_resources
from app.domain.world.rng import rng_for

__all__ = ["TickResult", "TickSession"]

logger = logging.getLogger(__name__)


class TickResult(NamedTuple):
    """What one tick did, for the runner's logs and for tests."""

    ticked: bool
    now_ms: int = 0
    fired_world_event_ids: tuple[str, ...] = ()
    appended_events: int = 0
    wrote: bool = False


class TickSession:
    """Advance one session's world by one tick, in one transaction."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        eta_model: EtaModel | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        #: D7's local `EtaModel` port; `ScenarioDefinedEta` reads the scenario's five values.
        self._eta_model: EtaModel = eta_model if eta_model is not None else ScenarioDefinedEta()

    async def __call__(self, session_id: SessionId) -> TickResult:
        """Tick `session_id` once; a session that is not `ACTIVE` is a no-op."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None or session.state is not SessionState.ACTIVE:
                await uow.commit()
                return TickResult(ticked=False)

            now_ms = self._now_ms(session)
            loaded = await load_world_state(uow, session)
            # Simulated time never goes back (`advance` refuses it). A `time_scale` lowered
            # mid-session, or a wall clock nudged backwards, would otherwise raise instead of
            # simply standing still, so the tick clamps to the last tick it already made.
            now_ms = max(now_ms, loaded.state.last_tick_ms)

            result = _run(
                loaded,
                now_ms,
                session.session_seed,
                self._eta_model,
                assignment_resolved=_assignment_resolved(session),
            )
            if not result.changed:
                await uow.commit()
                return TickResult(ticked=True, now_ms=now_ms)

            attachments = await _attachments(uow, session_id, result.events)
            events = _with_assignment_ids(result.events, attachments)
            await self._persist(uow, session, loaded, result, now_ms)
            appended = await uow.events.append(session_id, events)
            await _record_state_changes(uow, appended, result.resources, attachments)
            await _materialise_notifications(uow, session, appended)
            await uow.commit()

        return TickResult(
            ticked=True,
            now_ms=now_ms,
            fired_world_event_ids=tuple(entry.world_event_id for entry in result.fired),
            appended_events=len(appended),
            wrote=True,
        )

    async def resolution_condition_met(self, session_id: SessionId) -> bool:
        """Evaluate the scenario's `expected_response.resolution_condition` (§10.8, §30.5).

        The verdict `guard_resolution_condition` reads, produced in the one place that may read
        the live `WorldState`: the condition language's leaves are `fact` (world truth and caller
        belief), `resource`, `stage`, `sim_time` and `action` (the folded `EventIndex`), and D3
        forbids the DDS slice from holding a path to the first of those. So
        `app.application.dds.stage_automation` is handed this **boolean** through a callable and
        learns nothing else about the world.

        A scenario with no `resolution_condition` answers `False`: rule R28 of §10.15 requires the
        field, so its absence is an invalid scenario, and an invalid scenario must not resolve
        itself. `evaluate_condition` is total and pure — it never raises — so there is no failure
        mode here beyond "the session vanished", which answers `False` as well.
        """
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None or session.state is not SessionState.ACTIVE:
                await uow.commit()
                return False
            document = await uow.scenarios.get_version_document(session.scenario_version_id)
            if document is None:  # pragma: no cover - the FK guarantees the row
                await uow.commit()
                return False
            condition = ScenarioVersion.model_validate(
                dict(document)
            ).expected_response.resolution_condition
            if condition is None:
                await uow.commit()
                return False
            loaded = await load_world_state(uow, session)
            await uow.commit()

        state = loaded.state
        return evaluate_condition(
            condition,
            ConditionContext(
                world_truth=state.world_truth,
                caller_belief=state.caller_belief,
                resources=state.resources,
                resource_keys=state.resource_keys,
                stage_states=state.stage_states,
                reached_states=state.reached_states,
                now_ms=max(self._now_ms(session), state.last_tick_ms),
                event_index=state.event_index,
            ),
        )

    # -- steps ---------------------------------------------------------------------------------

    def _now_ms(self, session: SimulationSession) -> int:
        """Simulated milliseconds since `SESSION_STARTED`, from persisted state only (§39, D7).

        `sim_now_ms` is the one source of that number (E17 R1); it also freezes the clock while
        the session sits in `ROLE_TRANSITION`, which this tick never observes because a session
        that is not `ACTIVE` is a no-op two lines into `__call__`.
        """
        return sim_now_ms(session, self._clock.now())

    async def _persist(
        self,
        uow: UnitOfWork,
        session: SimulationSession,
        loaded: LoadedWorldState,
        result: _TickOutcome,
        now_ms: int,
    ) -> None:
        """Write the rows this tick actually changed — and no others."""
        before = loaded.state
        if result.state.world_truth != before.world_truth:
            await uow.world_truth.save(result.state.world_truth)
        if result.state.caller_belief != before.caller_belief:
            await uow.caller_beliefs.save(result.state.caller_belief)

        for key, resource in result.resources.items():
            if before.resources.get(key) != resource:
                await uow.resources.save(session.id, resource)

        await uow.world_engine_states.save(
            WorldEngineState(
                incident_id=session.incident.incident_id,
                last_tick_ms=now_ms,
                last_folded_seq_no=loaded.last_seq_no,
                occurrences=dict(result.state.occurrences),
                last_fired_ms=dict(result.state.last_fired_ms),
                scheduled=result.state.scheduled,
                emotion_applications=dict(result.state.emotion_applications),
                reached_states=dict(result.state.reached_states),
            )
        )


class _TickOutcome(NamedTuple):
    """The pure result of one tick, before anything is written."""

    state: WorldState
    resources: Mapping[ResourceId, EmergencyResource]
    events: list[DomainEvent]
    fired: tuple[Any, ...]
    changed: bool


def _run(
    loaded: LoadedWorldState,
    now_ms: int,
    session_seed: str,
    eta_model: EtaModel,
    *,
    assignment_resolved: bool,
) -> _TickOutcome:
    """`advance` → `apply_effects` → `advance_resources`, all pure (§10.11, §10.7).

    `session_seed` is the session's own seed (D7 determinism rule 5), so two sessions of the same
    scenario with the same seed and the same actions produce the identical event stream.
    """
    advanced, _effects = advance(
        loaded.state, now_ms, loaded.pending_actions, rng_for(session_seed)
    )
    applied = apply_effects(advanced, advanced.fired, now_ms)
    for refusal in applied.skipped:
        logger.debug(
            "world event %s: resource transition %s on %s skipped (%s)",
            refusal.world_event_id,
            refusal.trigger,
            refusal.resource_id,
            refusal.reason,
        )
    resources, movement_events = advance_resources(
        applied.state.resources, now_ms, eta_model, assignment_resolved=assignment_resolved
    )
    events = [*applied.events, *movement_events]
    changed = bool(advanced.fired) or bool(loaded.pending_actions) or bool(movement_events)
    return _TickOutcome(
        state=applied.state.model_copy(update={"resources": resources}),
        resources=resources,
        events=events,
        fired=advanced.fired,
        changed=changed,
    )


def _assignment_resolved(session: SimulationSession) -> bool:
    """ "The DDS assignment reached `RESOLVED`" (§10.7), read from the stage that owns it.

    `role_stages.state` is the single authority for the DDS workflow state and every
    `dds_assignments` leg mirrors it (E9 analyst R1), so the aggregate this tick already holds
    answers the question without a second read. `CLOSED` counts too: an incident that was closed
    is at least as resolved as one that merely reached `RESOLVED`, and a unit still `WORKING`
    under a closed work item must go home.
    """
    return any(
        stage.role_type is RoleType.DDS
        and stage.state in (DDSStageState.RESOLVED, DDSStageState.CLOSED)
        for stage in session.stages
    )


async def _attachments(
    uow: UnitOfWork, session_id: SessionId, events: Sequence[DomainEvent]
) -> Mapping[ResourceId, AssignmentId | None]:
    """`resource_id -> the DDS leg it hangs on`, read only when a unit actually moved.

    Attachment is an application fact (`emergency_resources.assignment_id`, written by the DDS
    selection use case), so the pure mover cannot put it in the event it emits; the tick supplies
    it. A tick in which nothing moved does not read the board a second time.
    """
    if not any(event.event_type is EventType.RESOURCE_STATUS_CHANGED for event in events):
        return {}
    return {
        stored.resource.resource_id: stored.assignment_id
        for stored in await uow.resources.list_for_session(session_id)
    }


def _with_assignment_ids(
    events: Sequence[DomainEvent], attachments: Mapping[ResourceId, AssignmentId | None]
) -> list[DomainEvent]:
    """Put `assignment_id` into every `RESOURCE_STATUS_CHANGED` payload (§10.13).

    `uuid | null`: `null` for a unit nobody selected — a scenario unit coming back into its
    availability window on its own schedule, for instance.
    """
    enriched: list[DomainEvent] = []
    for event in events:
        if event.event_type is not EventType.RESOURCE_STATUS_CHANGED:
            enriched.append(event)
            continue
        key = ResourceId(UUID(str(event.payload["resource_id"])))
        assignment_id = attachments.get(key)
        enriched.append(
            event.model_copy(
                update={
                    "payload": {
                        **event.payload,
                        "assignment_id": (
                            None if assignment_id is None else UUID(str(assignment_id))
                        ),
                    }
                }
            )
        )
    return enriched


async def _record_state_changes(
    uow: UnitOfWork,
    appended: Sequence[SessionEvent],
    resources: Mapping[ResourceId, EmergencyResource],
    attachments: Mapping[ResourceId, AssignmentId | None],
) -> None:
    """One `resource_state_changes` row per `RESOURCE_STATUS_CHANGED` event (§20.5, SPEC §29).

    Written *after* the append rather than before it, because the row carries the
    `session_events.id` of the event it records — the §20.5 column that had nowhere to get its
    value from until the events and the rows shared one transaction.
    """
    for event in appended:
        if event.event_type is not EventType.RESOURCE_STATUS_CHANGED:
            continue
        key = ResourceId(UUID(str(event.payload["resource_id"])))
        resource = resources.get(key)
        if resource is None:  # pragma: no cover - the board always holds the mover
            continue
        previous = event.payload["previous_status"]
        await uow.resources.record_state_change(
            ResourceStateChange(
                resource=resource,
                previous_status=None if previous is None else ResourceStatus(previous),
                new_status=ResourceStatus(event.payload["new_status"]),
                trigger=str(event.payload["trigger"]),
                source_world_event_id=event.payload.get("source_world_event_id"),
                at_offset_ms=int(event.payload["at_offset_ms"]),
                assignment_id=attachments.get(key),
                session_event_id=event.id,
            )
        )


async def _materialise_notifications(
    uow: UnitOfWork, session: SimulationSession, appended: Sequence[SessionEvent]
) -> None:
    """Write the `notifications` rows of this tick's `NOTIFICATION_CREATED` events (§20.5).

    Same transaction as the events themselves (D5), and idempotent: the id is derived
    deterministically from the world event, and the adapter inserts "do nothing on conflict", so a
    re-examined check tick cannot produce a second row for one notification.
    """
    rows = [
        StoredNotification(
            notification_id=UUID(str(event.payload["notification_id"])),
            incident_id=session.incident.incident_id,
            audience_role=RoleType(str(event.payload["audience_role"])),
            severity=NotificationSeverity(str(event.payload["severity"])),
            title_ru=str(event.payload.get("title_ru", "")),
            body_ru=str(event.payload.get("body_ru", "")),
            source_world_event_id=event.payload.get("source_world_event_id"),
            created_at_offset_ms=int(event.payload["at_offset_ms"]),
        )
        for event in appended
        if event.event_type is EventType.NOTIFICATION_CREATED
    ]
    await uow.notifications.add_all(rows)
