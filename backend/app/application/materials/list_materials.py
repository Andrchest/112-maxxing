"""`ListMaterials` — `listMaterials`, the reference base «Справочная база» (ТЗ ¶256, HLD 71 §71.11).

Every authenticated role may call it; `include_archived` only takes effect for INSTRUCTOR/ADMIN —
a TRAINEE's own `include_archived=true` is silently ignored rather than refused, since the query
parameter is a convenience for the instructor's «Материалы» page, not a capability a trainee is
being denied access to (no assignment exists yet either, Q-E13-1, so every trainee already sees the
same unarchived list).
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.material_repository import StoredMaterial
from app.application.ports.unit_of_work import UnitOfWorkFactory

__all__ = ["ListMaterials"]


class ListMaterials:
    """`listMaterials` (§71.11)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, actor: AuthenticatedUser, *, include_archived: bool
    ) -> list[StoredMaterial]:
        effective_include_archived = include_archived and actor.is_instructor_or_admin
        async with self._unit_of_work() as uow:
            materials = await uow.materials.list_materials(
                include_archived=effective_include_archived
            )
            await uow.commit()
        return materials
