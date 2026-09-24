"""Builders for the pure DDS application tests — no database, no HTTP.

One snapshot, its legs and a small resource board, built by hand so that every test states the
one fact it is about. The shapes mirror the demo scenario (`scenarios/examples/apartment-fire`):
a handoff addressed to `FIRE_RESCUE` and `AMBULANCE`, with a police unit on the board whose
service received no leg at all — which is the case `leg_for` exists to decide.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.application.ports.resource_repository import StoredResource
from app.domain.common.ids import (
    AssignmentId,
    CardId,
    CardRevisionId,
    IncidentId,
    ResourceId,
    RoleStageId,
    SnapshotId,
    UserId,
)
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.resources import (
    EmergencyResource,
    EtaProfile,
    ResourceAvailability,
    ResourceCapability,
)
from app.domain.enums import DDSStageState, ResourceStatus, ResourceType, ServiceId
from app.domain.layers.handoff import HandoffSnapshot

FIRE = ServiceId("FIRE_RESCUE")
AMBULANCE = ServiceId("AMBULANCE")
POLICE = ServiceId("POLICE")


@pytest.fixture
def role_stage_id() -> RoleStageId:
    return RoleStageId(uuid4())


@pytest.fixture
def snapshot() -> HandoffSnapshot:
    """The demo handoff: FIRE_RESCUE first, AMBULANCE second, house "72" (SPEC §3)."""
    return HandoffSnapshot(
        snapshot_id=SnapshotId(uuid4()),
        incident_id=IncidentId(uuid4()),
        card_id=CardId(uuid4()),
        card_revision_id=CardRevisionId(uuid4()),
        card_values={"address.house": "72", "recipients.services": ["FIRE_RESCUE", "AMBULANCE"]},
        recipient_services=(FIRE, AMBULANCE),
        created_by_user_id=UserId(uuid4()),
        created_at_offset_ms=120_000,
        content_sha256="0" * 64,
    )


def make_leg(
    snapshot: HandoffSnapshot,
    role_stage_id: RoleStageId,
    service_type: ServiceId,
    **overrides: object,
) -> DDSAssignment:
    """One `dds_assignments` leg of `snapshot`, in `RECEIVED` unless told otherwise."""
    fields: dict[str, object] = {
        "assignment_id": AssignmentId(uuid4()),
        "incident_id": snapshot.incident_id,
        "role_stage_id": role_stage_id,
        "snapshot_id": snapshot.snapshot_id,
        "service_type": service_type,
        "state": DDSStageState.RECEIVED,
        "received_at_offset_ms": 120_000,
    }
    fields.update(overrides)
    return DDSAssignment(**fields)  # type: ignore[arg-type]


@pytest.fixture
def legs(snapshot: HandoffSnapshot, role_stage_id: RoleStageId) -> list[DDSAssignment]:
    """The two legs of the demo handoff, in recipient order."""
    return [make_leg(snapshot, role_stage_id, FIRE), make_leg(snapshot, role_stage_id, AMBULANCE)]


def make_resource(
    callsign: str,
    service_type: ServiceId,
    *,
    status: ResourceStatus = ResourceStatus.AVAILABLE,
    available_from_ms: int = 0,
    available_until_ms: int | None = None,
    capabilities: frozenset[ResourceCapability] = frozenset(),
    status_changed_at_offset_ms: int = 0,
) -> EmergencyResource:
    """One board unit. The ETA profile is the demo's АЦ-1 shape unless a test needs otherwise."""
    return EmergencyResource(
        resource_id=ResourceId(uuid4()),
        service_type=service_type,
        resource_type=ResourceType.FIRE_ENGINE,
        callsign=callsign,
        name_ru=callsign,
        capabilities=capabilities,
        current_status=status,
        availability=ResourceAvailability(
            available_from_ms=available_from_ms, available_until_ms=available_until_ms
        ),
        eta=EtaProfile(
            turnout_delay_seconds=60,
            travel_time_seconds=240,
            setup_seconds=60,
            on_scene_work_seconds=900,
            return_time_seconds=300,
        ),
        home_station_ru="ПЧ-1",
        crew_size=6,
        status_changed_at_offset_ms=status_changed_at_offset_ms,
    )


def stored(
    resource: EmergencyResource, assignment_id: AssignmentId | None = None
) -> StoredResource:
    """`resource` as the repository returns it, optionally attached to a leg."""
    return StoredResource(
        scenario_resource_id=resource.callsign.lower(),
        resource=resource,
        assignment_id=assignment_id,
    )
