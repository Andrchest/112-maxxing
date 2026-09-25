"""`GetMaterialFile` — `getMaterialFile`, download or open a material (HLD 71 §71.11).

**Content type.** The stored `content_type` (from the upload's extension, `allowed_types.py`),
verbatim — never re-derived from the bytes.

**Disposition.** A PDF is sent inline (a browser tab can render it); every other allowed type is an
attachment, which is what makes a DOCX "download" rather than the browser trying and failing to
render it (§71.11: "A PDF opens inline and a DOCX downloads").

**Archived + TRAINEE = `404`** (this task's technical reading, `errors.py`): the design's own words
are "hidden from trainees, the file is kept" — a `200` for the metadata list but not for the bytes
would defeat the hiding, so `listMaterials` and `getMaterialFile` agree for a TRAINEE caller.

**Path safety (SPEC §41).** The only input to the path is the row's own `sha256` (a validated hex
digest, `CHECK` at the database), joined onto `materials_dir` and refused unless the resolved path
is still inside it and is a real file — the same containment check `ServeAudioSegment` uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.materials.errors import MaterialNotFoundError
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.ids import MaterialId

__all__ = ["GetMaterialFile", "MaterialFileResponse"]

#: HLD 71 §71.11: "A PDF opens inline and a DOCX downloads" — generalised to every other type.
_INLINE_CONTENT_TYPES = frozenset({"application/pdf"})


@dataclass(frozen=True, slots=True)
class MaterialFileResponse:
    """What the router turns into a `Response`."""

    content: bytes
    content_type: str
    file_name: str
    inline: bool


class GetMaterialFile:
    """`getMaterialFile` (§71.11)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, *, materials_dir: Path) -> None:
        self._unit_of_work = unit_of_work
        #: `DATA_DIR/materials` (§71.11). Every served path must resolve inside it.
        self._materials_dir = materials_dir

    async def __call__(
        self, material_id: MaterialId, actor: AuthenticatedUser
    ) -> MaterialFileResponse:
        async with self._unit_of_work() as uow:
            material = await uow.materials.get(material_id)
            await uow.commit()
        if material is None:
            raise MaterialNotFoundError(material_id)
        if material.archived_at is not None and not actor.is_instructor_or_admin:
            raise MaterialNotFoundError(material_id)

        path = self._resolved_path(material.sha256, material_id)
        return MaterialFileResponse(
            content=path.read_bytes(),
            content_type=material.content_type,
            file_name=material.file_name,
            inline=material.content_type in _INLINE_CONTENT_TYPES,
        )

    def _resolved_path(self, sha256_hex: str, material_id: MaterialId) -> Path:
        base = self._materials_dir.resolve()
        candidate = (base / sha256_hex).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            raise MaterialNotFoundError(material_id)
        return candidate
