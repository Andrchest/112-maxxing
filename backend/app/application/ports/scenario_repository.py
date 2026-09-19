"""`ScenarioRepository` port — `scenarios`, `scenario_versions`, `scoring_rules` (HLD §20.2, D4).

Two use cases sit on this port: scenario import (`app.application.scenarios.import_scenarios`) and
session creation (E5), which calls `lock_scenario_version` in the same transaction that creates the
first session referencing the version (D4, §20.2, SPEC §42 invariant 6).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import ScenarioId, ScenarioVersionId
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.rules import ScoringRule

__all__ = ["ScenarioRepository", "StoredScenario", "StoredScenarioVersion"]


class StoredScenario(BaseModel):
    """The identity columns of a persisted `scenarios` row (§20.2)."""

    model_config = ConfigDict(frozen=True)

    scenario_id: ScenarioId
    slug: str
    title_ru: str


class StoredScenarioVersion(BaseModel):
    """The columns of a persisted `scenario_versions` row an application decision needs (§20.2).

    `content` itself is deliberately absent: an importer compares `content_sha256`, and a session
    reads the document through its own read path. `locked_at` is what makes the row immutable.
    """

    model_config = ConfigDict(frozen=True)

    scenario_version_id: ScenarioVersionId
    scenario_id: ScenarioId
    version: int
    content_sha256: str
    locked_at: datetime | None = None


@runtime_checkable
class ScenarioRepository(Protocol):
    """Reference-data access for scenarios and their versions."""

    async def find_scenario_by_slug(self, slug: str) -> StoredScenario | None:
        """The `scenarios` row with this slug, or `None`."""
        ...

    async def add_scenario(self, scenario_id: ScenarioId, slug: str, title_ru: str) -> None:
        """Insert a `scenarios` row."""
        ...

    async def find_version(
        self, scenario_id: ScenarioId, version: int
    ) -> StoredScenarioVersion | None:
        """The `scenario_versions` row `(scenario_id, version)`, or `None`."""
        ...

    async def add_version(
        self,
        scenario_version: ScenarioVersion,
        content: Mapping[str, Any],
        content_sha256: str,
        source_path: str | None = None,
    ) -> None:
        """Insert a `scenario_versions` row carrying the full validated document (§20.2)."""
        ...

    async def add_scoring_rules(
        self, scenario_version_id: ScenarioVersionId, rules: Sequence[ScoringRule]
    ) -> None:
        """Insert the `scoring_rules` projection of a version; `order_index` is the list order."""
        ...

    async def lock_scenario_version(self, scenario_version_id: ScenarioVersionId) -> bool:
        """Set `locked_at` if it is still null; idempotent.

        Returns `True` when this call set it and `False` when it was already locked. Called by
        session creation in the same transaction (D4); after it, the DB trigger of §20.2 rejects
        every `content` / `content_sha256` update (SPEC §42 invariant 6).
        """
        ...
