"""`materials` schemas (`i4-openapi-delta.yaml`, HLD 71 §71.11, I4 E34).

`TrainingMaterialViewSchema`'s property names are copied literally from `TrainingMaterialView`.
`listMaterials` answers `{"items": [...]}` with no `total` (the delta's own inline schema — not
`app.api.schemas.common.PageSchema`, which always carries one).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.api.schemas.common import ApiModel
from app.application.ports.material_repository import StoredMaterial

__all__ = ["MaterialListSchema", "TrainingMaterialViewSchema", "training_material_view_schema"]


class TrainingMaterialViewSchema(ApiModel):
    """`TrainingMaterialView`."""

    material_id: UUID
    title_ru: str
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by_user_id: UUID
    created_at: datetime
    archived_at: datetime | None


class MaterialListSchema(ApiModel):
    """`listMaterials`'s `200` body — `items` only, no `total` (the delta's own inline schema)."""

    items: list[TrainingMaterialViewSchema]


def training_material_view_schema(material: StoredMaterial) -> TrainingMaterialViewSchema:
    return TrainingMaterialViewSchema(
        material_id=UUID(str(material.material_id)),
        title_ru=material.title_ru,
        file_name=material.file_name,
        content_type=material.content_type,
        size_bytes=material.size_bytes,
        sha256=material.sha256,
        uploaded_by_user_id=UUID(str(material.uploaded_by_user_id)),
        created_at=material.created_at,
        archived_at=material.archived_at,
    )
