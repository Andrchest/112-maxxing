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
  nothing ever handed one in;
* (I7 E55) `for_viewer`: a ДДС trainee whose own legs are all the 03 service reads the first 100
  characters of `description.text`; every other reader reads it whole.
"""

from __future__ import annotations

import typing
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.application.handoff.work_item import (
    DESCRIPTION_LIMIT_CHARS,
    REQUIRED_FOR_HANDOFF,
    DdsMarksView,
    dds_marks_of,
    for_viewer,
    missing_field_paths,
    primary_leg,
    with_dds_marks,
    work_item_view,
)
from app.domain.common.ids import (
    AssignmentId,
    CardId,
    CardRevisionId,
    EventId,
    IncidentId,
    ResourceId,
    RoleStageId,
    SessionId,
    SnapshotId,
    UserId,
)
from app.domain.dds.assignment import DDSAssignment
from app.domain.enums import ActorType, ClosureReason, DDSStageState, ServiceId
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import CARD_FIELDS
from pydantic import BaseModel

FIRE = ServiceId("FIRE_RESCUE")
AMBULANCE = ServiceId("AMBULANCE")


def _is_identifier_or_timestamp_annotation(annotation: object) -> bool:
    """`True` for a `UUID`- or `datetime`-typed annotation, `X | None`/`tuple[X, ...]` included.

    Recurses into a generic's type arguments (`get_args`), so `tuple[UUID, ...]` and `datetime |
    None` both count, exactly like the bare `UUID`/`datetime` they wrap.
    """
    origin = typing.get_origin(annotation)
    if origin is not None:
        return any(
            _is_identifier_or_timestamp_annotation(argument)
            for argument in typing.get_args(annotation)
        )
    return isinstance(annotation, type) and issubclass(annotation, (UUID, datetime))


def _free_text_dump(model: BaseModel) -> str:
    """`str(model.model_dump())`, minus every field a random value could spuriously match.

    A random UUID, a sha256 digest or a timestamp is exactly the kind of value that occasionally
    contains a short digit string like "27" by chance — which is what made
    `test_the_snapshot_supplies_every_frozen_field` flaky (E11-0). This derives the exclusion from
    the model's own field types instead of hand-listing `DdsWorkItemView`'s field names, so a new
    free-text field is still checked by default and only an identifier/timestamp-shaped field (or
    one whose name says it is a hash — Python has no dedicated "sha256 digest" type to introspect)
    is ever left out.
    """
    fields = type(model).model_fields
    excluded = {
        name
        for name, info in fields.items()
        if _is_identifier_or_timestamp_annotation(info.annotation) or name.endswith("_sha256")
    }
    # `field_specs` (I3 E3a) is the pack's card *specification* — the same for every session, its
    # `order` integers included — not data copied from anywhere; it is pinned separately below.
    excluded.add("field_specs")
    included = set(fields) - excluded
    return str(model.model_dump(include=included))


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
    service_type: ServiceId,
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
    # Every identifier/hash/timestamp field is excluded first (they are random and occasionally
    # contain "27" by chance, e.g. inside a UUID or a sha256 digest — see `_free_text_dump`); what
    # is left is the free-text/enum data the projection actually copies from the snapshot, and
    # that must never contain the world-truth house number.
    assert "27" not in _free_text_dump(view)
    # The specification part is the card schema's, verbatim (v1 when none is given).
    assert view.card_schema == "v1"
    assert [spec.field_path for spec in view.field_specs] == [s.field_path for s in CARD_FIELDS]


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


# ---------------------------------------------------------------------------------------------
# «в службу 03 передаются только первые 100 символов» (I7 E55)
# ---------------------------------------------------------------------------------------------

LONG_DESCRIPTION = "Горит квартира на третьем этаже, " * 10


def _described(snapshot: HandoffSnapshot) -> HandoffSnapshot:
    return snapshot.model_copy(
        update={"card_values": {**snapshot.card_values, "description.text": LONG_DESCRIPTION}}
    )


def test_the_03_service_reads_the_first_100_characters_of_the_description(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    snapshot = _described(snapshot)
    medic, firefighter = UserId(uuid4()), UserId(uuid4())
    legs = [
        _leg(snapshot, role_stage_id, FIRE, bound_user_id=firefighter),
        _leg(snapshot, role_stage_id, AMBULANCE, bound_user_id=medic),
    ]
    view = work_item_view(snapshot, legs)
    assert len(LONG_DESCRIPTION) > DESCRIPTION_LIMIT_CHARS

    cut = for_viewer(view, legs, medic)
    assert cut.card_values["description.text"] == LONG_DESCRIPTION[:DESCRIPTION_LIMIT_CHARS]
    # Nothing else moves, and the snapshot's own hash still covers the whole text.
    assert {k: v for k, v in cut.card_values.items() if k != "description.text"} == CARD_VALUES
    assert cut.handoff_content_sha256 == view.handoff_content_sha256
    # The other service, and the instructor (`None`), read it whole.
    assert for_viewer(view, legs, firefighter).card_values["description.text"] == LONG_DESCRIPTION
    assert for_viewer(view, legs, None).card_values["description.text"] == LONG_DESCRIPTION


def test_a_viewer_of_more_than_the_03_service_reads_the_whole_description(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    snapshot = _described(snapshot)
    trainee = UserId(uuid4())
    bound_to_both = [
        _leg(snapshot, role_stage_id, FIRE, bound_user_id=trainee),
        _leg(snapshot, role_stage_id, AMBULANCE, bound_user_id=trainee),
    ]
    unbound = [_leg(snapshot, role_stage_id, FIRE), _leg(snapshot, role_stage_id, AMBULANCE)]
    for legs in (bound_to_both, unbound):
        view = for_viewer(work_item_view(snapshot, legs), legs, trainee)
        assert view.card_values["description.text"] == LONG_DESCRIPTION


def test_a_short_description_reaches_the_03_service_whole(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    medic = UserId(uuid4())
    short = snapshot.model_copy(
        update={"card_values": {**snapshot.card_values, "description.text": "Пожар в квартире"}}
    )
    legs = [_leg(short, role_stage_id, AMBULANCE, bound_user_id=medic)]
    view = work_item_view(short, legs)
    assert for_viewer(view, legs, medic) == view


# ---------------------------------------------------------------------------------------------
# «ЧС» / «ЧП» (I7 E55)
# ---------------------------------------------------------------------------------------------


def _marks_event(seq_no: int, *, chs: bool, chp: bool) -> SessionEvent:
    return SessionEvent(
        id=EventId(uuid4()),
        session_id=SessionId(uuid4()),
        seq_no=seq_no,
        event_type=EventType.DDS_CARD_MARKS_SET,
        timestamp_utc=datetime(2026, 9, 29, tzinfo=UTC),
        monotonic_offset_ms=seq_no * 1_000,
        actor_type=ActorType.TRAINEE,
        actor_id=UserId(uuid4()),
        payload={"chs": chs, "chp": chp},
    )


def test_the_marks_default_off_and_the_last_event_wins(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    assert dds_marks_of([]) == DdsMarksView(chs=False, chp=False)
    log = [_marks_event(1, chs=True, chp=True), _marks_event(2, chs=False, chp=True)]
    assert dds_marks_of(log) == DdsMarksView(chs=False, chp=True)
    view = work_item_view(snapshot, [_leg(snapshot, role_stage_id, FIRE)])
    assert view.dds_marks == DdsMarksView()
    marked = with_dds_marks(view, log)
    assert marked.dds_marks == DdsMarksView(chs=False, chp=True)
    assert marked.model_copy(update={"dds_marks": DdsMarksView()}) == view
