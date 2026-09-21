"""SPEC §3 / §10, HLD §10.3: the four copy functions deep-copy and never alias a layer.

The load-bearing assertions:

* mutating anything inside an instantiated `WorldTruth`/`CallerBelief` changes neither the other
  result nor the `ScenarioVersion` it came from;
* the caller's belief about `incident.fire_source` is `None`, and the string `"KITCHEN"` does not
  occur anywhere in a serialised `CallerBelief` (SPEC §5: the caller LLM must never receive it);
* a `HandoffSnapshot` keeps the card's value even when it contradicts world truth ("72" vs "27"),
  and later card edits cannot reach it;
* `snapshot_to_assignment` and `snapshot_to_assignments` have no parameter through which a
  `WorldTruth` could arrive;
* `snapshot_to_assignments` fans one snapshot out into one leg per recipient service, in order,
  with distinct ids and the same snapshot behind every one of them (E9).
"""

from __future__ import annotations

import inspect
from typing import get_type_hints
from uuid import UUID, uuid4

import pytest
from app.domain.caller.emotion import EmotionState
from app.domain.common.actors import ActorRef
from app.domain.common.ids import (
    CardId,
    CardRevisionId,
    IncidentId,
    RoleStageId,
    UserId,
)
from app.domain.enums import ActorType, DDSStageState, KnowledgeState, ServiceType
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.copies import (
    freeze_card_to_snapshot,
    instantiate_caller_belief,
    instantiate_world_truth,
    snapshot_to_assignment,
    snapshot_to_assignments,
)
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import OperatorCard, set_field
from app.domain.layers.world_truth import WorldTruth
from app.domain.scenario.version import ScenarioVersion

from tests.fixtures.scenarios import demo_document

TRAINEE = ActorRef(actor_type=ActorType.TRAINEE, actor_id=UserId(uuid4()))


@pytest.fixture
def version() -> ScenarioVersion:
    return ScenarioVersion.model_validate(demo_document())


@pytest.fixture
def incident_id() -> IncidentId:
    return IncidentId(uuid4())


def _card_with_house_72(incident_id: IncidentId) -> OperatorCard:
    card = OperatorCard(card_id=CardId(uuid4()), incident_id=incident_id, values={})
    card, _revision, _event = set_field(
        card, "address.house", "72", TRAINEE, 1_000, CardRevisionId(uuid4())
    )
    card, _revision, _event = set_field(
        card, "address.locality", "Смоленск", TRAINEE, 1_100, CardRevisionId(uuid4())
    )
    return card


# ---------------------------------------------------------------------------------------------
# instantiate_world_truth / instantiate_caller_belief
# ---------------------------------------------------------------------------------------------


def test_instantiate_world_truth_copies_the_scenario_values(
    version: ScenarioVersion, incident_id: IncidentId
) -> None:
    world = instantiate_world_truth(version, incident_id)

    assert world.incident_id == incident_id
    assert world.revision == 0
    assert world.facts["address.house"] == "27"
    assert world.facts["incident.fire_source"] == "KITCHEN"
    assert set(world.value_types) == set(version.world_truth.facts)


def test_instantiate_caller_belief_copies_the_caller_values(
    version: ScenarioVersion, incident_id: IncidentId
) -> None:
    belief = instantiate_caller_belief(version, incident_id)

    assert belief.incident_id == incident_id
    assert belief.revision == 0
    assert belief.facts["address.floor"] == 5
    assert belief.knowledge["address.floor"] is KnowledgeState.INCORRECT_BELIEF
    assert belief.certainty["people.victim_01.age"] == pytest.approx(0.4)
    assert belief.emotion == EmotionState(
        emotion=version.caller_profile.baseline_emotion,
        stress_level=version.caller_profile.baseline_stress_level,
    )
    assert belief.revealed_fact_ids == frozenset()


def test_caller_belief_never_carries_the_world_only_fire_source(
    version: ScenarioVersion, incident_id: IncidentId
) -> None:
    belief = instantiate_caller_belief(version, incident_id)

    assert belief.facts["incident.fire_source"] is None
    assert belief.knowledge["incident.fire_source"] is KnowledgeState.UNKNOWN
    assert "KITCHEN" not in belief.model_dump_json()


def test_mutating_one_instantiated_layer_touches_nothing_else(
    version: ScenarioVersion, incident_id: IncidentId
) -> None:
    world = instantiate_world_truth(version, incident_id)
    belief = instantiate_caller_belief(version, incident_id)

    world.facts["address.house"] = "MUTATED"
    world.value_types.pop("address.house")
    belief.facts["address.floor"] = 99
    belief.knowledge["address.floor"] = KnowledgeState.KNOWN
    belief.certainty["address.floor"] = 0.1

    assert version.world_truth.facts["address.house"].world_value == "27"
    assert version.caller_knowledge.facts["address.floor"].caller_value == 5
    assert version.caller_knowledge.facts["address.floor"].knowledge is (
        KnowledgeState.INCORRECT_BELIEF
    )

    fresh_world = instantiate_world_truth(version, incident_id)
    fresh_belief = instantiate_caller_belief(version, incident_id)
    assert fresh_world.facts["address.house"] == "27"
    assert "address.house" in fresh_world.value_types
    assert fresh_belief.facts["address.floor"] == 5


def test_a_list_valued_fact_is_not_shared_between_results(incident_id: IncidentId) -> None:
    document = demo_document()
    document["world_truth"]["facts"]["incident.tags"] = {
        "world_value": ["fire", "smoke"],
        "value_type": "STRING_LIST",
        "label_ru": "Метки",
    }
    document["caller_knowledge"]["facts"]["incident.tags"] = {
        "caller_value": ["fire", "smoke"],
        "knowledge": "KNOWN",
    }
    document["disclosure_rules"]["facts"]["incident.tags"] = {"policy": "ON_ASK"}
    version = ScenarioVersion.model_validate(document)

    world = instantiate_world_truth(version, incident_id)
    belief = instantiate_caller_belief(version, incident_id)

    world_tags = world.facts["incident.tags"]
    belief_tags = belief.facts["incident.tags"]
    assert isinstance(world_tags, list) and isinstance(belief_tags, list)
    world_tags.append("mutated")

    assert belief.facts["incident.tags"] == ["fire", "smoke"]
    assert version.world_truth.facts["incident.tags"].world_value == ["fire", "smoke"]


# ---------------------------------------------------------------------------------------------
# freeze_card_to_snapshot
# ---------------------------------------------------------------------------------------------


def test_snapshot_holds_the_card_value_even_against_world_truth(
    version: ScenarioVersion, incident_id: IncidentId
) -> None:
    world = instantiate_world_truth(version, incident_id)
    card = _card_with_house_72(incident_id)

    snapshot = freeze_card_to_snapshot(
        card,
        CardRevisionId(uuid4()),
        (ServiceType.FIRE_RESCUE, ServiceType.AMBULANCE),
        UserId(uuid4()),
        60_000,
    )

    assert world.facts["address.house"] == "27"
    assert snapshot.card_values["address.house"] == "72"
    assert snapshot.incident_id == incident_id
    assert snapshot.card_id == card.card_id
    assert snapshot.content_sha256


def test_later_card_edits_do_not_reach_the_snapshot(incident_id: IncidentId) -> None:
    card = _card_with_house_72(incident_id)
    snapshot = freeze_card_to_snapshot(
        card, CardRevisionId(uuid4()), (ServiceType.FIRE_RESCUE,), UserId(uuid4()), 60_000
    )

    changed_card, revision, _event = set_field(
        card, "address.house", "27", TRAINEE, 70_000, CardRevisionId(uuid4())
    )

    assert revision is not None
    assert changed_card.values["address.house"] == "27"
    assert snapshot.card_values["address.house"] == "72"


def test_snapshot_shares_no_mutable_object_with_the_card(incident_id: IncidentId) -> None:
    card = _card_with_house_72(incident_id)
    snapshot = freeze_card_to_snapshot(
        card, CardRevisionId(uuid4()), (ServiceType.FIRE_RESCUE,), UserId(uuid4()), 60_000
    )

    card.values["address.house"] = "99"

    assert snapshot.card_values["address.house"] == "72"
    assert snapshot.card_values is not card.values


# ---------------------------------------------------------------------------------------------
# snapshot_to_assignment
# ---------------------------------------------------------------------------------------------


def _snapshot(incident_id: IncidentId) -> HandoffSnapshot:
    return freeze_card_to_snapshot(
        _card_with_house_72(incident_id),
        CardRevisionId(uuid4()),
        (ServiceType.FIRE_RESCUE, ServiceType.AMBULANCE),
        UserId(uuid4()),
        60_000,
    )


def test_assignment_reflects_the_snapshot_and_nothing_else(incident_id: IncidentId) -> None:
    snapshot = _snapshot(incident_id)

    assignment = snapshot_to_assignment(snapshot, RoleStageId(uuid4()), 61_000)

    assert assignment.snapshot_id == snapshot.snapshot_id
    assert assignment.incident_id == snapshot.incident_id
    assert assignment.service_type == snapshot.recipient_services[0]
    assert assignment.received_at_offset_ms == 61_000
    # What the DDS trainee reads is the snapshot the assignment points at: "72", never "27".
    assert snapshot.card_values["address.house"] == "72"


def test_snapshot_to_assignment_accepts_no_world_truth() -> None:
    signature = inspect.signature(snapshot_to_assignment)
    hints = get_type_hints(snapshot_to_assignment)

    assert list(signature.parameters) == ["snapshot", "role_stage_id", "at_offset_ms"]
    for name in signature.parameters:
        assert hints[name] not in (WorldTruth, CallerBelief)
    assert not any(
        "WorldTruth" in str(hints[name]) or "CallerBelief" in str(hints[name])
        for name in signature.parameters
    )


def test_derived_ids_are_deterministic(incident_id: IncidentId) -> None:
    card = _card_with_house_72(incident_id)
    revision_id = CardRevisionId(uuid4())
    user_id = UserId(uuid4())
    role_stage_id = RoleStageId(uuid4())

    first = freeze_card_to_snapshot(card, revision_id, (ServiceType.FIRE_RESCUE,), user_id, 60_000)
    second = freeze_card_to_snapshot(card, revision_id, (ServiceType.FIRE_RESCUE,), user_id, 60_000)

    assert isinstance(first.snapshot_id, UUID)
    assert first.snapshot_id == second.snapshot_id
    assert first.content_sha256 == second.content_sha256
    assert (
        snapshot_to_assignment(first, role_stage_id, 61_000).assignment_id
        == snapshot_to_assignment(second, role_stage_id, 61_000).assignment_id
    )


# ---------------------------------------------------------------------------------------------
# snapshot_to_assignments (additive, E9)
# ---------------------------------------------------------------------------------------------


def test_one_leg_per_recipient_service_in_order(incident_id: IncidentId) -> None:
    """§10.7's "one assignment per recipient service", as the fan-out the use case persists."""
    snapshot = _snapshot(incident_id)
    role_stage_id = RoleStageId(uuid4())

    legs = snapshot_to_assignments(snapshot, role_stage_id, 61_000)

    assert [leg.service_type for leg in legs] == list(snapshot.recipient_services)
    assert {leg.snapshot_id for leg in legs} == {snapshot.snapshot_id}
    assert {leg.role_stage_id for leg in legs} == {role_stage_id}
    assert {leg.incident_id for leg in legs} == {snapshot.incident_id}
    assert all(leg.received_at_offset_ms == 61_000 for leg in legs)
    assert all(leg.state is DDSStageState.RECEIVED for leg in legs)


def test_every_leg_has_its_own_id(incident_id: IncidentId) -> None:
    """The service type is inside the `uuid5` name; without it the N legs would collide."""
    snapshot = _snapshot(incident_id)
    legs = snapshot_to_assignments(snapshot, RoleStageId(uuid4()), 61_000)

    assert len(legs) == 2
    assert len({leg.assignment_id for leg in legs}) == 2


def test_the_fan_out_is_deterministic(incident_id: IncidentId) -> None:
    """D7's replay determinism: the same inputs always derive the same leg ids."""
    snapshot = _snapshot(incident_id)
    role_stage_id = RoleStageId(uuid4())

    first = snapshot_to_assignments(snapshot, role_stage_id, 61_000)
    second = snapshot_to_assignments(snapshot, role_stage_id, 61_000)

    assert [leg.assignment_id for leg in first] == [leg.assignment_id for leg in second]


def test_the_fan_out_carries_the_card_value_not_the_world_value(incident_id: IncidentId) -> None:
    """SPEC §3: every leg points at the snapshot that says "72", and at nothing else."""
    snapshot = _snapshot(incident_id)
    legs = snapshot_to_assignments(snapshot, RoleStageId(uuid4()), 61_000)

    assert all(leg.snapshot_id == snapshot.snapshot_id for leg in legs)
    assert snapshot.card_values["address.house"] == "72"


def test_a_snapshot_with_no_recipient_service_cannot_be_fanned_out(
    incident_id: IncidentId,
) -> None:
    """The `create_handoff` guard refuses first; the domain refuses too rather than making none."""
    empty = freeze_card_to_snapshot(
        _card_with_house_72(incident_id), CardRevisionId(uuid4()), (), UserId(uuid4()), 60_000
    )
    with pytest.raises(ValueError, match="recipient_services"):
        snapshot_to_assignments(empty, RoleStageId(uuid4()), 61_000)


def test_snapshot_to_assignments_accepts_no_world_truth() -> None:
    """The fan-out's parameter list is the singular function's: no layer can arrive through it."""
    signature = inspect.signature(snapshot_to_assignments)
    hints = get_type_hints(snapshot_to_assignments)

    assert list(signature.parameters) == ["snapshot", "role_stage_id", "at_offset_ms"]
    assert not any(
        "WorldTruth" in str(hints[name]) or "CallerBelief" in str(hints[name])
        for name in signature.parameters
    )
