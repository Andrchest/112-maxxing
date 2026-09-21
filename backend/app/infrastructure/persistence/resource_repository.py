"""`SqlAlchemyResourceRepository` over `emergency_resources` + `resource_state_changes` (§20.5).

Per-session resource instances and their append-only audit trail. ORM rows never leave this module:
every conversion goes through `app.infrastructure.persistence.mappers` (D2).

`save` writes only the three columns the simulation engine owns — `current_status`, `eta`,
`status_changed_at_offset_ms` — and never `assignment_id`, which belongs to the DDS selection use
case and has its own statement (`attach`); a resource the engine moved and a resource a trainee
assigned are therefore two non-overlapping writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.resource_repository import (
    DispatchRecord,
    ResourceStateChange,
    StoredResource,
)
from app.db.models.dds import EmergencyResource as ResourceRow
from app.db.models.dds import ResourceStateChange as ResourceStateChangeRow
from app.domain.common.ids import AssignmentId, ResourceId, SessionId
from app.domain.dds.resources import EmergencyResource
from app.infrastructure.persistence.mappers import (
    emergency_resource_from_row,
    emergency_resource_row_values,
    resource_state_change_row_values,
)

__all__ = ["SqlAlchemyResourceRepository"]

_RESOURCES = ResourceRow.__table__
_STATE_CHANGES = ResourceStateChangeRow.__table__


class SqlAlchemyResourceRepository:
    """`ResourceRepository` over PostgreSQL, bound to one `AsyncSession` (one transaction)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, session_id: SessionId, resources: Sequence[StoredResource]) -> None:
        """Insert the whole board in one statement; an empty board inserts nothing."""
        if not resources:
            return
        await self._session.execute(
            sa.insert(_RESOURCES),
            [emergency_resource_row_values(session_id, stored) for stored in resources],
        )

    async def list_for_session(self, session_id: SessionId) -> list[StoredResource]:
        """Every resource of the session, ordered by `scenario_resource_id` (a stable order)."""
        result = await self._session.execute(
            sa.select(_RESOURCES)
            .where(_RESOURCES.c.session_id == UUID(str(session_id)))
            .order_by(_RESOURCES.c.scenario_resource_id)
        )
        return [emergency_resource_from_row(row._mapping) for row in result.all()]

    async def save(self, session_id: SessionId, resource: EmergencyResource) -> None:
        """Write back the three columns the engine owns."""
        await self._session.execute(
            sa.update(_RESOURCES)
            .where(
                _RESOURCES.c.id == UUID(str(resource.resource_id)),
                _RESOURCES.c.session_id == UUID(str(session_id)),
            )
            .values(
                current_status=resource.current_status.value,
                eta=resource.eta.model_dump(mode="json"),
                status_changed_at_offset_ms=resource.status_changed_at_offset_ms,
            )
        )

    async def attach(
        self,
        session_id: SessionId,
        resource_id: ResourceId,
        assignment_id: AssignmentId | None,
    ) -> None:
        """Write `assignment_id` alone — the one column the DDS selection use case owns (§20.5)."""
        await self._session.execute(
            sa.update(_RESOURCES)
            .where(
                _RESOURCES.c.id == UUID(str(resource_id)),
                _RESOURCES.c.session_id == UUID(str(session_id)),
            )
            .values(
                assignment_id=(None if assignment_id is None else UUID(str(assignment_id))),
            )
        )

    async def record_state_change(self, change: ResourceStateChange) -> None:
        """Append one `resource_state_changes` row (§20.5, SPEC §29)."""
        await self._session.execute(
            sa.insert(_STATE_CHANGES).values(**resource_state_change_row_values(change))
        )

    async def dispatch_history(self, session_id: SessionId) -> list[DispatchRecord]:
        """Every `trigger = 'dispatch'` row of this session's board, oldest first (§20.5).

        Joined to `emergency_resources` because `resource_state_changes` has no `session_id` of
        its own; rows whose `assignment_id` was nulled by the FK's `SET NULL` are skipped, since
        a leg that no longer exists has no history to report.
        """
        result = await self._session.execute(
            sa.select(
                _STATE_CHANGES.c.assignment_id,
                _STATE_CHANGES.c.resource_id,
                _STATE_CHANGES.c.at_offset_ms,
            )
            .join(_RESOURCES, _RESOURCES.c.id == _STATE_CHANGES.c.resource_id)
            .where(
                _RESOURCES.c.session_id == UUID(str(session_id)),
                _STATE_CHANGES.c.trigger == "dispatch",
                _STATE_CHANGES.c.assignment_id.is_not(None),
            )
            .order_by(_STATE_CHANGES.c.at_offset_ms, _STATE_CHANGES.c.id)
        )
        return [
            DispatchRecord(
                assignment_id=AssignmentId(UUID(str(row.assignment_id))),
                resource_id=ResourceId(UUID(str(row.resource_id))),
                at_offset_ms=int(row.at_offset_ms),
            )
            for row in result.all()
        ]
