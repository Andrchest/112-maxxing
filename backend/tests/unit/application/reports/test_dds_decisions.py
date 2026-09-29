"""`SessionReport.dds_decisions` — the N legs verbatim (SPEC §29 item 11).

The distinction from `app.application.handoff.work_item` is the point of this projection and of
this file: the trainee's work item aggregates the legs into one (primary leg, min offset, union of
units); the report shows them **as the N decisions they were**, because a review of what the DDS
decided must not hide that the ambulance leg was acknowledged and the police leg was not.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.application.reports.dds_decisions import dds_decisions
from app.domain.common.ids import (
    AssignmentId,
    IncidentId,
    RoleStageId,
    SessionId,
    SnapshotId,
)
from app.domain.dds.assignment import DDSAssignment
from app.domain.enums import ActorType, ClosureReason, DDSStageState, ServiceId
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

from tests.unit.domain.session._builders import det_uuid

SESSION = SessionId(det_uuid("session"))
STAGE = RoleStageId(det_uuid("stage"))
INCIDENT = IncidentId(det_uuid("incident"))
SNAPSHOT = SnapshotId(det_uuid("snapshot"))
ACTOR = det_uuid("dds-user")
NOW = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)

FIRE = AssignmentId(det_uuid("leg-fire"))
AMBULANCE = AssignmentId(det_uuid("leg-ambulance"))


def _leg(
    assignment_id: AssignmentId,
    service_type: ServiceId,
    *,
    received_at_offset_ms: int,
    acknowledged_at_offset_ms: int | None = None,
    closed_at_offset_ms: int | None = None,
    closure_reason: ClosureReason | None = None,
) -> DDSAssignment:
    return DDSAssignment(
        assignment_id=assignment_id,
        incident_id=INCIDENT,
        role_stage_id=STAGE,
        snapshot_id=SNAPSHOT,
        service_type=service_type,
        state=DDSStageState.CLOSED if closed_at_offset_ms else DDSStageState.RECEIVED,
        received_at_offset_ms=received_at_offset_ms,
        acknowledged_at_offset_ms=acknowledged_at_offset_ms,
        closed_at_offset_ms=closed_at_offset_ms,
        closure_reason=closure_reason,
    )


def _event(seq_no: int, event_type: EventType, **payload: object) -> SessionEvent:
    return SessionEvent(
        id=det_uuid(f"event-{seq_no}"),
        session_id=SESSION,
        seq_no=seq_no,
        event_type=event_type,
        timestamp_utc=NOW,
        monotonic_offset_ms=seq_no * 100,
        actor_type=ActorType.TRAINEE,
        payload=payload,
    )


def test_each_leg_becomes_its_own_decision() -> None:
    """No aggregation: two legs, two rows, in `received_at_offset_ms` order."""
    decisions = dds_decisions(
        [
            _leg(AMBULANCE, ServiceId("AMBULANCE"), received_at_offset_ms=200),
            _leg(FIRE, ServiceId("FIRE_RESCUE"), received_at_offset_ms=100),
        ],
        [],
    )
    assert [decision.service_type for decision in decisions] == [
        ServiceId("FIRE_RESCUE"),
        ServiceId("AMBULANCE"),
    ]


def test_a_leg_with_no_activity_renders_with_empty_lists() -> None:
    """A leg with no activity is a finding, not an absence — it renders, with empty lists."""
    (decision,) = dds_decisions([_leg(FIRE, ServiceId("POLICE"), received_at_offset_ms=0)], [])
    assert decision.dispatch_events == ()
    assert decision.status_updates == ()
    assert decision.acknowledged_at_offset_ms is None
    assert decision.closure_reason is None
    assert decision.closed_at_offset_ms is None


def test_dispatches_are_grouped_by_leg_and_keep_their_units_together() -> None:
    """One `RESOURCE_DISPATCHED` is one dispatch *act*; the per-unit audit rows would lose that
    these three went out together."""
    unit_a, unit_b = det_uuid("unit-a"), det_uuid("unit-b")
    decisions = dds_decisions(
        [
            _leg(FIRE, ServiceId("FIRE_RESCUE"), received_at_offset_ms=0),
            _leg(AMBULANCE, ServiceId("AMBULANCE"), received_at_offset_ms=1),
        ],
        [
            _event(
                1,
                EventType.RESOURCE_DISPATCHED,
                assignment_id=str(FIRE),
                resource_ids=[str(unit_a), str(unit_b)],
                callsigns=["АЦ-1", "АЦ-2"],
                at_offset_ms=5000,
                is_additional=False,
            ),
            _event(
                2,
                EventType.RESOURCE_DISPATCHED,
                assignment_id=str(FIRE),
                resource_ids=[str(unit_a)],
                callsigns=["АЦ-1"],
                at_offset_ms=9000,
                is_additional=True,
            ),
        ],
    )
    fire, ambulance = decisions
    assert len(fire.dispatch_events) == 2
    assert fire.dispatch_events[0].resource_ids == (unit_a, unit_b)
    assert fire.dispatch_events[0].callsigns == ("АЦ-1", "АЦ-2")
    assert fire.dispatch_events[0].is_additional is False
    assert fire.dispatch_events[1].is_additional is True
    assert fire.dispatch_events[1].at_offset_ms == 9000
    assert ambulance.dispatch_events == (), "another leg's dispatch is not this leg's decision"


def test_status_updates_are_folded_out_of_the_event_log() -> None:
    """There is no `status_updates` table (§20.5 declares none); the log is the record (D5)."""
    (decision,) = dds_decisions(
        [_leg(FIRE, ServiceId("FIRE_RESCUE"), received_at_offset_ms=0)],
        [
            _event(
                1,
                EventType.DDS_STATUS_UPDATE_SENT,
                assignment_id=str(FIRE),
                update_kind="ON_SCENE_REPORT",
                text_ru="Прибыли на место",
                at_offset_ms=7000,
                actor_user_id=str(ACTOR),
            )
        ],
    )
    (update,) = decision.status_updates
    assert update.text_ru == "Прибыли на место"
    assert update.at_offset_ms == 7000
    assert update.actor_user_id == ACTOR


def test_closure_comes_from_the_leg_itself() -> None:
    (decision,) = dds_decisions(
        [
            _leg(
                FIRE,
                ServiceId("FIRE_RESCUE"),
                received_at_offset_ms=0,
                acknowledged_at_offset_ms=1500,
                closed_at_offset_ms=60000,
                closure_reason=ClosureReason.RESOLVED,
            )
        ],
        [],
    )
    assert decision.acknowledged_at_offset_ms == 1500
    assert decision.closed_at_offset_ms == 60000
    assert decision.closure_reason is ClosureReason.RESOLVED


# -- E20-E R11: note_ru / comment_ru, additive from the catalog keys E17-A recorded -------------


def test_a_dispatch_note_is_carried_onto_its_dispatch_event() -> None:
    (decision,) = dds_decisions(
        [_leg(FIRE, ServiceId("FIRE_RESCUE"), received_at_offset_ms=0)],
        [
            _event(
                1,
                EventType.RESOURCE_DISPATCHED,
                assignment_id=str(FIRE),
                resource_ids=[],
                callsigns=[],
                at_offset_ms=5000,
                is_additional=False,
                note_ru="Заблокированный подъезд, заезжать со двора",
            )
        ],
    )
    (dispatch,) = decision.dispatch_events
    assert dispatch.note_ru == "Заблокированный подъезд, заезжать со двора"


def test_a_dispatch_with_no_note_is_none_not_an_empty_string() -> None:
    (decision,) = dds_decisions(
        [_leg(FIRE, ServiceId("FIRE_RESCUE"), received_at_offset_ms=0)],
        [
            _event(
                1,
                EventType.RESOURCE_DISPATCHED,
                assignment_id=str(FIRE),
                resource_ids=[],
                callsigns=[],
                at_offset_ms=5000,
                is_additional=False,
            )
        ],
    )
    (dispatch,) = decision.dispatch_events
    assert dispatch.note_ru is None


def test_a_closure_comment_is_carried_onto_the_decision() -> None:
    (decision,) = dds_decisions(
        [
            _leg(
                FIRE,
                ServiceId("FIRE_RESCUE"),
                received_at_offset_ms=0,
                closed_at_offset_ms=60000,
                closure_reason=ClosureReason.RESOLVED,
            )
        ],
        [
            _event(
                1,
                EventType.DDS_INCIDENT_CLOSED,
                assignment_id=str(FIRE),
                closure_reason=ClosureReason.RESOLVED.value,
                released_resource_ids=[],
                at_offset_ms=60000,
                actor_user_id=str(ACTOR),
                comment_ru="Ложный вызов подтверждён на месте",
            )
        ],
    )
    assert decision.comment_ru == "Ложный вызов подтверждён на месте"


def test_a_closure_with_no_comment_is_none() -> None:
    (decision,) = dds_decisions(
        [
            _leg(
                FIRE,
                ServiceId("FIRE_RESCUE"),
                received_at_offset_ms=0,
                closed_at_offset_ms=60000,
                closure_reason=ClosureReason.RESOLVED,
            )
        ],
        [],
    )
    assert decision.comment_ru is None


def test_another_legs_note_and_comment_do_not_leak_onto_this_leg() -> None:
    decisions = dds_decisions(
        [
            _leg(FIRE, ServiceId("FIRE_RESCUE"), received_at_offset_ms=0),
            _leg(
                AMBULANCE,
                ServiceId("AMBULANCE"),
                received_at_offset_ms=1,
                closed_at_offset_ms=60000,
                closure_reason=ClosureReason.RESOLVED,
            ),
        ],
        [
            _event(
                1,
                EventType.RESOURCE_DISPATCHED,
                assignment_id=str(FIRE),
                resource_ids=[],
                callsigns=[],
                at_offset_ms=5000,
                is_additional=False,
                note_ru="Только для пожарного расчёта",
            ),
            _event(
                2,
                EventType.DDS_INCIDENT_CLOSED,
                assignment_id=str(AMBULANCE),
                closure_reason=ClosureReason.RESOLVED.value,
                released_resource_ids=[],
                at_offset_ms=60000,
                actor_user_id=str(ACTOR),
                comment_ru="Только для бригады скорой",
            ),
        ],
    )
    fire, ambulance = decisions
    assert fire.comment_ru is None
    assert ambulance.dispatch_events == ()


def test_an_event_without_a_resolvable_assignment_is_ignored() -> None:
    """A payload that cannot name its leg is dropped rather than attributed to an arbitrary one."""
    (decision,) = dds_decisions(
        [_leg(FIRE, ServiceId("FIRE_RESCUE"), received_at_offset_ms=0)],
        [_event(1, EventType.RESOURCE_DISPATCHED, resource_ids=[], callsigns=[])],
    )
    assert decision.dispatch_events == ()


def test_an_unrelated_event_type_contributes_nothing() -> None:
    (decision,) = dds_decisions(
        [_leg(FIRE, ServiceId("FIRE_RESCUE"), received_at_offset_ms=0)],
        [_event(1, EventType.CARD_FIELD_CHANGED, field_path="incident.type")],
    )
    assert decision.dispatch_events == ()
    assert decision.status_updates == ()


def test_every_leg_carries_the_cards_last_marks() -> None:
    """I7 E55: the ДДС's «ЧС» / «ЧП» are the card's, so every leg shows the same last pair."""
    legs = [
        _leg(FIRE, ServiceId("FIRE_RESCUE"), received_at_offset_ms=0),
        _leg(AMBULANCE, ServiceId("AMBULANCE"), received_at_offset_ms=0),
    ]
    assert {(d.dds_marks.chs, d.dds_marks.chp) for d in dds_decisions(legs, [])} == {(False, False)}
    log = [
        _event(1, EventType.DDS_CARD_MARKS_SET, chs=True, chp=False),
        _event(2, EventType.DDS_CARD_MARKS_SET, chs=True, chp=True),
    ]
    assert {(d.dds_marks.chs, d.dds_marks.chp) for d in dds_decisions(legs, log)} == {(True, True)}
