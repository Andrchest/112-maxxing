"""`archiveScenario` / `unarchiveScenario` (I4 E32, HLD `71-i4-wave4.md` §71.9, ТЗ ¶229).

"Редактировать и удалять неактуальные сценарии" is built as an archive, not a delete: the FKs
from `scenario_versions` and sessions to `scenarios` stay `RESTRICT` (D4), so a scenario row is
never removed. Archiving only hides it from `listScenarios`'s default page; a session already
running on one of its versions is completely unaffected — nothing here touches
`scenario_versions` or `simulation_sessions` at all.
"""

from __future__ import annotations

from app.application.ports.scenario_repository import StoredScenarioListing
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.scenarios.queries import ScenarioNotFoundError
from app.domain.common.ids import ScenarioId

__all__ = ["ArchiveScenario", "UnarchiveScenario"]


class ArchiveScenario:
    """`archiveScenario` — idempotent; a second call leaves the original `archived_at`."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, scenario_id: ScenarioId) -> StoredScenarioListing:
        async with self._unit_of_work() as uow:
            listing = await uow.scenarios.set_archived(scenario_id, archived=True)
            await uow.commit()
        if listing is None:
            raise ScenarioNotFoundError(f"no scenario {scenario_id}")
        return listing


class UnarchiveScenario:
    """`unarchiveScenario` — idempotent; a second call is a no-op."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, scenario_id: ScenarioId) -> StoredScenarioListing:
        async with self._unit_of_work() as uow:
            listing = await uow.scenarios.set_archived(scenario_id, archived=False)
            await uow.commit()
        if listing is None:
            raise ScenarioNotFoundError(f"no scenario {scenario_id}")
        return listing
