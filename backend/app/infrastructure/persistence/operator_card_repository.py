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
from app.db.models.layers import IncidentCardRevision as IncidentCardRevisionRow
from app.domain.common.ids import CardId, IncidentId
from app.domain.enums import ValueType
from app.domain.layers.operator_card import CardRevision, OperatorCard
from app.infrastructure.persistence.mappers import (
    card_revision_from_row,
    card_revision_row_values,
    operator_card_from_row,
    operator_card_row_values,
)

__all__ = ["SqlAlchemyOperatorCardRepository"]

_CARDS = IncidentCardRow.__table__
_REVISIONS = IncidentCardRevisionRow.__table__


class SqlAlchemyOperatorCardRepository:
    """`OperatorCardRepository` over `incident_cards` + `incident_card_revisions` (§20.4, SPEC §9).

    The revision table is append-only: this class has `add_revision` and `list_revisions` and no
    update or delete, because the §20.9 `incident_card_revisions_append_only` trigger rejects both
    at the database. `uq_card_revisions_card_no (card_id, revision_no)` is what makes two
    concurrent writers of one card collide rather than silently interleave — the session row lock
    of §20.8 taken by the command pipeline serialises them before it can happen.
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

    async def add_revision(self, revision: CardRevision, value_type: ValueType) -> None:
        await self._session.execute(
            sa.insert(_REVISIONS).values(**card_revision_row_values(revision, value_type))
        )

    async def list_revisions(
        self,
        card_id: CardId,
        *,
        field_path: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[CardRevision], int]:
        card_uuid = UUID(str(card_id))
        condition = _REVISIONS.c.card_id == card_uuid
        if field_path is not None:
            condition = sa.and_(condition, _REVISIONS.c.field_path == field_path)

        total = await self._session.scalar(
            sa.select(sa.func.count()).select_from(_REVISIONS).where(condition)
        )
        result = await self._session.execute(
            sa.select(_REVISIONS)
            .where(condition)
            .order_by(_REVISIONS.c.revision_no.asc())
            .limit(limit)
            .offset(offset)
        )
        rows = [card_revision_from_row(row._mapping) for row in result.all()]
        return rows, int(total or 0)
