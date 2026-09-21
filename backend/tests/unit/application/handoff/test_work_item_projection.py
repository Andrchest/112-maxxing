"""The `DdsWorkItem` projection: one work item, N legs (E9 analyst R3; §10.7, SPEC §10, §11).

Pure tests over `app.application.handoff.work_item` — no database, no HTTP. What they pin:

* identity comes from the **primary** leg (`recipient_services[0]`'s), but every *quantity* is
  taken over all the legs, so the arbitrary choice of primary leg is inert: the resource-id lists
  are unions and `dispatched_at_offset_ms` is the earliest of the legs that have one;
* `missing_field_paths` names the `required_for_handoff` card fields the snapshot left empty and
  fills none of them — SPEC §10's "if the 112 operator omitted a critical fact, the omission
  propagates";
* the projection's inputs are a snapshot and its legs, and nothing else can enter (D3): the
  structural half of that is `test_inv_03_dds_never_reads_world_truth.py`, and this file is the
  behavioural half at the unit level — a world value of "27" is nowhere in the result because
  nothing ever handed one in.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.application.handoff.work_item import (
    REQUIRED_FOR_HANDOFF,
    missing_field_paths,
    primary_leg,
    work_item_view,
)
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
from app.domain.enums import ClosureReason, DDSStageState, ServiceType
from app.domain.layers.handoff import HandoffSnapshot

FIRE = ServiceType.FIRE_RESCUE
AMBULANCE = ServiceType.AMBULANCE

#: The card the demo operator types: the caller's "72" where world truth says "27", and no floor.
CARD_VALUES: dict[str, object] = {
    "incident.type": "FIRE",
    "address.locality": "Смоленск",
    "address.street": "улица Николаева",
    "address.house": "72",
    "recipients.services": ["FIRE_RESCUE", "AMBULANCE"],
}


@pytest.fixture
def role_stage_id() -> RoleStageId:
    return RoleStageId(uuid4())


@pytest.fixture
def snapshot() -> HandoffSnapshot:
    return HandoffSnapshot(
        snapshot_id=SnapshotId(uuid4()),
        incident_id=IncidentId(uuid4()),
        card_id=CardId(uuid4()),
        card_revision_id=CardRevisionId(uuid4()),
        card_values=dict(CARD_VALUES),
        recipient_services=(FIRE, AMBULANCE),
        created_by_user_id=UserId(uuid4()),
        created_at_offset_ms=120_000,
        content_sha256="0" * 64,
    )


def _leg(
    snapshot: HandoffSnapshot,
    role_stage_id: RoleStageId,
    service_type: ServiceType,
    **overrides: object,
) -> DDSAssignment:
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


# ---------------------------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------------------------


def test_identity_comes_from_the_first_recipient_services_leg(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    """`assignment_id` / `service_type` are the primary leg's — the only two fields that are."""
    ambulance = _leg(snapshot, role_stage_id, AMBULANCE)
    fire = _leg(snapshot, role_stage_id, FIRE)

    # Deliberately given out of order: the projection reads `recipient_services`, not the list.
    view = work_item_view(snapshot, [ambulance, fire])

    assert view.service_type is FIRE
    assert view.assignment_id == UUID(str(fire.assignment_id))
    assert primary_leg([ambulance, fire], snapshot) is fire


def test_the_snapshot_supplies_every_frozen_field(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    """`card_values` is the snapshot's, verbatim — "72", never "27" (SPEC §3)."""
    view = work_item_view(snapshot, [_leg(snapshot, role_stage_id, FIRE)])

    assert view.card_values == CARD_VALUES
    assert view.card_values["address.house"] == "72"
    assert view.recipient_services == (FIRE, AMBULANCE)
    assert view.handoff_content_sha256 == snapshot.content_sha256
    assert view.snapshot_id == UUID(str(snapshot.snapshot_id))
    assert "27" not in str(view.model_dump())


def test_a_work_item_needs_at_least_one_leg(snapshot: HandoffSnapshot) -> None:
    """A handoff with no leg is not a work item; the caller checks before it projects."""
    with pytest.raises(ValueError, match="no DDS assignment leg"):
        work_item_view(snapshot, [])


# ---------------------------------------------------------------------------------------------
# Quantities over all legs
# ---------------------------------------------------------------------------------------------


def test_resource_id_lists_are_the_union_over_the_legs(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    """An ambulance selected under the AMBULANCE leg is visible on the one work item (R3)."""
    engine = ResourceId(uuid4())
    ambulance_unit = ResourceId(uuid4())
    fire = _leg(snapshot, role_stage_id, FIRE, selected_resource_ids=(engine,))
    ambulance = _leg(snapshot, role_stage_id, AMBULANCE, selected_resource_ids=(ambulance_unit,))

    view = work_item_view(snapshot, [fire, ambulance])

    assert view.selected_resource_ids == (UUID(str(engine)), UUID(str(ambulance_unit)))


def test_the_union_deduplicates(snapshot: HandoffSnapshot, role_stage_id: RoleStageId) -> None:
    """A unit that somehow appears under two legs is one unit on the work item."""
    shared = ResourceId(uuid4())
    legs = [
        _leg(snapshot, role_stage_id, FIRE, dispatched_resource_ids=(shared,)),
        _leg(snapshot, role_stage_id, AMBULANCE, dispatched_resource_ids=(shared,)),
    ]

    assert work_item_view(snapshot, legs).dispatched_resource_ids == (UUID(str(shared)),)


def test_dispatched_at_is_the_earliest_leg_that_has_one(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    """When the stage first left `RESOURCE_SELECTION` — not when the primary leg did."""
    legs = [
        _leg(snapshot, role_stage_id, FIRE, dispatched_at_offset_ms=200_000),
        _leg(snapshot, role_stage_id, AMBULANCE, dispatched_at_offset_ms=150_000),
    ]

    assert work_item_view(snapshot, legs).dispatched_at_offset_ms == 150_000


def test_dispatched_at_stays_null_while_no_leg_has_one(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    """A recipient service that received no unit leaves the stage's `dispatched_at` unset."""
    legs = [_leg(snapshot, role_stage_id, FIRE), _leg(snapshot, role_stage_id, AMBULANCE)]

    assert work_item_view(snapshot, legs).dispatched_at_offset_ms is None


def test_the_stage_wide_fields_come_from_the_legs_that_all_share_them(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    """`state`, `acknowledged_at`, `closed_at`, `closure_reason` are mirrored across legs (R1)."""
    overrides = {
        "state": DDSStageState.CLOSED,
        "acknowledged_at_offset_ms": 130_000,
        "closed_at_offset_ms": 600_000,
        "closure_reason": ClosureReason.RESOLVED,
    }
    legs = [
        _leg(snapshot, role_stage_id, FIRE, **overrides),
        _leg(snapshot, role_stage_id, AMBULANCE, **overrides),
    ]

    view = work_item_view(snapshot, legs)

    assert view.state is DDSStageState.CLOSED
    assert view.acknowledged_at_offset_ms == 130_000
    assert view.closed_at_offset_ms == 600_000
    assert view.closure_reason is ClosureReason.RESOLVED


# ---------------------------------------------------------------------------------------------
# missing_field_paths
# ---------------------------------------------------------------------------------------------


def test_missing_field_paths_names_the_omission_and_fills_nothing(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    """SPEC §10: the omission propagates — it is named, never repaired."""
    view = work_item_view(snapshot, [_leg(snapshot, role_stage_id, FIRE)])

    # `caller.phone` is `required_for_handoff` and the operator never typed it.
    assert "caller.phone" in view.missing_field_paths
    assert "caller.phone" not in view.card_values
    assert set(view.missing_field_paths) <= set(REQUIRED_FOR_HANDOFF)
    # `address.floor` is not required for handoff, so it is not *reported* as missing — and it
    # is still absent from the values, which is the omission SPEC §10 wants to propagate.
    assert "address.floor" not in view.missing_field_paths
    assert "address.floor" not in view.card_values
    assert "address.house" not in view.missing_field_paths


@pytest.mark.parametrize("empty", [None, "", []])
def test_a_cleared_required_field_counts_as_missing(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId, empty: object
) -> None:
    """A field the trainee cleared is as absent as one they never touched."""
    cleared = snapshot.model_copy(
        update={"card_values": {**snapshot.card_values, "address.house": empty}}
    )

    assert "address.house" in missing_field_paths(cleared)


def test_a_complete_snapshot_has_no_missing_field(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    """The positive case, so the test above cannot pass by always reporting everything."""
    complete = snapshot.model_copy(
        update={
            "card_values": {
                **snapshot.card_values,
                **{path: "заполнено" for path in REQUIRED_FOR_HANDOFF},
                "recipients.services": ["FIRE_RESCUE"],
            }
        }
    )

    assert missing_field_paths(complete) == ()
