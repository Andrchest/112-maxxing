"""`archiveScenario` / `unarchiveScenario` (I4 E32, HLD `71-i4-wave4.md` §71.9, ТЗ ¶229).

"Редактировать и удалять неактуальные сценарии" is built as an archive, not a delete: the FKs
from `scenario_versions` and sessions to `scenarios` stay `RESTRICT` (D4), so a scenario row is
never removed. Archiving only hides it from `listScenarios`'s default page; a session already
running on one of its versions is completely unaffected — nothing here touches
`scenario_versions` or `simulation_sessions` at all.
"""

from __future__ import annotations

from app.application.ports.audit_changes import NO_AUDIT_CHANGES, AuditChangeCollector
from app.application.ports.reference import ReferencePort
from app.application.ports.scenario_repository import StoredScenarioListing
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.reference.queries import reference_catalog
from app.application.scenarios.queries import ScenarioNotFoundError, with_category
from app.domain.common.ids import ScenarioId

__all__ = ["ArchiveScenario", "UnarchiveScenario"]


async def _set_archived(
    unit_of_work: UnitOfWorkFactory,
    changes: AuditChangeCollector,
    scenario_id: ScenarioId,
    *,
    archived: bool,
    reference: ReferencePort | None = None,
) -> StoredScenarioListing:
    """Both commands: flip the flag, and report `scenario.archived` «было → стало» (I7 E43)."""
    async with unit_of_work() as uow:
        before = await uow.scenarios.get_scenario(scenario_id)
        listing = await uow.scenarios.set_archived(scenario_id, archived=archived)
        await uow.commit()
    if listing is None:
        raise ScenarioNotFoundError(f"no scenario {scenario_id}")
    changes.record(
        "scenario",
        "archived",
        before.archived_at is not None if before is not None else None,
        listing.archived_at is not None,
    )
    # I7 E53: the same `category` `listScenarios` shows for this scenario.
    return with_category(listing, reference_catalog(reference))


class ArchiveScenario:
    """`archiveScenario` — idempotent; a second call leaves the original `archived_at`."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        *,
        changes: AuditChangeCollector = NO_AUDIT_CHANGES,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._changes = changes
        self._reference = reference

    async def __call__(self, scenario_id: ScenarioId) -> StoredScenarioListing:
        return await _set_archived(
            self._unit_of_work,
            self._changes,
            scenario_id,
            archived=True,
            reference=self._reference,
        )


class UnarchiveScenario:
    """`unarchiveScenario` — idempotent; a second call is a no-op."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        *,
        changes: AuditChangeCollector = NO_AUDIT_CHANGES,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._changes = changes
        self._reference = reference

    async def __call__(self, scenario_id: ScenarioId) -> StoredScenarioListing:
        return await _set_archived(
            self._unit_of_work,
            self._changes,
            scenario_id,
            archived=False,
            reference=self._reference,
        )
