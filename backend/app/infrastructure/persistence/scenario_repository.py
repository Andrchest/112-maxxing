"""`SqlAlchemyScenarioRepository` — `scenarios`, `scenario_versions`, `scoring_rules` (§20.2, D4).

`lock_scenario_version` is the SPEC §42 invariant 6 hinge: it sets `locked_at` if and only if it is
still null, which arms the `scenario_versions_locked_guard` trigger of §20.2 so that every later
UPDATE of `content` / `content_sha256` — through the ORM or through raw SQL — is rejected by
PostgreSQL itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.scenario_repository import StoredScenario, StoredScenarioVersion
from app.db.models.reference import Scenario as ScenarioRow
from app.db.models.reference import ScenarioVersion as ScenarioVersionRow
from app.db.models.reference import ScoringRule as ScoringRuleRow
from app.domain.common.ids import ScenarioId, ScenarioVersionId
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.rules import ScoringRule
from app.infrastructure.persistence.mappers import (
    scenario_version_row_values,
    scoring_rule_row_values,
)

__all__ = ["SqlAlchemyScenarioRepository"]

_SCENARIOS = ScenarioRow.__table__
_VERSIONS = ScenarioVersionRow.__table__
_RULES = ScoringRuleRow.__table__


class SqlAlchemyScenarioRepository:
    """`ScenarioRepository` over PostgreSQL, bound to one `AsyncSession` (one transaction)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_scenario_by_slug(self, slug: str) -> StoredScenario | None:
        result = await self._session.execute(
            sa.select(_SCENARIOS.c.id, _SCENARIOS.c.slug, _SCENARIOS.c.title_ru).where(
                _SCENARIOS.c.slug == slug
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return StoredScenario(
            scenario_id=ScenarioId(UUID(str(row.id))), slug=row.slug, title_ru=row.title_ru
        )

    async def get_scenario(self, scenario_id: ScenarioId) -> StoredScenario | None:
        result = await self._session.execute(
            sa.select(_SCENARIOS.c.id, _SCENARIOS.c.slug, _SCENARIOS.c.title_ru).where(
                _SCENARIOS.c.id == UUID(str(scenario_id))
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return StoredScenario(
            scenario_id=ScenarioId(UUID(str(row.id))), slug=row.slug, title_ru=row.title_ru
        )

    async def get_version(
        self, scenario_version_id: ScenarioVersionId
    ) -> StoredScenarioVersion | None:
        result = await self._session.execute(
            sa.select(
                _VERSIONS.c.id,
                _VERSIONS.c.scenario_id,
                _VERSIONS.c.version,
                _VERSIONS.c.content_sha256,
                _VERSIONS.c.locked_at,
            ).where(_VERSIONS.c.id == UUID(str(scenario_version_id)))
        )
        row = result.one_or_none()
        if row is None:
            return None
        return StoredScenarioVersion(
            scenario_version_id=ScenarioVersionId(UUID(str(row.id))),
            scenario_id=ScenarioId(UUID(str(row.scenario_id))),
            version=int(row.version),
            content_sha256=row.content_sha256,
            locked_at=row.locked_at,
        )

    async def get_version_document(
        self, scenario_version_id: ScenarioVersionId
    ) -> Mapping[str, Any] | None:
        """The stored `content` of a version — the full validated document (§20.2)."""
        result = await self._session.execute(
            sa.select(_VERSIONS.c.content).where(_VERSIONS.c.id == UUID(str(scenario_version_id)))
        )
        row = result.one_or_none()
        if row is None:
            return None
        return dict(row.content)

    async def add_scenario(self, scenario_id: ScenarioId, slug: str, title_ru: str) -> None:
        await self._session.execute(
            sa.insert(_SCENARIOS).values(id=UUID(str(scenario_id)), slug=slug, title_ru=title_ru)
        )

    async def find_version(
        self, scenario_id: ScenarioId, version: int
    ) -> StoredScenarioVersion | None:
        result = await self._session.execute(
            sa.select(
                _VERSIONS.c.id,
                _VERSIONS.c.scenario_id,
                _VERSIONS.c.version,
                _VERSIONS.c.content_sha256,
                _VERSIONS.c.locked_at,
            ).where(
                _VERSIONS.c.scenario_id == UUID(str(scenario_id)),
                _VERSIONS.c.version == version,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return StoredScenarioVersion(
            scenario_version_id=ScenarioVersionId(UUID(str(row.id))),
            scenario_id=ScenarioId(UUID(str(row.scenario_id))),
            version=int(row.version),
            content_sha256=row.content_sha256,
            locked_at=row.locked_at,
        )

    async def add_version(
        self,
        scenario_version: ScenarioVersion,
        content: Mapping[str, Any],
        content_sha256: str,
        source_path: str | None = None,
    ) -> None:
        values = scenario_version_row_values(scenario_version, content, content_sha256, source_path)
        await self._session.execute(sa.insert(_VERSIONS).values(**values))

    async def add_scoring_rules(
        self, scenario_version_id: ScenarioVersionId, rules: Sequence[ScoringRule]
    ) -> None:
        rows = scoring_rule_row_values(scenario_version_id, rules)
        if not rows:
            return
        await self._session.execute(sa.insert(_RULES), rows)

    async def lock_scenario_version(self, scenario_version_id: ScenarioVersionId) -> bool:
        """Set `locked_at = now()` if it is still null; `True` when this call set it (D4)."""
        result = await self._session.execute(
            sa.update(_VERSIONS)
            .where(
                _VERSIONS.c.id == UUID(str(scenario_version_id)),
                _VERSIONS.c.locked_at.is_(None),
            )
            .values(locked_at=sa.func.now())
            .returning(_VERSIONS.c.id)
        )
        return result.one_or_none() is not None
