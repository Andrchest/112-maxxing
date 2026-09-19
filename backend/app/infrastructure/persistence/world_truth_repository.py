"""`SqlAlchemyWorldTruthRepository` over `incident_world_states` (§20.4, D3).

One layer, one module, one table, one class holding exactly one `Table`. There is no shared base
class and no generic "layer" adapter, because a shared access path is precisely what D3 forbids —
and the separation is structural: the card and handoff adapters live in their own modules and
import nothing from this one.

ORM rows never leave this module: every conversion goes through
`app.infrastructure.persistence.mappers` (D2).
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.layers import IncidentWorldState as WorldStateRow
from app.domain.common.ids import IncidentId
from app.domain.layers.world_truth import WorldTruth
from app.infrastructure.persistence.mappers import world_truth_from_row, world_truth_row_values

__all__ = ["SqlAlchemyWorldTruthRepository"]

_WORLD_STATES = WorldStateRow.__table__


class SqlAlchemyWorldTruthRepository:
    """`WorldTruthRepository` over `incident_world_states` (§20.4, D3)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, incident_id: IncidentId) -> WorldTruth | None:
        result = await self._session.execute(
            sa.select(_WORLD_STATES).where(_WORLD_STATES.c.incident_id == UUID(str(incident_id)))
        )
        row = result.one_or_none()
        return None if row is None else world_truth_from_row(row._mapping)

    async def add(self, world_truth: WorldTruth) -> None:
        await self._session.execute(
            sa.insert(_WORLD_STATES).values(**world_truth_row_values(world_truth))
        )

    async def save(self, world_truth: WorldTruth) -> None:
        values = world_truth_row_values(world_truth)
        await self._session.execute(
            sa.update(_WORLD_STATES)
            .where(_WORLD_STATES.c.incident_id == values["incident_id"])
            .values(
                revision=values["revision"],
                facts=values["facts"],
                value_types=values["value_types"],
                updated_at=sa.func.now(),
            )
        )
