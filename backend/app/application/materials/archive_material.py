"""`ArchiveMaterial` — `archiveMaterial` (INSTRUCTOR / ADMIN, HLD 71 §71.11).

Hides the material from a trainee's «Справочная база»; the file and the row both stay (reference
data, no retention). Idempotent: archiving an already-archived material returns it unchanged,
keeping its first `archived_at` rather than moving it forward on every repeated call.
"""

from __future__ import annotations

from app.application.materials.errors import MaterialNotFoundError
from app.application.ports.audit_changes import NO_AUDIT_CHANGES, AuditChangeCollector
from app.application.ports.clock import Clock
from app.application.ports.material_repository import StoredMaterial
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.ids import MaterialId

__all__ = ["ArchiveMaterial"]


class ArchiveMaterial:
    """`archiveMaterial` (§71.11)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        *,
        changes: AuditChangeCollector = NO_AUDIT_CHANGES,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._changes = changes  # I7 E43

    async def __call__(self, material_id: MaterialId) -> StoredMaterial:
        async with self._unit_of_work() as uow:
            before = await uow.materials.get(material_id)
            archived = await uow.materials.archive(material_id, archived_at=self._clock.now())
            if archived is None:
                raise MaterialNotFoundError(material_id)
            await uow.commit()
        self._changes.record(
            "material",
            "archived",
            before.archived_at is not None if before is not None else None,
            archived.archived_at is not None,
        )
        return archived
