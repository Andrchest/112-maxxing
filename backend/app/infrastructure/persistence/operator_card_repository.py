"""`SqlAlchemyOperatorCardRepository` over `incident_cards` (§20.4, D3, SPEC §9).

One layer, one module, one table, one class holding exactly one `Table`. There is no shared base
class and no generic "layer" adapter, because a shared access path is precisely what D3 forbids.
The isolation is structural rather than a matter of discipline: this module's imports name the
card layer and nothing else, so nothing reachable from here reaches the engine-written layers.

ORM rows never leave this module: every conversion goes through
`app.infrastructure.persistence.mappers` (D2).

`backend/tests/unit/application/sessions/test_layer_repository_isolation.py` scans this module's
imports and fails if any of them names a layer this one may not see.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.layers import IncidentCard as IncidentCardRow
from app.domain.common.ids import IncidentId
from app.domain.layers.operator_card import OperatorCard
from app.infrastructure.persistence.mappers import operator_card_from_row, operator_card_row_values

__all__ = ["SqlAlchemyOperatorCardRepository"]

_CARDS = IncidentCardRow.__table__


class SqlAlchemyOperatorCardRepository:
    """`OperatorCardRepository` over `incident_cards` (§20.4, D3, SPEC §9).

    `incident_card_revisions` is written by the card-editing use case — TODO(E7).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, incident_id: IncidentId) -> OperatorCard | None:
        result = await self._session.execute(
            sa.select(_CARDS).where(_CARDS.c.incident_id == UUID(str(incident_id)))
        )
        row = result.one_or_none()
        return None if row is None else operator_card_from_row(row._mapping)

    async def add(self, card: OperatorCard) -> None:
        await self._session.execute(sa.insert(_CARDS).values(**operator_card_row_values(card)))

    async def save(self, card: OperatorCard) -> None:
        values = operator_card_row_values(card)
        await self._session.execute(
            sa.update(_CARDS)
            .where(_CARDS.c.id == values["id"])
            .values(
                values=values["values"],
                revision_counter=values["revision_counter"],
                updated_at=sa.func.now(),
            )
        )
