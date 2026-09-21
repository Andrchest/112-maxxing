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

from app.db.models.dds import DDSAssignment as DDSAssignmentRow
from app.domain.common.ids import RoleStageId
from app.domain.dds.assignment import DDSAssignment
from app.infrastructure.persistence.mappers import (
    dds_assignment_from_row,
    dds_assignment_row_values,
)

__all__ = ["SqlAlchemyDDSAssignmentRepository"]

_ASSIGNMENTS = DDSAssignmentRow.__table__


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
        await self._session.execute(
            sa.update(_ASSIGNMENTS)
            .where(_ASSIGNMENTS.c.id == UUID(str(assignment.assignment_id)))
            .values(**values)
        )
