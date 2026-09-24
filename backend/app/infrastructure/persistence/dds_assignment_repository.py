"""`SqlAlchemyDDSAssignmentRepository` over `dds_assignments` (§20.5, §10.7, D3).

One table, one class holding exactly one `Table`, and — as with the four layer adapters — the
isolation is structural: this module's imports name the DDS assignment and nothing else, so no
holder of it gains a path to `WorldTruth`, `CallerBelief` or the live `OperatorCard`
(SPEC §42 test 3). ORM rows never leave this module; every conversion goes through
`app.infrastructure.persistence.mappers` (D2).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.dds_assignment_repository import StatusHistoryEntry
from app.db.models.dds import DDSAssignment as DDSAssignmentRow
from app.db.models.dds import DDSServiceStatusHistory as HistoryRow
from app.domain.common.ids import AssignmentId, RoleStageId, SessionId
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.response import ServiceResponseStatus, StatusSource
from app.domain.enums import ActorType
from app.infrastructure.persistence.mappers import (
    dds_assignment_from_row,
    dds_assignment_row_values,
)

__all__ = ["SqlAlchemyDDSAssignmentRepository"]

_ASSIGNMENTS = DDSAssignmentRow.__table__
_HISTORY = HistoryRow.__table__


class SqlAlchemyDDSAssignmentRepository:
    """`DDSAssignmentRepository` over `dds_assignments` (§20.5)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, assignments: Sequence[DDSAssignment]) -> None:
        """Insert the whole fan-out of one handoff in one statement."""
        if not assignments:
            return
        await self._session.execute(
            sa.insert(_ASSIGNMENTS),
            [dds_assignment_row_values(assignment) for assignment in assignments],
        )

    async def list_for_stage(self, role_stage_id: RoleStageId) -> list[DDSAssignment]:
        """Every leg of one DDS `RoleStage`, oldest first and then by id for a stable order."""
        result = await self._session.execute(
            sa.select(_ASSIGNMENTS)
            .where(_ASSIGNMENTS.c.role_stage_id == UUID(str(role_stage_id)))
            .order_by(_ASSIGNMENTS.c.received_at_offset_ms, _ASSIGNMENTS.c.id)
        )
        return [dds_assignment_from_row(row._mapping) for row in result.all()]

    async def save(self, assignment: DDSAssignment) -> None:
        """Write one leg back. The identity columns are never part of the update."""
        values = dds_assignment_row_values(assignment)
        for immutable in ("id", "incident_id", "role_stage_id", "snapshot_id", "service_type"):
            values.pop(immutable)
        # The event store's card-status flush owns `accept_missed` (sticky): a command's copy of
        # the leg may predate it, so writing it back could only ever clear it.
        values.pop("accept_missed")
        await self._session.execute(
            sa.update(_ASSIGNMENTS)
            .where(_ASSIGNMENTS.c.id == UUID(str(assignment.assignment_id)))
            .values(**values)
        )

    async def add_history(self, entries: Sequence[StatusHistoryEntry]) -> None:
        """Append the `dds_service_status_history` rows of this Unit of Work's status events."""
        if not entries:
            return
        await self._session.execute(
            sa.insert(_HISTORY),
            [
                {
                    "session_id": UUID(str(entry.session_id)),
                    "assignment_id": UUID(str(entry.assignment_id)),
                    "event_id": entry.event_id,
                    "seq_no": entry.seq_no,
                    "previous_status": entry.previous_status.value,
                    "new_status": entry.new_status.value,
                    "order_number": entry.order_number,
                    "comment_ru": entry.comment_ru,
                    "completion_reason": entry.completion_reason,
                    "source": entry.source.value,
                    "actor_type": entry.actor_type.value,
                    "actor_user_id": entry.actor_user_id,
                    "at_offset_ms": entry.at_offset_ms,
                }
                for entry in entries
            ],
        )

    async def list_history(
        self, assignment_ids: Sequence[AssignmentId]
    ) -> list[StatusHistoryEntry]:
        """Every history row of these legs, oldest first (`seq_no`)."""
        if not assignment_ids:
            return []
        result = await self._session.execute(
            sa.select(_HISTORY)
            .where(_HISTORY.c.assignment_id.in_([UUID(str(item)) for item in assignment_ids]))
            .order_by(_HISTORY.c.seq_no)
        )
        return [
            StatusHistoryEntry(
                session_id=SessionId(row.session_id),
                assignment_id=AssignmentId(row.assignment_id),
                event_id=row.event_id,
                seq_no=int(row.seq_no),
                previous_status=ServiceResponseStatus(row.previous_status),
                new_status=ServiceResponseStatus(row.new_status),
                order_number=row.order_number,
                comment_ru=row.comment_ru,
                completion_reason=row.completion_reason,
                source=StatusSource(row.source),
                actor_type=ActorType(row.actor_type),
                actor_user_id=row.actor_user_id,
                at_offset_ms=int(row.at_offset_ms),
            )
            for row in result.all()
        ]
