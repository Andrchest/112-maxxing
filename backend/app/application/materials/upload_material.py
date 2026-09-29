"""`UploadMaterial` — `uploadMaterial` (INSTRUCTOR / ADMIN, HLD 71 §71.11, HLD 20 §20.12).

The bytes are written under `Settings.data_dir/materials/<sha256>`, computed over the whole body
(this task reads the upload fully into memory before hashing — acceptable for the allow-listed
document/image sizes `SIM_MATERIAL_MAX_MB` bounds; a very large deployment limit would want a
streaming hash instead, noted here rather than built). **The sha dedupe**: if that path already
exists, the file is not written a second time — the row `training_materials.sha256` is not unique
(two uploads of the same bytes under a different title are two rows over one stored file).
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256 as sha256_of
from pathlib import Path

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.materials.allowed_types import content_type_of, extension_of
from app.application.materials.errors import MaterialTooLargeError, MaterialTypeNotAllowedError
from app.application.ports.audit_changes import NO_AUDIT_CHANGES, AuditChangeCollector
from app.application.ports.clock import Clock
from app.application.ports.id_generator import IdGenerator
from app.application.ports.material_repository import StoredMaterial
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.ids import MaterialId, UserId

__all__ = ["UploadMaterial", "UploadMaterialRequest"]


@dataclass(frozen=True, slots=True)
class UploadMaterialRequest:
    """The router's own parsed `multipart/form-data` body."""

    title_ru: str
    file_name: str
    content: bytes


class UploadMaterial:
    """`uploadMaterial` (§71.11): allow-list, size limit, sha256 dedupe, insert."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        *,
        materials_dir: Path,
        max_size_bytes: int,
        changes: AuditChangeCollector = NO_AUDIT_CHANGES,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ids = ids
        self._clock = clock
        #: `Settings.data_dir / "materials"` (HLD 71 §71.11).
        self._materials_dir = materials_dir
        self._max_size_bytes = max_size_bytes
        self._changes = changes  # I7 E43

    async def __call__(
        self, request: UploadMaterialRequest, *, actor: AuthenticatedUser
    ) -> StoredMaterial:
        extension = extension_of(request.file_name)
        content_type = content_type_of(extension)
        if content_type is None:
            raise MaterialTypeNotAllowedError(request.file_name)
        size_bytes = len(request.content)
        if size_bytes > self._max_size_bytes:
            raise MaterialTooLargeError(size_bytes, self._max_size_bytes)

        digest = sha256_of(request.content).hexdigest()
        self._write_once(digest, request.content)

        material = StoredMaterial(
            material_id=MaterialId(self._ids.new()),
            title_ru=request.title_ru,
            file_name=request.file_name,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=digest,
            uploaded_by_user_id=UserId(actor.user_id),
            created_at=self._clock.now(),
            archived_at=None,
        )
        async with self._unit_of_work() as uow:
            await uow.materials.add(material)
            await uow.commit()
        for field in ("title_ru", "file_name", "content_type", "size_bytes"):
            self._changes.record("material", field, None, getattr(material, field))
        return material

    def _write_once(self, sha256_hex: str, content: bytes) -> None:
        """Write `content` to `materials_dir/<sha256_hex>` unless it is already there."""
        self._materials_dir.mkdir(parents=True, exist_ok=True)
        path = self._materials_dir / sha256_hex
        if path.is_file():
            return
        path.write_bytes(content)
