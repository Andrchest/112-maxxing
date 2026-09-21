"""`SessionReport.resource_timeline` — SPEC §29 item 12: every step a unit took.

`openapi.yaml` calls a `ResourceTimelineEntryView` "one `RESOURCE_STATUS_CHANGED` step", and that
is literally the source: the event log, not `resource_state_changes`. The table is the audit copy
the DDS console reads; the log is the record (D5), and it carries `callsign` and `trigger` in the
same payload, so the projection needs one read the report already performs rather than a second
repository call whose rows would have to be re-joined to `emergency_resources` for the callsign.

The entries keep the log's own order (`seq_no`), so "SELECTED → DISPATCHED → EN_ROUTE → ON_SCENE"
reads down the page the way it happened — including the world-engine's own transitions, which are
the ones a trainee most often wants to see next to their decisions.

`previous_status` is `null` on a unit's first transition (nothing preceded it) — `openapi.yaml`
types it nullable for exactly this reason (E16-D, SPEC §27: never fabricate a status). The
projection reports whatever the payload actually carries and never invents a "previous" the log
does not hold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.domain.enums import ResourceStatus
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

__all__ = ["ResourceTimelineEntry", "resource_timeline"]


@dataclass(frozen=True, slots=True)
class ResourceTimelineEntry:
    """`openapi.yaml`'s `ResourceTimelineEntryView`."""

    resource_id: UUID
    callsign: str
    previous_status: ResourceStatus | None
    new_status: ResourceStatus
    trigger: str
    at_offset_ms: int


def resource_timeline(events: Sequence[SessionEvent]) -> tuple[ResourceTimelineEntry, ...]:
    """Every `RESOURCE_STATUS_CHANGED` of the log, in `seq_no` order."""
    entries: list[ResourceTimelineEntry] = []
    for event in sorted(events, key=lambda item: item.seq_no):
        if event.event_type is not EventType.RESOURCE_STATUS_CHANGED:
            continue
        resource_id = _uuid(event.payload.get("resource_id"))
        new_status = _status(event.payload.get("new_status"))
        if resource_id is None or new_status is None:
            continue  # pragma: no cover - §10.13 types both keys as required
        entries.append(
            ResourceTimelineEntry(
                resource_id=resource_id,
                callsign=str(event.payload.get("callsign") or ""),
                previous_status=_status(event.payload.get("previous_status")),
                new_status=new_status,
                trigger=str(event.payload.get("trigger") or ""),
                at_offset_ms=int(event.payload.get("at_offset_ms") or event.monotonic_offset_ms),
            )
        )
    return tuple(entries)


def _uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


def _status(value: object) -> ResourceStatus | None:
    if isinstance(value, ResourceStatus):
        return value
    if isinstance(value, str):
        try:
            return ResourceStatus(value)
        except ValueError:
            return None
    return None
