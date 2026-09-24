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

**The memo statuses (I3 E5b, HLD 70 §70.4.3, D16).** Each leg also carries its final
`response_status`, who played it (`responder`, `bound_user_id`), its whole status history —
folded from `DDS_SERVICE_STATUS_SET`, the source the `dds_service_status_history` read model is
itself materialised from, rendered as the leg block renders it (`ServiceStatusEntryView`: the author
before the time, REQ-5295) — and the card issues its service flagged (`DDS_CARD_ISSUE_FLAGGED`,
`dds_card_check: ON`). `dds_participant_totals` adds the per-ДДС-participant counts a review of
several ДДС trainees needs: the legs each played, the statuses each set, their primary decisions,
refusals and completions, and their card-issue flags. Both are pure folds over the legs and the log.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple
from uuid import UUID

from app.application.dds.views import CardIssueView, ServiceStatusEntryView, StatusUpdateView
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.card_issue import CardIssueKind
from app.domain.dds.response import LegResponder, ServiceResponseStatus, StatusSource
from app.domain.enums import ClosureReason, ServiceId, StatusUpdateKind
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

__all__ = [
    "DdsDecision",
    "DdsParticipant",
    "DdsParticipantTotals",
    "DispatchEvent",
    "dds_decisions",
    "dds_participant_totals",
]

_S = ServiceResponseStatus
_SYSTEM_DISPLAY_RU = "Система"
"""Who a SIMULATION entry is shown as (the leg block's word, `app.application.dds.views`)."""


@dataclass(frozen=True, slots=True)
class DispatchEvent:
    """One item of `openapi.yaml`'s `DdsDecisionView.dispatch_events` — one dispatch act."""

    at_offset_ms: int
    resource_ids: tuple[UUID, ...]
    callsigns: tuple[str, ...]
    is_additional: bool
    note_ru: str | None = None
    """ADDITIVE (E20-E R11): `RESOURCE_DISPATCHED.note_ru` (E17 R2) — the trainee's free-text
    dispatch note, `None` when none was given."""


@dataclass(frozen=True, slots=True)
class DdsDecision:
    """`openapi.yaml`'s `DdsDecisionView` — one leg of the work item, as decided."""

    assignment_id: UUID
    service_type: ServiceId
    acknowledged_at_offset_ms: int | None
    dispatch_events: tuple[DispatchEvent, ...]
    status_updates: tuple[StatusUpdateView, ...]
    closure_reason: ClosureReason | None
    closed_at_offset_ms: int | None
    comment_ru: str | None = None
    """ADDITIVE (E20-E R11): `DDS_INCIDENT_CLOSED.comment_ru` (E17 R2) — the trainee's free-text
    closure comment, `None` when none was given or the leg is not yet closed."""
    response_status: ServiceResponseStatus = ServiceResponseStatus.ADDED
    """ADDITIVE (I3 E5b): the leg's last memo status (picker legs: the mirrored one)."""
    responder: LegResponder = LegResponder.TRAINEE
    """ADDITIVE (I3 E5b): who played the leg — a ДДС trainee or the scenario's script."""
    bound_user_id: UUID | None = None
    """ADDITIVE (I3 E5b): the ДДС participant bound to the leg's service, if any."""
    status_history: tuple[ServiceStatusEntryView, ...] = ()
    """ADDITIVE (I3 E5b): every `DDS_SERVICE_STATUS_SET` of the leg, in log order."""
    card_issues: tuple[CardIssueView, ...] = ()
    """ADDITIVE (I3 E5b): every `DDS_CARD_ISSUE_FLAGGED` raised on the leg."""


class DdsParticipant(NamedTuple):
    """One ДДС participant of the session, as `dds_participant_totals` needs them."""

    user_id: UUID
    display_name_ru: str
    assigned_service_id: str | None


@dataclass(frozen=True, slots=True)
class DdsParticipantTotals:
    """`openapi.yaml`'s `DdsParticipantTotalsView` — one ДДС participant's totals (I3 E5b)."""

    user_id: UUID
    display_name_ru: str
    assigned_service_id: str | None
    legs: int
    """The legs this participant played: bound to them, or every trainee leg when nobody is
    bound (one trainee plays every leg, §70.4.5)."""
    status_entries: int
    """`DDS_SERVICE_STATUS_SET`s this participant authored (TRAINEE)."""
    accepted: int
    not_accepted: int
    refused: int
    completed: int
    card_issues: int


def dds_decisions(
    legs: Sequence[DDSAssignment],
    events: Sequence[SessionEvent],
    *,
    display_names: Mapping[UUID, str] | None = None,
    service_names: Mapping[str, str] | None = None,
) -> tuple[DdsDecision, ...]:
    """One `DdsDecision` per leg, in the order the legs were created (`received_at_offset_ms`).

    Pure: the legs and the event log are the only inputs, which is the same structural isolation
    `work_item.py` documents — nothing here can reach `WorldTruth`, `CallerBelief` or the live
    `OperatorCard`, because it is never given one. `display_names` (participant → name) and
    `service_names` (service id → catalog name) only label the history's authors.
    """
    dispatches = _dispatch_events_by_assignment(events)
    updates = _status_updates_by_assignment(events)
    comments = _closure_comments_by_assignment(events)
    history = _status_history_by_assignment(events, display_names or {}, service_names or {})
    issues = _card_issues_by_assignment(events)
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
            comment_ru=comments.get(UUID(str(leg.assignment_id))),
            response_status=leg.response_status,
            responder=leg.responder,
            bound_user_id=None if leg.bound_user_id is None else UUID(str(leg.bound_user_id)),
            status_history=history.get(UUID(str(leg.assignment_id)), ()),
            card_issues=issues.get(UUID(str(leg.assignment_id)), ()),
        )
        for leg in ordered
    )


def dds_participant_totals(
    participants: Sequence[DdsParticipant],
    legs: Sequence[DDSAssignment],
    events: Sequence[SessionEvent],
) -> tuple[DdsParticipantTotals, ...]:
    """One `DdsParticipantTotals` per ДДС participant, in `participants` order (I3 E5b).

    Pure over the legs and the log. A status counts for the participant who authored it
    (`DDS_SERVICE_STATUS_SET.actor_user_id`, TRAINEE source) — scripted, system and picker-mirror
    steps count for nobody.
    """
    leg_ids = {UUID(str(leg.assignment_id)) for leg in legs}
    authored: dict[UUID, list[str]] = {}
    flagged: dict[UUID, int] = {}
    for event in events:
        if _uuid(event.payload.get("assignment_id")) not in leg_ids:
            continue
        actor = _uuid(event.payload.get("actor_user_id"))
        if actor is None:
            continue
        if (
            event.event_type is EventType.DDS_SERVICE_STATUS_SET
            and event.payload.get("source") == StatusSource.TRAINEE.value
        ):
            authored.setdefault(actor, []).append(str(event.payload.get("new_status")))
        elif event.event_type is EventType.DDS_CARD_ISSUE_FLAGGED:
            flagged[actor] = flagged.get(actor, 0) + 1
    return tuple(
        DdsParticipantTotals(
            user_id=participant.user_id,
            display_name_ru=participant.display_name_ru,
            assigned_service_id=participant.assigned_service_id,
            legs=sum(1 for leg in legs if _plays(leg, participant.user_id)),
            status_entries=len(authored.get(participant.user_id, ())),
            accepted=authored.get(participant.user_id, []).count(_S.ACCEPTED.value),
            not_accepted=authored.get(participant.user_id, []).count(_S.NOT_ACCEPTED.value),
            refused=authored.get(participant.user_id, []).count(_S.REFUSED.value),
            completed=authored.get(participant.user_id, []).count(_S.COMPLETED.value),
            card_issues=flagged.get(participant.user_id, 0),
        )
        for participant in participants
    )


def _plays(leg: DDSAssignment, user_id: UUID) -> bool:
    if leg.responder is LegResponder.SCRIPTED:
        return False
    return leg.bound_user_id is None or UUID(str(leg.bound_user_id)) == user_id


def _status_history_by_assignment(
    events: Sequence[SessionEvent],
    display_names: Mapping[UUID, str],
    service_names: Mapping[str, str],
) -> Mapping[UUID, tuple[ServiceStatusEntryView, ...]]:
    grouped: dict[UUID, list[ServiceStatusEntryView]] = {}
    for event in events:
        if event.event_type is not EventType.DDS_SERVICE_STATUS_SET:
            continue
        payload = event.payload
        assignment_id = _uuid(payload.get("assignment_id"))
        if assignment_id is None:
            continue
        source = StatusSource(str(payload["source"]))
        actor = _uuid(payload.get("actor_user_id"))
        service = str(payload.get("service_type") or "")
        if source is StatusSource.SCRIPTED_RESPONDER:
            author = service_names.get(service, service)
        elif actor is not None and actor in display_names:
            author = display_names[actor]
        else:
            author = _SYSTEM_DISPLAY_RU
        grouped.setdefault(assignment_id, []).append(
            ServiceStatusEntryView(
                event_id=UUID(str(event.id)),
                previous_status=ServiceResponseStatus(str(payload["previous_status"])),
                new_status=ServiceResponseStatus(str(payload["new_status"])),
                order_number=_optional_str(payload.get("order_number")),
                comment_ru=_optional_str(payload.get("comment_ru")),
                completion_reason=_optional_str(payload.get("completion_reason")),
                source=source,
                actor_user_id=actor,
                actor_display_ru=author,
                at_offset_ms=int(payload.get("at_offset_ms", event.monotonic_offset_ms)),
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _card_issues_by_assignment(
    events: Sequence[SessionEvent],
) -> Mapping[UUID, tuple[CardIssueView, ...]]:
    grouped: dict[UUID, list[CardIssueView]] = {}
    for event in events:
        if event.event_type is not EventType.DDS_CARD_ISSUE_FLAGGED:
            continue
        payload = event.payload
        assignment_id = _uuid(payload.get("assignment_id"))
        if assignment_id is None:
            continue
        grouped.setdefault(assignment_id, []).append(
            CardIssueView(
                event_id=UUID(str(event.id)),
                assignment_id=assignment_id,
                field_path=_optional_str(payload.get("field_path")),
                issue_kind=CardIssueKind(str(payload["issue_kind"])),
                comment_ru=str(payload.get("comment_ru") or ""),
                at_offset_ms=int(payload.get("at_offset_ms", event.monotonic_offset_ms)),
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


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
                note_ru=_optional_str(event.payload.get("note_ru")),
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _closure_comments_by_assignment(events: Sequence[SessionEvent]) -> Mapping[UUID, str]:
    """ADDITIVE (E20-E R11): `assignment_id -> DDS_INCIDENT_CLOSED.comment_ru`, one entry per leg
    that was closed with a non-empty comment — the same fold shape `_dispatch_events_by_assignment`
    / `_status_updates_by_assignment` use over the same event log."""
    comments: dict[UUID, str] = {}
    for event in events:
        if event.event_type is not EventType.DDS_INCIDENT_CLOSED:
            continue
        assignment_id = _uuid(event.payload.get("assignment_id"))
        comment = _optional_str(event.payload.get("comment_ru"))
        if assignment_id is not None and comment is not None:
            comments[assignment_id] = comment
    return comments


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


def _optional_str(value: object) -> str | None:
    """A non-empty `str` payload value, or `None` — `"" | null | absent` all read as "not given"
    (matches `openapi.yaml`'s `note_ru`/`comment_ru`: `[string, 'null']`, never an empty string)."""
    if isinstance(value, str) and value != "":
        return value
    return None


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
