"""`SessionReport.dds_decisions` — SPEC §29 item 11: what the DDS acknowledged, dispatched,
reported and closed.

`app.application.handoff.work_item` says it plainly: "The *instructor's*
`InstructorSessionOverview.assignments` and the report's `dds_decisions` are the N legs verbatim —
same schema, two documented readings … this module builds the trainee's reading only." This module
builds the other one. There is no aggregation across legs here — no primary leg, no min, no union:
each `DDSAssignment` row becomes one `DdsDecisionView`, because a review of what the DDS *decided*
must show the ambulance leg and the fire leg as the two decisions they were.

Three of the fields have no column and are folded out of `session_events`, which §20.5 and
`openapi.yaml` both state is their only source:

* `dispatch_events` ← `RESOURCE_DISPATCHED` (`resource_ids`, `callsigns`, `is_additional`), the
  one event that already carries the whole dispatch as one act. `DispatchRecord` rows in
  `resource_state_changes` are per *unit* and would lose "these three went together";
* `status_updates` ← `DDS_STATUS_UPDATE_SENT`. `app.application.dds.send_status_update` says it
  outright: "There is no `status_updates` table: §20.5 declares none, and the event log is the
  record (D5)." The `StatusUpdateView` it builds from the event it just appended is reused here
  verbatim, so the live console and the report render one shape;
* `closure_reason` / `closed_at_offset_ms` ← the leg itself, which `close_incident` stamps.

Every event is matched to its leg by `payload["assignment_id"]`, so a leg with no dispatch and no
report renders with empty lists rather than being dropped: "the DDS did nothing for the police
leg" is a finding, not an absence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.application.dds.views import StatusUpdateView
from app.domain.dds.assignment import DDSAssignment
from app.domain.enums import ClosureReason, ServiceType, StatusUpdateKind
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

__all__ = ["DdsDecision", "DispatchEvent", "dds_decisions"]


@dataclass(frozen=True, slots=True)
class DispatchEvent:
    """One item of `openapi.yaml`'s `DdsDecisionView.dispatch_events` — one dispatch act."""

    at_offset_ms: int
    resource_ids: tuple[UUID, ...]
    callsigns: tuple[str, ...]
    is_additional: bool


@dataclass(frozen=True, slots=True)
class DdsDecision:
    """`openapi.yaml`'s `DdsDecisionView` — one leg of the work item, as decided."""

    assignment_id: UUID
    service_type: ServiceType
    acknowledged_at_offset_ms: int | None
    dispatch_events: tuple[DispatchEvent, ...]
    status_updates: tuple[StatusUpdateView, ...]
    closure_reason: ClosureReason | None
    closed_at_offset_ms: int | None


def dds_decisions(
    legs: Sequence[DDSAssignment], events: Sequence[SessionEvent]
) -> tuple[DdsDecision, ...]:
    """One `DdsDecision` per leg, in the order the legs were created (`received_at_offset_ms`).

    Pure: the legs and the event log are the only inputs, which is the same structural isolation
    `work_item.py` documents — nothing here can reach `WorldTruth`, `CallerBelief` or the live
    `OperatorCard`, because it is never given one.
    """
    dispatches = _dispatch_events_by_assignment(events)
    updates = _status_updates_by_assignment(events)
    ordered = sorted(legs, key=lambda leg: (leg.received_at_offset_ms, str(leg.assignment_id)))
    return tuple(
        DdsDecision(
            assignment_id=UUID(str(leg.assignment_id)),
            service_type=leg.service_type,
            acknowledged_at_offset_ms=leg.acknowledged_at_offset_ms,
            dispatch_events=dispatches.get(UUID(str(leg.assignment_id)), ()),
            status_updates=updates.get(UUID(str(leg.assignment_id)), ()),
            closure_reason=leg.closure_reason,
            closed_at_offset_ms=leg.closed_at_offset_ms,
        )
        for leg in ordered
    )


def _dispatch_events_by_assignment(
    events: Sequence[SessionEvent],
) -> Mapping[UUID, tuple[DispatchEvent, ...]]:
    grouped: dict[UUID, list[DispatchEvent]] = {}
    for event in events:
        if event.event_type is not EventType.RESOURCE_DISPATCHED:
            continue
        assignment_id = _uuid(event.payload.get("assignment_id"))
        if assignment_id is None:
            continue
        grouped.setdefault(assignment_id, []).append(
            DispatchEvent(
                at_offset_ms=int(event.payload.get("at_offset_ms") or event.monotonic_offset_ms),
                resource_ids=tuple(
                    resource
                    for resource in (
                        _uuid(value) for value in event.payload.get("resource_ids") or ()
                    )
                    if resource is not None
                ),
                callsigns=tuple(str(value) for value in event.payload.get("callsigns") or ()),
                is_additional=bool(event.payload.get("is_additional")),
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _status_updates_by_assignment(
    events: Sequence[SessionEvent],
) -> Mapping[UUID, tuple[StatusUpdateView, ...]]:
    grouped: dict[UUID, list[StatusUpdateView]] = {}
    for event in events:
        if event.event_type is not EventType.DDS_STATUS_UPDATE_SENT:
            continue
        assignment_id = _uuid(event.payload.get("assignment_id"))
        actor_user_id = _uuid(event.payload.get("actor_user_id"))
        if assignment_id is None or actor_user_id is None:
            continue
        grouped.setdefault(assignment_id, []).append(
            StatusUpdateView(
                assignment_id=assignment_id,
                update_kind=StatusUpdateKind(str(event.payload["update_kind"])),
                text_ru=str(event.payload.get("text_ru") or ""),
                at_offset_ms=int(event.payload.get("at_offset_ms") or event.monotonic_offset_ms),
                actor_user_id=actor_user_id,
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _uuid(value: object) -> UUID | None:
    """A payload value as a `UUID`, or `None` when it is absent or not one."""
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None
