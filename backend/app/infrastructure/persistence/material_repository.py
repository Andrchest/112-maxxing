"""`SqlAlchemyMaterialRepository` — `training_materials` (HLD 20 §20.12, I4 E34, migration
`0018_training_materials`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.material_repository import StoredMaterial
from app.db.models.materials import TrainingMaterial as MaterialRow
from app.domain.common.ids import MaterialId, UserId

__all__ = ["SqlAlchemyMaterialRepository"]

_MATERIALS = MaterialRow.__table__


class SqlAlchemyMaterialRepository:
    """`MaterialRepository` over PostgreSQL, bound to one `AsyncSession` (one transaction)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, material: StoredMaterial) -> None:
        await self._session.execute(
            sa.insert(_MATERIALS).values(
                id=UUID(str(material.material_id)),
                title_ru=material.title_ru,
                file_name=material.file_name,
                content_type=material.content_type,
                size_bytes=material.size_bytes,
                sha256=material.sha256,
                uploaded_by=UUID(str(material.uploaded_by_user_id)),
                created_at=material.created_at,
                archived_at=material.archived_at,
            )
        )

    async def get(self, material_id: MaterialId) -> StoredMaterial | None:
        result = await self._session.execute(
            sa.select(_MATERIALS).where(_MATERIALS.c.id == UUID(str(material_id)))
        )
        row = result.one_or_none()
        return None if row is None else _stored(row)

    async def list_materials(self, *, include_archived: bool) -> list[StoredMaterial]:
        query = sa.select(_MATERIALS)
        if not include_archived:
            query = query.where(_MATERIALS.c.archived_at.is_(None))
        query = query.order_by(_MATERIALS.c.created_at.desc(), _MATERIALS.c.id.desc())
        result = await self._session.execute(query)
        return [_stored(row) for row in result.all()]

    async def archive(
        self, material_id: MaterialId, *, archived_at: datetime
    ) -> StoredMaterial | None:
        existing = await self.get(material_id)
        if existing is None:
            return None
        if existing.archived_at is not None:
            return existing  # idempotent: the first archive time wins
        await self._session.execute(
            sa.update(_MATERIALS)
            .where(_MATERIALS.c.id == UUID(str(material_id)))
            .values(archived_at=archived_at)
        )
        return await self.get(material_id)


def _stored(row: sa.Row[tuple[object, ...]]) -> StoredMaterial:
    mapping = row._mapping
    return StoredMaterial(
        material_id=MaterialId(UUID(str(mapping["id"]))),
        title_ru=str(mapping["title_ru"]),
        file_name=str(mapping["file_name"]),
        content_type=str(mapping["content_type"]),
        size_bytes=int(mapping["size_bytes"]),
        sha256=str(mapping["sha256"]),
        uploaded_by_user_id=UserId(UUID(str(mapping["uploaded_by"]))),
        created_at=mapping["created_at"],
        archived_at=mapping["archived_at"],
    )
