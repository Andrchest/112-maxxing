"""`SqlAlchemyHandoffRepository` over `handoff_snapshots` (§20.4, D3, SPEC §10).

One layer, one module, one table, one class holding exactly one `Table`. There is no shared base
class and no generic "layer" adapter, because a shared access path is precisely what D3 forbids.
The isolation is structural rather than a matter of discipline: this module's imports name the
handoff layer and nothing else, so the DDS side — which reads the snapshot by value — has no
import path at all to the engine-written layers.

ORM rows never leave this module: every conversion goes through
`app.infrastructure.persistence.mappers` (D2).

`backend/tests/unit/application/sessions/test_layer_repository_isolation.py` scans this module's
imports and fails if any of them names a layer this one may not see.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.layers import HandoffSnapshot as HandoffSnapshotRow
from app.domain.common.ids import SnapshotId
from app.domain.layers.handoff import HandoffSnapshot
from app.infrastructure.persistence.mappers import (
    handoff_snapshot_from_row,
    handoff_snapshot_row_values,
)

__all__ = ["SqlAlchemyHandoffRepository"]

_SNAPSHOTS = HandoffSnapshotRow.__table__


class SqlAlchemyHandoffRepository:
    """`HandoffRepository` over `handoff_snapshots` (§20.4, D3, SPEC §10).

    The row is immutable at rest (§20.9 trigger), so `save` refuses rather than issuing an UPDATE
    the database would reject anyway.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, snapshot_id: SnapshotId) -> HandoffSnapshot | None:
        result = await self._session.execute(
            sa.select(_SNAPSHOTS).where(_SNAPSHOTS.c.id == UUID(str(snapshot_id)))
        )
        row = result.one_or_none()
        return None if row is None else handoff_snapshot_from_row(row._mapping)

    async def add(self, snapshot: HandoffSnapshot) -> None:
        await self._session.execute(
            sa.insert(_SNAPSHOTS).values(**handoff_snapshot_row_values(snapshot))
        )

    async def save(self, snapshot: HandoffSnapshot) -> None:
        """A handoff snapshot is immutable (§20.4, §20.9): there is nothing legal to write."""
        raise NotImplementedError(
            f"handoff snapshot {snapshot.snapshot_id} is immutable (§20.9); create a new "
            "snapshot instead of saving over one"
        )
