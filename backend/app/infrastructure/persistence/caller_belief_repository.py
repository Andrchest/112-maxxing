"""`SqlAlchemyCallerBeliefRepository` over `incident_caller_beliefs` (§20.4, D3).

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

from app.db.models.layers import IncidentCallerBelief as CallerBeliefRow
from app.domain.common.ids import IncidentId
from app.domain.layers.caller_belief import CallerBelief
from app.infrastructure.persistence.mappers import caller_belief_from_row, caller_belief_row_values

__all__ = ["SqlAlchemyCallerBeliefRepository"]

_CALLER_BELIEFS = CallerBeliefRow.__table__


class SqlAlchemyCallerBeliefRepository:
    """`CallerBeliefRepository` over `incident_caller_beliefs` (§20.4, D3)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, incident_id: IncidentId) -> CallerBelief | None:
        result = await self._session.execute(
            sa.select(_CALLER_BELIEFS).where(
                _CALLER_BELIEFS.c.incident_id == UUID(str(incident_id))
            )
        )
        row = result.one_or_none()
        return None if row is None else caller_belief_from_row(row._mapping)

    async def add(self, caller_belief: CallerBelief) -> None:
        await self._session.execute(
            sa.insert(_CALLER_BELIEFS).values(**caller_belief_row_values(caller_belief))
        )

    async def save(self, caller_belief: CallerBelief) -> None:
        values = caller_belief_row_values(caller_belief)
        await self._session.execute(
            sa.update(_CALLER_BELIEFS)
            .where(_CALLER_BELIEFS.c.incident_id == values["incident_id"])
            .values(
                revision=values["revision"],
                facts=values["facts"],
                knowledge=values["knowledge"],
                certainty=values["certainty"],
                emotion=values["emotion"],
                revealed_fact_ids=values["revealed_fact_ids"],
                updated_at=sa.func.now(),
            )
        )
