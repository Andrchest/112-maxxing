"""`SessionReport.resource_timeline` — every step a unit took (SPEC §29 item 12).

`openapi.yaml` calls the view "one `RESOURCE_STATUS_CHANGED` step", and the projection takes that
literally: the event log, in `seq_no` order, including the world engine's own transitions — which
are the ones a trainee most often wants to read next to their own decisions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.application.reports.resource_timeline import resource_timeline
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType, ResourceStatus
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

from tests.unit.domain.session._builders import det_uuid

SESSION = SessionId(det_uuid("session"))
NOW = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
UNIT = det_uuid("unit-a")


def _event(seq_no: int, event_type: EventType, **payload: object) -> SessionEvent:
    return SessionEvent(
        id=det_uuid(f"event-{seq_no}"),
        session_id=SESSION,
        seq_no=seq_no,
        event_type=event_type,
        timestamp_utc=NOW,
        monotonic_offset_ms=seq_no * 100,
        actor_type=ActorType.SIMULATION,
        payload=payload,
    )


def _status_change(
    seq_no: int, previous: str | None, new: str, *, trigger: str = "dispatch", at: int | None = None
) -> SessionEvent:
    return _event(
        seq_no,
        EventType.RESOURCE_STATUS_CHANGED,
        resource_id=str(UNIT),
        callsign="АЦ-1",
        previous_status=previous,
        new_status=new,
        trigger=trigger,
        at_offset_ms=at if at is not None else seq_no * 100,
    )


def test_the_timeline_reads_down_the_page_in_log_order() -> None:
    entries = resource_timeline(
        [
            _status_change(3, "DISPATCHED", "EN_ROUTE"),
            _status_change(1, "AVAILABLE", "SELECTED", trigger="select"),
            _status_change(2, "SELECTED", "DISPATCHED"),
        ]
    )
    assert [entry.new_status for entry in entries] == [
        ResourceStatus.SELECTED,
        ResourceStatus.DISPATCHED,
        ResourceStatus.EN_ROUTE,
    ]
    assert entries[0].trigger == "select"
    assert entries[0].callsign == "АЦ-1"
    assert entries[0].resource_id == UNIT


def test_other_event_types_are_not_in_the_resource_timeline() -> None:
    entries = resource_timeline(
        [
            _event(1, EventType.RESOURCE_DISPATCHED, assignment_id=str(det_uuid("leg"))),
            _status_change(2, "SELECTED", "DISPATCHED"),
            _event(3, EventType.CARD_FIELD_CHANGED, field_path="incident.type"),
        ]
    )
    assert len(entries) == 1


def test_a_first_transition_has_no_previous_status() -> None:
    """Nothing preceded it; inventing a "previous" the log does not hold would be fabricating
    history, so the entry reports `null`."""
    (entry,) = resource_timeline([_status_change(1, None, "AVAILABLE", trigger="scenario")])
    assert entry.previous_status is None
    assert entry.new_status is ResourceStatus.AVAILABLE


def test_the_stored_offset_wins_over_the_envelope_offset() -> None:
    (entry,) = resource_timeline([_status_change(9, "AVAILABLE", "SELECTED", at=4321)])
    assert entry.at_offset_ms == 4321


def test_an_empty_log_is_an_empty_timeline() -> None:
    assert resource_timeline([]) == ()
