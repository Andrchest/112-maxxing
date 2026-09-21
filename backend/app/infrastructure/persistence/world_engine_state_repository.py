"""`SqlAlchemyWorldEngineStateRepository` over `world_engine_states` (additive, E6; D3, D7).

One row per incident, holding the world event engine's bookkeeping — and nothing that is a *fact*
about the world or the caller, which is what keeps D3's "four layers, four storage locations"
intact while the engine still has a transactional home for its counters.

ORM rows never leave this module: every conversion goes through
`app.infrastructure.persistence.mappers` (D2).
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.world_engine_state_repository import WorldEngineState
from app.db.models.session import WorldEngineState as WorldEngineStateRow
from app.domain.common.ids import IncidentId
from app.infrastructure.persistence.mappers import (
    world_engine_state_from_row,
    world_engine_state_row_values,
)

__all__ = ["SqlAlchemyWorldEngineStateRepository"]

_ENGINE_STATES = WorldEngineStateRow.__table__


class SqlAlchemyWorldEngineStateRepository:
    """`WorldEngineStateRepository` over `world_engine_states` (E6)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, incident_id: IncidentId) -> WorldEngineState | None:
        result = await self._session.execute(
            sa.select(_ENGINE_STATES).where(_ENGINE_STATES.c.incident_id == UUID(str(incident_id)))
        )
        row = result.one_or_none()
        return None if row is None else world_engine_state_from_row(row._mapping)

    async def add(self, state: WorldEngineState) -> None:
        await self._session.execute(
            sa.insert(_ENGINE_STATES).values(**world_engine_state_row_values(state))
        )

    async def save(self, state: WorldEngineState) -> None:
        values = world_engine_state_row_values(state)
        await self._session.execute(
            sa.update(_ENGINE_STATES)
            .where(_ENGINE_STATES.c.incident_id == values["incident_id"])
            .values(
                last_tick_ms=values["last_tick_ms"],
                last_folded_seq_no=values["last_folded_seq_no"],
                bookkeeping=values["bookkeeping"],
                updated_at=sa.func.now(),
            )
        )
