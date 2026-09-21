"""`SqlAlchemyNotificationRepository` over `notifications` (§20.5 additive, §10.7, D3, D5).

One table, one class holding exactly one `Table`, and — as with the DDS assignment adapter — the
isolation is structural: this module's imports name the notification and nothing else, so no
holder of it gains a path to `WorldTruth`, `CallerBelief` or the live `OperatorCard` (SPEC §42
test 3). ORM rows never leave this module; every conversion goes through
`app.infrastructure.persistence.mappers` (D2).

Two statements carry the whole design:

* `add_all` inserts `ON CONFLICT (id) DO NOTHING`. `NOTIFICATION_CREATED.notification_id` is
  derived deterministically from the world event that produced it (`world/apply.py`), so a tick
  re-examining a check it already folded must not create a second row for the same notification;
* `acknowledge` is a single conditional `UPDATE … WHERE acknowledged_at_offset_ms IS NULL` and
  reports whether it hit a row. That is what makes a second acknowledgement `409` rather than a
  silent overwrite, without a read-then-write that two commands could interleave inside.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.notification_repository import StoredNotification
from app.db.models.dds import Notification as NotificationRow
from app.domain.common.ids import IncidentId, UserId
from app.domain.enums import RoleType
from app.infrastructure.persistence.mappers import notification_from_row, notification_row_values

__all__ = ["SqlAlchemyNotificationRepository"]

_NOTIFICATIONS = NotificationRow.__table__


class SqlAlchemyNotificationRepository:
    """`NotificationRepository` over PostgreSQL, bound to one `AsyncSession` (one transaction)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, notifications: Sequence[StoredNotification]) -> None:
        """Insert the notifications of one tick; an id already present is left alone."""
        if not notifications:
            return
        statement = pg_insert(_NOTIFICATIONS).on_conflict_do_nothing(index_elements=["id"])
        await self._session.execute(
            statement,
            [notification_row_values(notification) for notification in notifications],
        )

    async def list_for_incident(
        self, incident_id: IncidentId, *, audience_role: RoleType, unacknowledged_only: bool = False
    ) -> list[StoredNotification]:
        """This role's notifications, newest first (`listNotifications`)."""
        statement = sa.select(_NOTIFICATIONS).where(
            _NOTIFICATIONS.c.incident_id == UUID(str(incident_id)),
            _NOTIFICATIONS.c.audience_role == audience_role.value,
        )
        if unacknowledged_only:
            statement = statement.where(_NOTIFICATIONS.c.acknowledged_at_offset_ms.is_(None))
        result = await self._session.execute(
            statement.order_by(
                _NOTIFICATIONS.c.created_at_offset_ms.desc(), _NOTIFICATIONS.c.id.desc()
            )
        )
        return [notification_from_row(row._mapping) for row in result.all()]

    async def get(self, notification_id: UUID) -> StoredNotification | None:
        """One row by id, or `None`."""
        result = await self._session.execute(
            sa.select(_NOTIFICATIONS).where(_NOTIFICATIONS.c.id == notification_id)
        )
        row = result.one_or_none()
        return None if row is None else notification_from_row(row._mapping)

    async def acknowledge(
        self, notification_id: UUID, *, at_offset_ms: int, user_id: UserId
    ) -> bool:
        """Stamp the acknowledgement once; `False` when somebody already had."""
        result = await self._session.execute(
            sa.update(_NOTIFICATIONS)
            .where(
                _NOTIFICATIONS.c.id == notification_id,
                _NOTIFICATIONS.c.acknowledged_at_offset_ms.is_(None),
            )
            .values(
                acknowledged_at_offset_ms=at_offset_ms,
                acknowledged_by_user_id=UUID(str(user_id)),
            )
        )
        return bool(result.rowcount)

    async def unacknowledged_count(
        self, incident_id: IncidentId, *, audience_role: RoleType
    ) -> int:
        """`DdsStageView.unacknowledged_notification_count` for this role."""
        result = await self._session.execute(
            sa.select(sa.func.count())
            .select_from(_NOTIFICATIONS)
            .where(
                _NOTIFICATIONS.c.incident_id == UUID(str(incident_id)),
                _NOTIFICATIONS.c.audience_role == audience_role.value,
                _NOTIFICATIONS.c.acknowledged_at_offset_ms.is_(None),
            )
        )
        return int(result.scalar_one())
