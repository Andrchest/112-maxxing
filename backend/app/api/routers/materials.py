"""`materials` router — `uploadMaterial`, `listMaterials`, `getMaterialFile`, `archiveMaterial`
(`i4-openapi-delta.yaml`, HLD 71 §71.11, I4 E34, ТЗ ¶227, ¶256, ¶387, ¶370).

Upload and archive are INSTRUCTOR/ADMIN only (`AdminOrInstructorDep`); the two reads are every
authenticated role (`CurrentUserDep`) — «Справочная база» is a trainee page too.

`getMaterialFile` returns a `Response` rather than a `response_model`, the same reason
`getAudioSegment` does (`app.api.routers.reports`): its body is the file's own bytes.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Form, Query, Response, UploadFile

from app.api.deps import ContainerDep
from app.api.schemas.materials import (
    MaterialListSchema,
    TrainingMaterialViewSchema,
    training_material_view_schema,
)
from app.api.security import AdminOrInstructorDep, CurrentUserDep
from app.application.materials.upload_material import UploadMaterialRequest
from app.domain.common.ids import MaterialId

router = APIRouter(prefix="/api/v1/materials", tags=["materials"])


def _content_disposition(*, inline: bool, file_name: str) -> str:
    """RFC 6266/5987: an ASCII fallback plus the real, percent-encoded name (Cyrillic titles)."""
    kind = "inline" if inline else "attachment"
    ascii_fallback = file_name.encode("ascii", "replace").decode("ascii")
    return f"{kind}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(file_name)}"


@router.post(
    "",
    operation_id="uploadMaterial",
    summary="Upload a methodical material (INSTRUCTOR / ADMIN) — ТЗ ¶227, ¶387, ¶370.",
    response_model=TrainingMaterialViewSchema,
    status_code=201,
)
async def upload_material(
    container: ContainerDep,
    user: AdminOrInstructorDep,
    title_ru: Annotated[str, Form(min_length=1)],
    file: UploadFile,
) -> TrainingMaterialViewSchema:
    """Allow-list pdf/docx/doc/xlsx/txt/md/png/jpg (else `422 MATERIAL_TYPE_NOT_ALLOWED`); larger
    than `SIM_MATERIAL_MAX_MB` is `422 MATERIAL_TOO_LARGE`. Identical bytes are stored once."""
    content = await file.read()
    material = await container.upload_material()(
        UploadMaterialRequest(title_ru=title_ru, file_name=file.filename or "", content=content),
        actor=user,
    )
    return training_material_view_schema(material)


@router.get(
    "",
    operation_id="listMaterials",
    summary="The reference base «Справочная база» (every authenticated role) — ТЗ ¶256.",
    response_model=MaterialListSchema,
    status_code=200,
)
async def list_materials(
    container: ContainerDep,
    user: CurrentUserDep,
    include_archived: Annotated[bool, Query()] = False,
) -> MaterialListSchema:
    """Unarchived materials for everyone; `include_archived` only takes effect for
    INSTRUCTOR/ADMIN. No per-trainee assignment (Q-E13-1 open)."""
    materials = await container.list_materials()(user, include_archived=include_archived)
    return MaterialListSchema(items=[training_material_view_schema(m) for m in materials])


@router.get(
    "/{material_id}/file",
    operation_id="getMaterialFile",
    summary="Download or open a material (every authenticated role).",
    status_code=200,
    response_class=Response,
)
async def get_material_file(
    material_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
) -> Response:
    """The stored content type; a PDF is sent inline, other types as an attachment."""
    served = await container.get_material_file()(MaterialId(material_id), user)
    headers = {
        "Content-Disposition": _content_disposition(
            inline=served.inline, file_name=served.file_name
        )
    }
    return Response(content=served.content, media_type=served.content_type, headers=headers)


@router.post(
    "/{material_id}/archive",
    operation_id="archiveMaterial",
    summary="Archive a material — hidden from trainees, file kept (INSTRUCTOR / ADMIN).",
    response_model=TrainingMaterialViewSchema,
    status_code=200,
)
async def archive_material(
    material_id: UUID,
    container: ContainerDep,
    _user: AdminOrInstructorDep,
) -> TrainingMaterialViewSchema:
    """Idempotent: archiving an already-archived material returns it unchanged."""
    material = await container.archive_material()(MaterialId(material_id))
    return training_material_view_schema(material)
