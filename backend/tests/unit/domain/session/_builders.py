"""Deterministic builders shared by the session unit tests.

Nothing here invents product data: the `ScenarioVersion` is the committed demo scenario document
(`scenarios/examples/apartment-fire/v1.yaml`) with ids added and, where a test needs a variant,
exactly one key mutated — the same discipline `tests/unit/domain/scenario/` uses.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from app.domain.common.actors import ActorRef
from app.domain.common.ids import (
    CardId,
    IncidentId,
    ResourceId,
    RoleStageId,
    ScenarioId,
    ScenarioVersionId,
    SessionId,
    UserId,
)
from app.domain.dds.resources import (
    EmergencyResource,
    EtaProfile,
    ResourceAvailability,
    ResourceCapability,
)
from app.domain.enums import (
    ActorType,
    ResourceStatus,
    ResourceType,
    RoleType,
    ServiceId,
)
from app.domain.layers.operator_card import OperatorCard
from app.domain.scenario.version import ScenarioVersion
from app.domain.session.session import (
    Incident,
    RoleStage,
    SessionParticipant,
    SimulationSession,
    StageState,
)

from tests.fixtures.scenarios import demo_document

_NAMESPACE = uuid.UUID("00000000-0000-4000-8000-000000000000")


def det_uuid(name: str) -> uuid.UUID:
    """A stable UUID for `name`, so a test's expected ids never depend on `uuid4`."""
    return uuid.uuid5(_NAMESPACE, name)


def scenario_version(
    *,
    role_chain: Sequence[RoleType] | None = None,
    with_prefab_handoff: bool = True,
) -> ScenarioVersion:
    """The demo scenario as a `ScenarioVersion`, optionally with a different `role_chain` or with
    `expected_response.prefab_handoff` removed."""
    document: dict[str, Any] = demo_document()
    document["id"] = str(det_uuid("scenario-version"))
    document["scenario_id"] = str(det_uuid("scenario"))
    if role_chain is not None:
        document["role_chain"] = [role.value for role in role_chain]
    if not with_prefab_handoff:
        document["expected_response"].pop("prefab_handoff", None)
    return ScenarioVersion(**document)


def user(name: str) -> UserId:
    return UserId(det_uuid(f"user:{name}"))


def actor(actor_type: ActorType, user_name: str | None = None) -> ActorRef:
    return ActorRef(actor_type=actor_type, actor_id=None if user_name is None else user(user_name))


SYSTEM = actor(ActorType.SYSTEM, "system")
INSTRUCTOR = actor(ActorType.INSTRUCTOR, "instructor")
SIMULATION = actor(ActorType.SIMULATION, "simulation")


def stage_ids(count: int) -> tuple[RoleStageId, ...]:
    return tuple(RoleStageId(det_uuid(f"stage:{index}")) for index in range(count))


SESSION_ID = SessionId(det_uuid("session"))
INCIDENT_ID = IncidentId(det_uuid("incident"))


def build_stage(
    *,
    order_index: int,
    role_type: RoleType,
    state: StageState,
    participant_user_id: UserId | None = None,
    started_at_offset_ms: int | None = None,
    completed_at_offset_ms: int | None = None,
) -> RoleStage:
    return RoleStage(
        role_stage_id=RoleStageId(det_uuid(f"stage:{order_index}")),
        session_id=SESSION_ID,
        incident_id=INCIDENT_ID,
        role_type=role_type,
        order_index=order_index,
        state=state,
        participant_user_id=participant_user_id,
        started_at_offset_ms=started_at_offset_ms,
        completed_at_offset_ms=completed_at_offset_ms,
    )


def build_session(
    *,
    session_mode: Any,
    state: Any,
    stages: Sequence[RoleStage],
    participants: Sequence[SessionParticipant] = (),
) -> SimulationSession:
    """A `SimulationSession` assembled directly, for tests that need a state the factory cannot
    produce (the factory only ever returns `CREATED`)."""
    return SimulationSession(
        id=SESSION_ID,
        scenario_version_id=ScenarioVersionId(det_uuid("scenario-version")),
        session_mode=session_mode,
        state=state,
        session_seed="apartment-fire-v1",
        created_by_user_id=user("instructor"),
        incident=Incident(
            incident_id=INCIDENT_ID,
            session_id=SESSION_ID,
            scenario_version_id=ScenarioVersionId(det_uuid("scenario-version")),
        ),
        stages=tuple(stages),
        participants=tuple(participants),
    )


def card(services: Sequence[str] | None) -> OperatorCard:
    values: dict[str, Any] = {}
    if services is not None:
        values["recipients.services"] = list(services)
    return OperatorCard(card_id=CardId(det_uuid("card")), incident_id=INCIDENT_ID, values=values)


def resources(*statuses: ResourceStatus) -> Mapping[str, EmergencyResource]:
    """A resource-board projection: one `EmergencyResource` per status, keyed by its id string."""
    board: dict[str, EmergencyResource] = {}
    for index, status in enumerate(statuses):
        resource_id = ResourceId(det_uuid(f"resource:{index}"))
        board[str(resource_id)] = EmergencyResource(
            resource_id=resource_id,
            service_type=ServiceId("FIRE_RESCUE"),
            resource_type=ResourceType.FIRE_ENGINE,
            callsign=f"АЦ-{index + 1}",
            name_ru="Автоцистерна",
            capabilities=frozenset({ResourceCapability.FIRE_SUPPRESSION}),
            current_status=status,
            availability=ResourceAvailability(),
            eta=EtaProfile(
                turnout_delay_seconds=60,
                travel_time_seconds=300,
                setup_seconds=60,
                on_scene_work_seconds=1200,
                return_time_seconds=300,
            ),
            home_station_ru="ПЧ-1",
            crew_size=4,
        )
    return board


def scenario_ids() -> tuple[ScenarioId, str]:
    return ScenarioId(det_uuid("scenario")), "apartment-fire"
