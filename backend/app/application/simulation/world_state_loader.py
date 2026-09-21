"""Build a `WorldState` from persisted state — and nothing else (D3, D7, HLD §10.11).

This is the **only** application module that holds both the world-truth and the caller-belief
repository at once, which is the whole point of its existence: D3 says the four information layers
are four storage locations reachable through four separate ports, and the world event engine is the
one component that legitimately needs two of them. Confining that to a single module makes the
exception structural — `backend/tests/unit/application/simulation/test_world_state_visibility.py`
asserts by AST scan that the only module under `app/application` importing this one is
`tick_session`, so no DDS- or operator-facing use case can reach `WorldTruth` through it.

It builds a `WorldState` and returns it. It does not tick, persist, append or publish anything.

Three things the pure engine needs are *not* columns of any layer table and are assembled here:

* `definitions` and `emotion_rules` come from the scenario version's stored document (§30.1), which
  is re-parsed by the one parser (`app.domain.scenario`);
* `resource_keys` is the `scenario_resource_id → ResourceId` map of §20.5, which the effects'
  scenario-local resource ids (`"ac2"`) are resolved through;
* `event_index` is **re-folded from `session_events`** rather than stored. It is a pure fold of the
  session's own action events (determinism rule 1), so re-deriving it keeps the log the single
  source of what happened (D5) and makes a restart bit-identical to an uninterrupted run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NamedTuple

from app.application.ports.unit_of_work import UnitOfWork
from app.application.ports.world_engine_state_repository import WorldEngineState
from app.application.simulation.sim_time import sim_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import ResourceId
from app.domain.common.values import FactValue
from app.domain.dds.resources import EmergencyResource
from app.domain.enums import RoleType
from app.domain.events.session_event import SessionEvent
from app.domain.scenario.version import ScenarioVersion
from app.domain.session.session import SimulationSession
from app.domain.world.conditions import EventIndex
from app.domain.world.engine import PendingAction, WorldState

__all__ = ["LoadedWorldState", "WorldStateNotInstantiatedError", "load_world_state"]


class WorldStateNotInstantiatedError(DomainError):
    """A layer row session creation is supposed to have written is missing."""

    code = "CONFLICT"


class LoadedWorldState(NamedTuple):
    """Everything one tick needs, loaded from persisted state.

    `pending_actions` are the session's events with `seq_no > engine_state.last_folded_seq_no`,
    already converted to simulated time; `last_seq_no` is the highest `seq_no` seen, which becomes
    the new `last_folded_seq_no` when the tick writes.
    """

    state: WorldState
    engine_state: WorldEngineState
    scenario_resource_ids: Mapping[ResourceId, str]
    pending_actions: tuple[PendingAction, ...]
    last_seq_no: int


async def load_world_state(uow: UnitOfWork, session: SimulationSession) -> LoadedWorldState:
    """Assemble the engine's `WorldState` for `session` from PostgreSQL (§10.11, D3, D7)."""
    incident_id = session.incident.incident_id
    version = await _scenario_version(uow, session)

    world_truth = await uow.world_truth.get(incident_id)
    if world_truth is None:
        raise WorldStateNotInstantiatedError(
            f"incident {incident_id} has no incident_world_states row; session creation writes it"
        )
    caller_belief = await uow.caller_beliefs.get(incident_id)
    if caller_belief is None:
        raise WorldStateNotInstantiatedError(
            f"incident {incident_id} has no incident_caller_beliefs row; session creation writes it"
        )

    stored_resources = await uow.resources.list_for_session(session.id)
    resources: dict[ResourceId, EmergencyResource] = {}
    resource_keys: dict[str, ResourceId] = {}
    scenario_resource_ids: dict[ResourceId, str] = {}
    for stored in stored_resources:
        key = stored.resource.resource_id
        resources[key] = stored.resource
        resource_keys[stored.scenario_resource_id] = key
        scenario_resource_ids[key] = stored.scenario_resource_id

    engine_state = await uow.world_engine_states.get(incident_id)
    if engine_state is None:
        raise WorldStateNotInstantiatedError(
            f"incident {incident_id} has no world_engine_states row; session creation writes it"
        )

    events = await uow.events.read(session.id)
    folded = [event for event in events if event.seq_no <= engine_state.last_folded_seq_no]
    pending = [event for event in events if event.seq_no > engine_state.last_folded_seq_no]
    last_seq_no = max((event.seq_no for event in events), default=0)

    stage_states = _stage_states(session)
    return LoadedWorldState(
        state=WorldState(
            incident_id=incident_id,
            world_truth=world_truth,
            caller_belief=caller_belief,
            resources=resources,
            resource_keys=resource_keys,
            stage_states=stage_states,
            reached_states=_reached_states(engine_state, stage_states),
            last_tick_ms=engine_state.last_tick_ms,
            occurrences=dict(engine_state.occurrences),
            last_fired_ms=dict(engine_state.last_fired_ms),
            scheduled=engine_state.scheduled,
            event_index=EventIndex.fold(_as_actions(folded, session)),
            emotion_applications=dict(engine_state.emotion_applications),
            definitions=version.world_events,
            emotion_rules=version.caller_profile.emotion_rules,
        ),
        engine_state=engine_state,
        scenario_resource_ids=scenario_resource_ids,
        pending_actions=tuple(_as_actions(pending, session)),
        last_seq_no=last_seq_no,
    )


async def _scenario_version(uow: UnitOfWork, session: SimulationSession) -> ScenarioVersion:
    """The session's scenario document, through the one parser (`app.domain.scenario`)."""
    document = await uow.scenarios.get_version_document(session.scenario_version_id)
    if document is None:
        raise WorldStateNotInstantiatedError(
            f"session {session.id} references scenario version {session.scenario_version_id}, "
            "which has no stored content"
        )
    return ScenarioVersion.model_validate(dict(document))


def _as_actions(events: Sequence[SessionEvent], session: SimulationSession) -> list[PendingAction]:
    """Turn persisted events into `PendingAction`s stamped in **simulated** time.

    `monotonic_offset_ms` is wall-clock based (SPEC §39), so it goes through the same `sim_ms` the
    tick's own `now_ms` does. TODO(E17): `paused_total_ms` is the session's *current* total, and a
    per-event attribution needs the pause intervals a pause/resume use case will record.
    """
    return [
        PendingAction(
            event_type=event.event_type,
            at_offset_ms=sim_ms(
                event.monotonic_offset_ms, session.paused_total_ms, session.time_scale
            ),
            payload=_fact_payload(event.payload),
            actor=ActorRef(actor_type=event.actor_type, actor_id=event.actor_id),
        )
        for event in events
    ]


def _fact_payload(payload: Mapping[str, object]) -> dict[str, FactValue]:
    """The `FactValue`-shaped subset of a persisted payload (§10.11 `payload_match`).

    `session_events.payload` is free-form jsonb and several event types carry nested structures
    (`WORLD_TRUTH_MUTATED.changes`, for instance), while a `payload_match` and an `action`
    condition's `payload_equals` are `Mapping[str, FactValue]` — scalars and string lists. Keeping
    only the entries a match could ever compare against is therefore lossless for the engine and
    keeps `PendingAction` inside its declared type.
    """
    kept: dict[str, FactValue] = {}
    for key, value in payload.items():
        if value is None or isinstance(value, str | int | float | bool):
            kept[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            kept[key] = list(value)
    return kept


def _stage_states(session: SimulationSession) -> dict[RoleType, str]:
    """`role_type → current stage state`, the shape `evaluate_condition` reads (§10.11)."""
    return {stage.role_type: stage.state.value for stage in session.stages}


def _reached_states(
    engine_state: WorldEngineState, stage_states: Mapping[RoleType, str]
) -> dict[RoleType, frozenset[str]]:
    """The stored reached set, widened by whatever each stage is in right now (`REACHED`)."""
    reached = {role: set(states) for role, states in engine_state.reached_states.items()}
    for role, state in stage_states.items():
        reached.setdefault(role, set()).add(state)
    return {role: frozenset(states) for role, states in reached.items()}
