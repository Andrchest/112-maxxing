"""Card status — the §70.4.6 projection and the flush-before-append planner (I3 E4a).

* **The precedence table (assumption A-5).** One row per status, each built so that *every*
  lower-precedence rule also matches: the row asserts that the higher rule wins, which is exactly
  what "first match wins" means. `NOT_NOTIFIED` is also shown to be sticky.
* **The picker mirror** (§70.4.4), `ACCEPTED ≡ DDS_ACKNOWLEDGED`.
* **The planner** (§70.3.5): a deadline event is stamped with its deadline, precedes a later
  event of the same batch, is computed once whatever the flush cadence, and nothing lands in a
  closed or not-yet-started log.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from app.domain.common.actors import ActorRef
from app.domain.dds.card_status import (
    DEFAULT_CARD_TIMERS,
    CardLeg,
    CardStatus,
    CardStatusFold,
    CardStatusReason,
    CardTimers,
    card_status,
    fold_card_status,
    mirror_leg_status,
    plan_append,
)
from app.domain.enums import ActorType, ClosureReason, DDSStageState
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

TIMERS = CardTimers(accept_within_ms=30_000, not_completed_after_ms=600_000)
INCIDENT = UUID("00000000-0000-4000-8000-0000000000aa")
TRAINEE = ActorRef(actor_type=ActorType.TRAINEE)


def _leg(status: str = "RECEIVED", decided: int | None = None, received: int = 0) -> CardLeg:
    return CardLeg(
        assignment_id=f"leg-{status}-{decided}-{received}",
        service_type="FIRE_RESCUE",
        received_at_offset_ms=received,
        status=status,
        decided_at_offset_ms=decided,
    )


# ---------------------------------------------------------------------------------------------
# The precedence table (A-5)
# ---------------------------------------------------------------------------------------------

#: `(expected, legs, handoff offset, now, report released)`. Every row is built so that all the
#: rules *below* the expected one also hold — the row pins that the higher one wins.
PRECEDENCE: list[tuple[CardStatus, list[CardLeg], int | None, int, bool]] = [
    # COMPLETED beats everything: 48 h passed, the leg was not accepted in time, released.
    (CardStatus.COMPLETED, [_leg("COMPLETED", None)], 0, 700_000, True),
    # REFUSED beats NOT_COMPLETED, NOT_NOTIFIED, CHECKED, WORKED.
    (CardStatus.REFUSED, [_leg("NOT_ACCEPTED", None), _leg("RECEIVED")], 0, 700_000, True),
    (CardStatus.REFUSED, [_leg("REFUSED", 5_000)], 0, 700_000, True),
    # NOT_COMPLETED beats NOT_NOTIFIED, CHECKED, WORKED.
    (CardStatus.NOT_COMPLETED, [_leg("RECEIVED", None)], 0, 600_000, True),
    # NOT_NOTIFIED beats CHECKED and WORKED.
    (CardStatus.NOT_NOTIFIED, [_leg("RECEIVED", None)], 0, 30_000, True),
    # CHECKED beats WORKED.
    (CardStatus.CHECKED, [_leg("ACCEPTED", 5_000)], 0, 40_000, True),
    # WORKED: a handoff, nothing else.
    (CardStatus.WORKED, [_leg("ACCEPTED", 5_000)], 0, 40_000, False),
    # REGISTERED: the session started, no handoff yet.
    (CardStatus.REGISTERED, [], None, 999_999, False),
]


@pytest.mark.parametrize(
    ("expected", "legs", "handoff", "now", "released"),
    PRECEDENCE,
    ids=[f"{row[0].value}-{index}" for index, row in enumerate(PRECEDENCE)],
)
def test_the_precedence_table(
    expected: CardStatus,
    legs: list[CardLeg],
    handoff: int | None,
    now: int,
    released: bool,
) -> None:
    assert card_status(legs, handoff, TIMERS, now, released) is expected


def test_every_status_has_a_row() -> None:
    assert {row[0] for row in PRECEDENCE} == set(CardStatus)


def test_not_notified_is_sticky_once_the_accept_deadline_passed() -> None:
    """Accepting late does not lift «Не оповещено»: the decision came at or after the deadline."""
    late = _leg("ACCEPTED", decided=30_000)
    assert card_status([late], 0, TIMERS, 29_999, False) is CardStatus.WORKED
    assert card_status([late], 0, TIMERS, 30_000, False) is CardStatus.NOT_NOTIFIED
    assert card_status([late], 0, TIMERS, 90_000, True) is CardStatus.NOT_NOTIFIED


def test_a_decision_strictly_before_the_deadline_is_in_time() -> None:
    assert card_status([_leg("ACCEPTED", 29_999)], 0, TIMERS, 90_000, False) is CardStatus.WORKED


def test_a_handoff_without_any_notified_service_is_completed() -> None:
    assert card_status([], 0, TIMERS, 0, False) is CardStatus.COMPLETED


def test_a_handoff_naming_services_without_legs_is_worked() -> None:
    """A chain without a DDS stage: the handoff names services, nobody receives them."""
    assert card_status([], 0, TIMERS, 0, False, notification_list_empty=False) is CardStatus.WORKED


# ---------------------------------------------------------------------------------------------
# The picker mirror (§70.4.4)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "closure", "expected"),
    [
        (DDSStageState.RECEIVED, None, "RECEIVED"),
        (DDSStageState.ACKNOWLEDGED, None, "ACCEPTED"),
        (DDSStageState.RESOURCE_SELECTION, None, "ACCEPTED"),
        (DDSStageState.DISPATCHED, None, "ACCEPTED"),
        (DDSStageState.EN_ROUTE, None, "RESPONSE_STARTED"),
        (DDSStageState.ARRIVED, None, "ARRIVED"),
        (DDSStageState.WORKING, None, "WORKING"),
        (DDSStageState.RESOLVED, None, "COMPLETED"),
        (DDSStageState.CLOSED, ClosureReason.RESOLVED, "COMPLETED"),
        (DDSStageState.CLOSED, ClosureReason.FALSE_CALL, "WORKING"),
        (DDSStageState.CLOSED, None, "WORKING"),
    ],
)
def test_the_picker_mirror(
    state: DDSStageState, closure: ClosureReason | None, expected: str
) -> None:
    assert mirror_leg_status(state, closure, previous="WORKING") == expected


# ---------------------------------------------------------------------------------------------
# The fold and the planner (§70.3.5)
# ---------------------------------------------------------------------------------------------


def _event(event_type: EventType, offset: int, **payload: Any) -> DomainEvent:
    return DomainEvent(
        event_type=event_type, actor=TRAINEE, monotonic_offset_ms=offset, payload=payload
    )


def _started_with_legs() -> CardStatusFold:
    """A started GENERATED_CARD-like session: two legs received at 0, status already WORKED."""
    return fold_card_status(
        [
            _event(EventType.SESSION_CREATED, 0, timers=TIMERS.model_dump()),
            _event(EventType.SESSION_STARTED, 0),
            _event(EventType.HANDOFF_RECEIVED, 0, assignment_id="a1", service_type="FIRE_RESCUE"),
            _event(EventType.HANDOFF_RECEIVED, 0, assignment_id="a2", service_type="AMBULANCE"),
            _event(
                EventType.DDS_CARD_STATUS_CHANGED,
                0,
                previous_status="REGISTERED",
                new_status="WORKED",
            ),
        ]
    )


def _status_events(events: list[DomainEvent]) -> list[DomainEvent]:
    return [e for e in events if e.event_type is EventType.DDS_CARD_STATUS_CHANGED]


def test_the_fold_reads_timers_legs_and_the_last_status() -> None:
    fold = _started_with_legs()
    assert fold.timers == TIMERS
    assert [leg.assignment_id for leg in fold.legs] == ["a1", "a2"]
    assert fold.handoff_offset_ms == 0
    assert fold.status is CardStatus.WORKED


def test_a_deadline_is_stamped_with_its_own_offset_and_precedes_the_later_command() -> None:
    ack = _event(EventType.DDS_ACKNOWLEDGED, 40_000, assignment_id="a1")
    planned, after = plan_append(
        _started_with_legs(), [ack], incident_id=INCIDENT, running_now_ms=40_000
    )
    assert [e.event_type for e in planned] == [
        EventType.DDS_CARD_STATUS_CHANGED,
        EventType.DDS_ACKNOWLEDGED,
    ]
    deadline = planned[0]
    assert deadline.monotonic_offset_ms == 30_000
    assert deadline.actor.actor_type is ActorType.SIMULATION
    assert dict(deadline.payload) == {
        "incident_id": str(INCIDENT),
        "previous_status": "WORKED",
        "new_status": "NOT_NOTIFIED",
        "reason": CardStatusReason.ACCEPT_DEADLINE_MISSED.value,
        "assignment_id": "a1",
        "service_type": "FIRE_RESCUE",
        "deadline_offset_ms": 30_000,
        "at_offset_ms": 30_000,
    }
    assert after.status is CardStatus.NOT_NOTIFIED


def test_an_acknowledgement_before_the_deadline_emits_nothing() -> None:
    ack = _event(EventType.DDS_ACKNOWLEDGED, 10_000, assignment_id="a1")
    planned, after = plan_append(
        _started_with_legs(), [ack], incident_id=INCIDENT, running_now_ms=10_000
    )
    assert planned == [ack]
    flushed, _ = plan_append(after, [], incident_id=INCIDENT, running_now_ms=100_000)
    assert flushed == [], "the legs were accepted in time: the deadline changes nothing"


@pytest.mark.parametrize("step_ms", [100, 900, 7_000, 45_000])
def test_the_stream_does_not_depend_on_how_often_anybody_flushed(step_ms: int) -> None:
    """INV 7's pure half: flushing every `step_ms` gives the one stream a single flush gives."""
    fold = _started_with_legs()
    stream: list[DomainEvent] = []
    now = 0
    while now < 700_000:
        now = min(now + step_ms, 700_000)
        flushed, fold = plan_append(fold, [], incident_id=INCIDENT, running_now_ms=now)
        stream.extend(flushed)
    single, _ = plan_append(_started_with_legs(), [], incident_id=INCIDENT, running_now_ms=700_000)
    assert [(e.monotonic_offset_ms, dict(e.payload)) for e in stream] == [
        (e.monotonic_offset_ms, dict(e.payload)) for e in single
    ]
    assert [e.payload["new_status"] for e in single] == ["NOT_NOTIFIED", "NOT_COMPLETED"]
    assert [e.monotonic_offset_ms for e in single] == [30_000, 600_000]


def test_the_running_clock_caps_a_scaled_world_event() -> None:
    """A tick stamps world events in simulated ms; a deadline must not pass early."""
    world = _event(EventType.WORLD_EVENT_TRIGGERED, 60_000)
    planned, _ = plan_append(
        _started_with_legs(), [world], incident_id=INCIDENT, running_now_ms=20_000
    )
    assert planned == [world]


def test_the_batchs_own_change_is_appended_after_it() -> None:
    fold = fold_card_status(
        [_event(EventType.SESSION_CREATED, 0), _event(EventType.SESSION_STARTED, 0)]
    )
    batch = [
        _event(EventType.HANDOFF_CREATED, 5_000, recipient_services=["FIRE_RESCUE"]),
        _event(EventType.HANDOFF_RECEIVED, 5_000, assignment_id="a1", service_type="FIRE_RESCUE"),
    ]
    planned, after = plan_append(fold, batch, incident_id=INCIDENT, running_now_ms=5_000)
    assert planned[:2] == batch
    [changed] = _status_events(planned)
    assert changed.payload["reason"] == "HANDOFF_CREATED"
    assert changed.payload["deadline_offset_ms"] is None
    assert after.status is CardStatus.WORKED


def test_the_closure_completes_the_card_before_the_session_completes() -> None:
    fold = _started_with_legs().apply(EventType.DDS_ACKNOWLEDGED, {}, 10_000)
    batch = [
        _event(EventType.DDS_INCIDENT_CLOSED, 500_000, closure_reason="RESOLVED"),
        _event(EventType.STAGE_STATE_CHANGED, 500_000, role_type="DDS", new_state="CLOSED"),
        _event(EventType.SESSION_COMPLETED, 500_000),
    ]
    planned, after = plan_append(fold, batch, incident_id=INCIDENT, running_now_ms=500_000)
    names = [e.event_type for e in planned]
    assert names.index(EventType.DDS_CARD_STATUS_CHANGED) < names.index(EventType.SESSION_COMPLETED)
    assert after.status is CardStatus.COMPLETED
    assert after.closed


def test_nothing_is_appended_into_a_closed_or_unstarted_log() -> None:
    closed = _started_with_legs().apply(EventType.SESSION_ABORTED, {}, 1_000)
    assert plan_append(closed, [], incident_id=INCIDENT, running_now_ms=900_000)[0] == []
    unstarted = fold_card_status([_event(EventType.SESSION_CREATED, 0)])
    assert plan_append(unstarted, [], incident_id=INCIDENT, running_now_ms=900_000)[0] == []


def test_a_deadline_already_decided_is_not_decided_again() -> None:
    """The horizon: once NOT_COMPLETED is stamped, the old accept deadline is not re-evaluated
    against the later fold (which would invent a NOT_NOTIFIED that never happened)."""
    fold = _started_with_legs()
    first, fold = plan_append(fold, [], incident_id=INCIDENT, running_now_ms=700_000)
    again, _ = plan_append(fold, [], incident_id=INCIDENT, running_now_ms=800_000)
    assert len(first) == 2
    assert again == []


def test_the_defaults_are_the_memos() -> None:
    assert DEFAULT_CARD_TIMERS.model_dump() == {
        "accept_within_ms": 30_000,
        "fill_within_ms": 180_000,
        "not_completed_after_ms": 172_800_000,
    }


# ---------------------------------------------------------------------------------------------
# Leg-aware (I3 E5a): in memo mode the legs move by their own DDS_SERVICE_STATUS_SET
# ---------------------------------------------------------------------------------------------

MEMO_VARIANTS = {
    "card_source": "GENERATED_CARD",
    "dds_mode": "MEMO_STATUSES",
    "dds_card_check": "OFF",
    "dds_brigade_call": "OFF",
}


def _status_set(offset: int, assignment_id: str, previous: str, new: str) -> DomainEvent:
    return _event(
        EventType.DDS_SERVICE_STATUS_SET,
        offset,
        assignment_id=assignment_id,
        previous_status=previous,
        new_status=new,
    )


def _memo_started() -> CardStatusFold:
    """A started memo session: two legs `ADDED` at 0, status `WORKED`."""
    return fold_card_status(
        [
            _event(
                EventType.SESSION_CREATED, 0, timers=TIMERS.model_dump(), variants=MEMO_VARIANTS
            ),
            _event(EventType.SESSION_STARTED, 0),
            _event(
                EventType.HANDOFF_RECEIVED,
                0,
                assignment_id="a1",
                service_type="FIRE_RESCUE",
                initial_response_status="ADDED",
            ),
            _event(
                EventType.HANDOFF_RECEIVED,
                0,
                assignment_id="a2",
                service_type="POLICE",
                initial_response_status="ADDED",
            ),
            _event(
                EventType.DDS_CARD_STATUS_CHANGED,
                0,
                previous_status="REGISTERED",
                new_status="WORKED",
            ),
        ]
    )


def test_memo_legs_start_added_and_the_stage_moves_none_of_them() -> None:
    fold = _memo_started()
    assert fold.memo
    assert [leg.status for leg in fold.legs] == ["ADDED", "ADDED"]
    moved = fold.apply(
        EventType.STAGE_STATE_CHANGED,
        {"role_type": "DDS", "new_state": "ACKNOWLEDGED"},
        5_000,
    ).apply(EventType.DDS_ACKNOWLEDGED, {"assignment_id": "a1"}, 5_000)
    assert [leg.status for leg in moved.legs] == ["ADDED", "ADDED"]
    assert [leg.decided_at_offset_ms for leg in moved.legs] == [None, None]
    assert moved.dds_state is DDSStageState.ACKNOWLEDGED


def test_a_memo_leg_takes_its_own_status_and_its_first_decision() -> None:
    fold = _memo_started()
    for event in (
        _status_set(3_000, "a1", "ADDED", "RECEIVED"),
        _status_set(4_000, "a1", "RECEIVED", "NOT_ACCEPTED"),
        _status_set(9_000, "a1", "NOT_ACCEPTED", "ACCEPTED"),
    ):
        fold = fold.apply(event.event_type, event.payload, event.monotonic_offset_ms)
    first, second = fold.legs
    assert (first.status, first.decided_at_offset_ms) == ("ACCEPTED", 4_000)
    assert (second.status, second.decided_at_offset_ms) == ("ADDED", None)


def test_a_memo_decision_is_accepted_from_the_leg_not_from_the_acknowledgement() -> None:
    """ACCEPTED comes from the leg status (E5a), so only the leg that decided is in time; the
    other misses its deadline even though the stage was acknowledged."""
    batch = [
        _status_set(10_000, "a1", "ADDED", "RECEIVED"),
        _status_set(10_000, "a1", "RECEIVED", "ACCEPTED"),
        _event(EventType.DDS_ACKNOWLEDGED, 10_000, assignment_id="a1"),
    ]
    _planned, after = plan_append(
        _memo_started(), batch, incident_id=INCIDENT, running_now_ms=10_000
    )
    flushed, after = plan_append(after, [], incident_id=INCIDENT, running_now_ms=40_000)
    [missed] = _status_events(flushed)
    assert missed.payload["new_status"] == "NOT_NOTIFIED"
    assert missed.payload["assignment_id"] == "a2"
    assert missed.monotonic_offset_ms == 30_000


def test_memo_card_status_follows_decline_correction_and_completion() -> None:
    fold = _memo_started()
    declined, fold = plan_append(
        fold,
        [
            _status_set(5_000, "a1", "ADDED", "RECEIVED"),
            _status_set(5_000, "a1", "RECEIVED", "NOT_ACCEPTED"),
        ],
        incident_id=INCIDENT,
        running_now_ms=5_000,
    )
    assert [(e.payload["new_status"], e.payload["reason"]) for e in _status_events(declined)] == [
        ("REFUSED", "LEG_DECLINED_OR_REFUSED")
    ]
    corrected, fold = plan_append(
        fold,
        [_status_set(6_000, "a1", "NOT_ACCEPTED", "ACCEPTED")],
        incident_id=INCIDENT,
        running_now_ms=6_000,
    )
    assert [(e.payload["new_status"], e.payload["reason"]) for e in _status_events(corrected)] == [
        ("WORKED", "LEG_STATUS_CORRECTED")
    ]
    completing = [
        _status_set(7_000, "a2", "ADDED", "RECEIVED"),
        _status_set(7_000, "a2", "RECEIVED", "ACCEPTED"),
        *(
            _status_set(8_000, leg, previous, new)
            for leg in ("a1", "a2")
            for previous, new in (
                ("ACCEPTED", "RESPONSE_STARTED"),
                ("RESPONSE_STARTED", "ARRIVED"),
                ("ARRIVED", "WORKING"),
                ("WORKING", "COMPLETED"),
            )
        ),
    ]
    completed, fold = plan_append(fold, completing, incident_id=INCIDENT, running_now_ms=8_000)
    assert [(e.payload["new_status"], e.payload["reason"]) for e in _status_events(completed)] == [
        ("COMPLETED", "ALL_LEGS_COMPLETED")
    ]


def test_picker_mode_ignores_the_mirrored_status_events() -> None:
    """In picker mode the stage event already applied the picker map; the `PICKER_MIRROR` status
    events that follow carry the same values and are not re-read (E4a's projection, unchanged)."""
    fold = _started_with_legs()
    assert not fold.memo
    after = fold.apply(
        EventType.DDS_SERVICE_STATUS_SET,
        {"assignment_id": "a1", "previous_status": "RECEIVED", "new_status": "REFUSED"},
        1_000,
    )
    assert [leg.status for leg in after.legs] == [leg.status for leg in fold.legs]
