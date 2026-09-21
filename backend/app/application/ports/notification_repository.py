"""`NotificationRepository` port — the `notifications` table (§20.5 additive, §10.7, D3, D5).

`notifications` is a **materialized projection of the event log**, exactly as `dds_assignments`
is: the world engine emits `NOTIFICATION_CREATED` as part of a tick, and the tick's own Unit of
Work writes the row in the same transaction (`app.application.simulation.tick_session`), so the
log and the table can never disagree. `acknowledgeNotification` writes the acknowledgement back
and emits `NOTIFICATION_ACKNOWLEDGED` in one transaction for the same reason.

`StoredNotification` is an application model rather than a domain type. §10.7 sketches a
`domain/dds/notification.py`, but the record has no behaviour, no invariant and no state machine —
it is a row the engine wrote and a trainee ticked off — and every consumer (the list endpoint, the
`DdsStageView` badge count, the report timeline) wants exactly these nine columns. See this task's
report under "HLD gaps".

Like `DDSAssignmentRepository`, this port is safe to hand to a DDS service because of what it does
**not** name: there is no `WorldTruth`, no `CallerBelief` and no `OperatorCard` in its imports or
its signatures (SPEC §42 test 3, D3).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import IncidentId, UserId
from app.domain.enums import NotificationSeverity, RoleType

__all__ = ["NotificationRepository", "StoredNotification"]


class StoredNotification(BaseModel):
    """One `notifications` row — §10.7's `Notification`, plus who acknowledged it (§20.5)."""

    model_config = ConfigDict(frozen=True)

    notification_id: UUID
    incident_id: IncidentId
    audience_role: RoleType
    severity: NotificationSeverity
    title_ru: str
    body_ru: str
    source_world_event_id: str | None = None
    created_at_offset_ms: int
    acknowledged_at_offset_ms: int | None = None
    acknowledged_by_user_id: UserId | None = None


@runtime_checkable
class NotificationRepository(Protocol):
    """`notifications` — materialized from `NOTIFICATION_CREATED` / `NOTIFICATION_ACKNOWLEDGED`."""

    async def add_all(self, notifications: Sequence[StoredNotification]) -> None:
        """Insert the notifications one tick created, in emission order.

        Idempotent by primary key: `NOTIFICATION_CREATED.notification_id` is derived
        deterministically from the world event (`world/apply.py`), so replaying a tick that was
        already folded must not duplicate a row. An implementation therefore inserts with
        "do nothing on conflict".
        """
        ...

    async def list_for_incident(
        self, incident_id: IncidentId, *, audience_role: RoleType, unacknowledged_only: bool = False
    ) -> list[StoredNotification]:
        """This role's notifications, newest first (`listNotifications`).

        The filter is the contract's: "`audience_role == the caller's role`; the operator console
        calls the same endpoint". It is applied in SQL, not after the read, so a role never even
        loads another role's rows.
        """
        ...

    async def get(self, notification_id: UUID) -> StoredNotification | None:
        """One row by id, or `None` — `404 NOT_FOUND` for the acknowledging command."""
        ...

    async def acknowledge(
        self, notification_id: UUID, *, at_offset_ms: int, user_id: UserId
    ) -> bool:
        """Stamp the acknowledgement; `False` when the row was already acknowledged.

        The `WHERE acknowledged_at_offset_ms IS NULL` is part of the statement rather than a
        read-then-write, so two concurrent acknowledgements of one notification produce exactly
        one `NOTIFICATION_ACKNOWLEDGED` and one `409` (`openapi.yaml`).
        """
        ...

    async def unacknowledged_count(
        self, incident_id: IncidentId, *, audience_role: RoleType
    ) -> int:
        """`DdsStageView.unacknowledged_notification_count` for this role."""
        ...
