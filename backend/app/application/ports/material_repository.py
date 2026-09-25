"""`MaterialRepository` port — `training_materials` (HLD 71 §71.11, HLD 20 §20.12, I4 E34).

Metadata only: the bytes live under `Settings.data_dir/materials/<sha256>` and are never read or
written through this port (that is `app.application.materials.storage`, next to the use cases that
need it — the same split `app.application.recording` keeps between the WAV sink and the
`audio_segments` repository).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import MaterialId, UserId

__all__ = ["MaterialRepository", "StoredMaterial"]


class StoredMaterial(BaseModel):
    """One `training_materials` row."""

    model_config = ConfigDict(frozen=True)

    material_id: MaterialId
    title_ru: str
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by_user_id: UserId
    created_at: datetime
    archived_at: datetime | None


@runtime_checkable
class MaterialRepository(Protocol):
    """Read and write `training_materials` rows (§20.12)."""

    async def add(self, material: StoredMaterial) -> None:
        """Insert a new row. The file itself is written by the caller, before this call."""
        ...

    async def get(self, material_id: MaterialId) -> StoredMaterial | None:
        """One row, or `None`."""
        ...

    async def list_materials(self, *, include_archived: bool) -> list[StoredMaterial]:
        """Every row, newest first; `include_archived=False` excludes an archived one."""
        ...

    async def archive(
        self, material_id: MaterialId, *, archived_at: datetime
    ) -> StoredMaterial | None:
        """Set `archived_at` unless it is already set (idempotent); `None` if no such row."""
        ...
