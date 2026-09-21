"""The pure DDS projections: leg resource lists, `selectable`, and the radio read model.

Three things that have no table and are therefore computed, each with one test file section:

* `project_legs` — `selected_resource_ids` from the live board, `dispatched_resource_ids` from the
  append-only `resource_state_changes` history, per leg (E9 analyst R7). The split is what makes a
  released unit still count as having been sent;
* `selectable` — the `EmergencyResourceView` hint, which must agree with
  `guard_selection_open_and_within_availability_window` rather than guess;
* `radio_message_views` — `RADIO_MESSAGE_CREATED` rows folded into the radio log, filtered by
  `to_role` and paged by `seq_no` (`20-db-schema.md` §20.1: there is no radio table).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.application.dds.leg_for import project_legs
from app.application.dds.views import radio_message_views, selectable
from app.application.ports.resource_repository import DispatchRecord
from app.domain.common.ids import AssignmentId, EventId, ResourceId, SessionId
from app.domain.dds.assignment import DDSAssignment
from app.domain.enums import ActorType, DDSStageState, ResourceStatus, RoleType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.handoff import HandoffSnapshot

from tests.unit.application.dds.conftest import AMBULANCE, FIRE, make_resource, stored

# ---------------------------------------------------------------------------------------------
# project_legs
# ---------------------------------------------------------------------------------------------


def test_selected_units_land_on_the_leg_they_are_attached_to(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """Per leg, not per stage: the fire engine is on the FIRE leg, the ambulance on its own."""
    engine = make_resource("АЦ-1", FIRE, status=ResourceStatus.SELECTED)
    ambulance = make_resource("СМП-11", AMBULANCE, status=ResourceStatus.SELECTED)
    board = [stored(engine, legs[0].assignment_id), stored(ambulance, legs[1].assignment_id)]

    fire_leg, ambulance_leg = project_legs(legs, board, [])

    assert fire_leg.selected_resource_ids == (engine.resource_id,)
    assert ambulance_leg.selected_resource_ids == (ambulance.resource_id,)


def test_a_unit_that_is_attached_but_not_selected_is_not_in_the_selected_list(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """A dispatched unit is still attached; `selected_resource_ids` means `SELECTED`."""
    engine = make_resource("АЦ-1", FIRE, status=ResourceStatus.EN_ROUTE)

    fire_leg, _ = project_legs(legs, [stored(engine, legs[0].assignment_id)], [])

    assert fire_leg.selected_resource_ids == ()


def test_an_unattached_unit_reaches_no_leg(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """A unit in `SELECTED` that hangs on nothing is not part of this work item."""
    stray = make_resource("АЦ-9", FIRE, status=ResourceStatus.SELECTED)

    fire_leg, ambulance_leg = project_legs(legs, [stored(stray, None)], [])

    assert fire_leg.selected_resource_ids == ()
    assert ambulance_leg.selected_resource_ids == ()


def test_dispatched_history_survives_the_units_release(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """R7: the dispatch history comes from the audit rows, never from the live attachment.

    The board here has the unit detached — as `closeDdsIncident` leaves it — and the leg still
    reports that this is the unit it received.
    """
    engine = make_resource("АЦ-1", FIRE, status=ResourceStatus.RETURNING)
    history = [
        DispatchRecord(
            assignment_id=legs[0].assignment_id,
            resource_id=engine.resource_id,
            at_offset_ms=200_000,
        )
    ]

    fire_leg, _ = project_legs(legs, [stored(engine, None)], history)

    assert fire_leg.dispatched_resource_ids == (engine.resource_id,)


def test_a_unit_dispatched_twice_appears_once(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """`dispatched_resource_ids` is a set in list clothing, in first-seen order."""
    engine = make_resource("АЦ-1", FIRE)
    history = [
        DispatchRecord(
            assignment_id=legs[0].assignment_id, resource_id=engine.resource_id, at_offset_ms=ms
        )
        for ms in (200_000, 400_000)
    ]

    fire_leg, _ = project_legs(legs, [stored(engine, legs[0].assignment_id)], history)

    assert fire_leg.dispatched_resource_ids == (engine.resource_id,)


def test_a_leg_that_received_nothing_reports_two_empty_lists(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """The AMBULANCE-got-nothing case the instructor overview needs to be able to show."""
    engine = make_resource("АЦ-1", FIRE, status=ResourceStatus.SELECTED)

    _fire_leg, ambulance_leg = project_legs(legs, [stored(engine, legs[0].assignment_id)], [])

    assert ambulance_leg.selected_resource_ids == ()
    assert ambulance_leg.dispatched_resource_ids == ()


def test_history_for_a_leg_of_another_stage_is_ignored(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """The dispatch history is session-wide; only this stage's legs are projected."""
    engine = make_resource("АЦ-1", FIRE)
    foreign = DispatchRecord(
        assignment_id=AssignmentId(uuid4()),
        resource_id=engine.resource_id,
        at_offset_ms=1,
    )

    for leg in project_legs(legs, [], [foreign]):
        assert leg.dispatched_resource_ids == ()


# ---------------------------------------------------------------------------------------------
# selectable
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        DDSStageState.RESOURCE_SELECTION,
        DDSStageState.EN_ROUTE,
        DDSStageState.ARRIVED,
        DDSStageState.WORKING,
    ],
)
def test_an_available_unit_is_selectable_in_every_selection_open_state(
    state: DDSStageState,
) -> None:
    """The E9 repair, seen from the UI hint: reinforcement is offered where it is possible."""
    assert selectable(make_resource("АЦ-1", FIRE), stage_state=state, now_ms=0) is True


@pytest.mark.parametrize(
    "state", [DDSStageState.RECEIVED, DDSStageState.ACKNOWLEDGED, DDSStageState.DISPATCHED]
)
def test_nothing_is_selectable_before_the_selection_screen_is_open(
    state: DDSStageState,
) -> None:
    assert selectable(make_resource("АЦ-1", FIRE), stage_state=state, now_ms=0) is False


def test_a_unit_outside_its_availability_window_is_not_selectable() -> None:
    """The demo's СМП-12 becomes available at 120 s and not before."""
    unit = make_resource(
        "СМП-12", AMBULANCE, status=ResourceStatus.UNAVAILABLE, available_from_ms=120_000
    )
    available = unit.model_copy(update={"current_status": ResourceStatus.AVAILABLE})

    assert selectable(available, stage_state=DDSStageState.RESOURCE_SELECTION, now_ms=0) is False
    assert (
        selectable(available, stage_state=DDSStageState.RESOURCE_SELECTION, now_ms=120_000) is True
    )


def test_a_unit_that_is_not_available_is_not_selectable() -> None:
    """`select` fires from `AVAILABLE` only, so nothing else can be a candidate."""
    for status in (ResourceStatus.SELECTED, ResourceStatus.EN_ROUTE, ResourceStatus.OUT_OF_SERVICE):
        unit = make_resource("АЦ-1", FIRE, status=status)
        assert selectable(unit, stage_state=DDSStageState.RESOURCE_SELECTION, now_ms=0) is False


# ---------------------------------------------------------------------------------------------
# radio_message_views
# ---------------------------------------------------------------------------------------------

INCIDENT_ID = UUID("11111111-1111-5111-8111-111111111111")


def _radio_event(seq_no: int, to_role: RoleType, text: str = "Приём") -> SessionEvent:
    return SessionEvent(
        id=EventId(uuid4()),
        session_id=SessionId(uuid4()),
        seq_no=seq_no,
        event_type=EventType.RADIO_MESSAGE_CREATED,
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        monotonic_offset_ms=seq_no * 1000,
        actor_type=ActorType.SIMULATION,
        payload={
            "radio_message_id": str(uuid4()),
            "from_callsign": "АЦ-2",
            "to_role": to_role.value,
            "text_ru": text,
            "resource_id": None,
            "source_world_event_id": "ac2_breakdown",
            "at_offset_ms": seq_no * 1000,
        },
    )


def _other_event(seq_no: int) -> SessionEvent:
    return _radio_event(seq_no, RoleType.DDS).model_copy(
        update={"event_type": EventType.NOTIFICATION_CREATED}
    )


def test_only_radio_events_addressed_to_the_role_are_projected() -> None:
    """The contract's filter: `to_role == the caller's role`, and only that event type."""
    events = [
        _radio_event(1, RoleType.DDS),
        _radio_event(2, RoleType.OPERATOR_112),
        _other_event(3),
    ]

    page = radio_message_views(events, incident_id=INCIDENT_ID, to_role=RoleType.DDS)

    assert [item.seq_no for item in page.items] == [1]
    assert page.items[0].to_role is RoleType.DDS
    assert page.items[0].incident_id == INCIDENT_ID


def test_the_page_cursor_is_the_last_seq_no_returned() -> None:
    """`last_seq_no` is what a client passes back as `after_seq_no` (§40.3's shape)."""
    events = [_radio_event(seq, RoleType.DDS) for seq in (4, 7, 9)]

    page = radio_message_views(events, incident_id=INCIDENT_ID, to_role=RoleType.DDS)

    assert page.last_seq_no == 9


def test_after_seq_no_skips_what_the_client_already_has() -> None:
    events = [_radio_event(seq, RoleType.DDS) for seq in (4, 7, 9)]

    page = radio_message_views(
        events, incident_id=INCIDENT_ID, to_role=RoleType.DDS, after_seq_no=7
    )

    assert [item.seq_no for item in page.items] == [9]


def test_an_empty_page_reports_the_cursor_it_was_given() -> None:
    """Polling an idle radio log must not rewind the client's cursor to zero."""
    page = radio_message_views([], incident_id=INCIDENT_ID, to_role=RoleType.DDS, after_seq_no=12)

    assert page.items == ()
    assert page.last_seq_no == 12


def test_the_limit_truncates_and_leaves_a_usable_cursor() -> None:
    events = [_radio_event(seq, RoleType.DDS) for seq in range(1, 6)]

    page = radio_message_views(events, incident_id=INCIDENT_ID, to_role=RoleType.DDS, limit=2)

    assert [item.seq_no for item in page.items] == [1, 2]
    assert page.last_seq_no == 2


def test_the_source_world_event_id_travels_for_the_instructor() -> None:
    """The view carries it; §40.4's redaction is what removes it from a trainee's *event*."""
    page = radio_message_views(
        [_radio_event(1, RoleType.DDS)], incident_id=INCIDENT_ID, to_role=RoleType.DDS
    )

    assert page.items[0].source_world_event_id == "ac2_breakdown"


def test_a_resource_id_in_the_payload_is_carried_through() -> None:
    """`ac2_breakdown`'s radio message names the unit that broke down."""
    resource_id = ResourceId(uuid4())
    event = _radio_event(1, RoleType.DDS)
    event = event.model_copy(update={"payload": {**event.payload, "resource_id": str(resource_id)}})

    page = radio_message_views([event], incident_id=INCIDENT_ID, to_role=RoleType.DDS)

    assert page.items[0].resource_id == UUID(str(resource_id))
