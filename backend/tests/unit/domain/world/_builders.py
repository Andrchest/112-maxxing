"""Deterministic builders shared by the world-engine unit tests and by INV 7.

Nothing here invents product data: the scenario is the committed demo document
(`scenarios/examples/apartment-fire/v1.yaml`), instantiated through the real
`instantiate_world_truth` / `instantiate_caller_belief`, and the resource board is built from the
scenario's own `available_resources`. Ids are `uuid5`-derived so a run never depends on `uuid4`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from app.domain.common.ids import IncidentId, ResourceId, ScenarioId, ScenarioVersionId
from app.domain.dds.resources import EmergencyResource
from app.domain.enums import ResourceStatus
from app.domain.layers.copies import instantiate_caller_belief, instantiate_world_truth
from app.domain.scenario.version import ScenarioVersion
from app.domain.world.engine import WorldState

from tests.fixtures.scenarios import demo_document

_NAMESPACE = uuid.UUID("00000000-0000-4000-8000-000000000000")


def det_uuid(name: str) -> uuid.UUID:
    """A stable UUID for `name`, so no test result depends on `uuid4`."""
    return uuid.uuid5(_NAMESPACE, name)


INCIDENT_ID = IncidentId(det_uuid("incident"))


def demo_scenario() -> ScenarioVersion:
    """The committed demo scenario as a `ScenarioVersion`."""
    document: dict[str, Any] = demo_document()
    document["id"] = str(ScenarioVersionId(det_uuid("scenario-version")))
    document["scenario_id"] = str(ScenarioId(det_uuid("scenario")))
    return ScenarioVersion(**document)


def resource_board(
    version: ScenarioVersion, *, statuses: Mapping[str, ResourceStatus] | None = None
) -> tuple[dict[ResourceId, EmergencyResource], dict[str, ResourceId]]:
    """The scenario's `available_resources` as a runtime board plus its scenario-id key map."""
    board: dict[ResourceId, EmergencyResource] = {}
    keys: dict[str, ResourceId] = {}
    overrides = statuses or {}
    for spec in version.available_resources:
        key = ResourceId(det_uuid(f"resource:{spec.resource_id}"))
        keys[spec.resource_id] = key
        board[key] = EmergencyResource(
            resource_id=key,
            service_type=spec.service_type,
            resource_type=spec.resource_type,
            callsign=spec.callsign,
            name_ru=spec.name_ru,
            capabilities=frozenset(spec.capabilities),
            current_status=overrides.get(spec.resource_id, spec.availability.initial_status),
            availability=spec.availability,
            eta=spec.eta,
            home_station_ru=spec.home_station_ru,
            crew_size=spec.crew_size,
            status_changed_at_offset_ms=0,
        )
    return board, keys


def demo_world_state(
    *, statuses: Mapping[str, ResourceStatus] | None = None, with_events: bool = True
) -> WorldState:
    """A `WorldState` instantiated from the demo scenario (world events included by default)."""
    version = demo_scenario()
    board, keys = resource_board(version, statuses=statuses)
    return WorldState(
        incident_id=INCIDENT_ID,
        world_truth=instantiate_world_truth(version, INCIDENT_ID),
        caller_belief=instantiate_caller_belief(version, INCIDENT_ID),
        resources=board,
        resource_keys=keys,
        definitions=version.world_events if with_events else (),
        emotion_rules=version.caller_profile.emotion_rules,
    )
