"""Domain errors of `app.application.materials` (HLD 71 §71.11, I4 E34, `i4-openapi-delta.yaml`).

`code` is the `ProblemCode` `app.api.errors.STATUS_BY_CODE` maps to a status; the two 422 codes are
E34's own addition to the I4 delta's `UnprocessableEntityI4` (§71.16).
"""

from __future__ import annotations

from app.domain.common.errors import DomainError
from app.domain.common.ids import MaterialId

__all__ = ["MaterialNotFoundError", "MaterialTooLargeError", "MaterialTypeNotAllowedError"]


class MaterialTypeNotAllowedError(DomainError):
    """`uploadMaterial`'s file extension is not on the allow-list (`422`, ТЗ ¶387, ¶370)."""

    code = "MATERIAL_TYPE_NOT_ALLOWED"

    def __init__(self, file_name: str) -> None:
        self.file_name = file_name
        super().__init__(f"{file_name!r} is not an allowed material type")


class MaterialTooLargeError(DomainError):
    """`uploadMaterial`'s body exceeds `SIM_MATERIAL_MAX_MB` (`422`)."""

    code = "MATERIAL_TOO_LARGE"

    def __init__(self, size_bytes: int, max_bytes: int) -> None:
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes
        super().__init__(f"{size_bytes} bytes exceeds the {max_bytes}-byte limit")


class MaterialNotFoundError(DomainError):
    """No such `training_materials` row — or one hidden from this caller (`404`).

    Raised for an unknown id and, in `GetMaterialFile`, for a material a TRAINEE archived-hides
    (this task's technical reading of "hidden from trainees, the file is kept" — the row is not a
    404 for INSTRUCTOR/ADMIN, only for the role the archive is meant to hide it from).
    """

    code = "NOT_FOUND"

    def __init__(self, material_id: MaterialId) -> None:
        self.material_id = material_id
        super().__init__(f"no training material {material_id}")
