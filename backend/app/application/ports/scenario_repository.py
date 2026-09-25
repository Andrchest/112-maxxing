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
from app.domain.enums import RoleType
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.rules import ScoringRule
from app.domain.session.variants import ScenarioVariants

__all__ = [
    "ScenarioRepository",
    "StoredScenario",
    "StoredScenarioListing",
    "StoredScenarioVersion",
    "StoredScenarioVersionDetail",
]


class StoredScenario(BaseModel):
    """The identity columns of a persisted `scenarios` row (§20.2)."""

    model_config = ConfigDict(frozen=True)

    scenario_id: ScenarioId
    slug: str
    title_ru: str
    archived_at: datetime | None = None
    """I4 E32 (§20.11.3): `None` = active; set by `archiveScenario`."""


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


class StoredScenarioListing(BaseModel):
    """One row of `listScenarios` — `openapi.yaml`'s `ScenarioSummary`, property names literal.

    `version_count` and `latest_version` are aggregates over `scenario_versions`, so they are
    computed by the adapter in one statement rather than by a per-scenario read above it.
    """

    model_config = ConfigDict(frozen=True)

    scenario_id: ScenarioId
    slug: str
    title_ru: str
    version_count: int
    latest_version: int | None = None
    latest_difficulty: int | None = None
    """I3 E9a: the latest version's `difficulty` (1–5), so a picker can show and filter it."""
    archived_at: datetime | None = None
    """I4 E32 (§20.11.3): `None` = active; hidden from `listScenarios` unless `include_archived`."""


class StoredScenarioVersionDetail(BaseModel):
    """The `scenario_versions` columns `openapi.yaml`'s `ScenarioVersionListItem` renders.

    Distinct from `StoredScenarioVersion`, which is the decision-making projection the importer
    and session creation read (`content_sha256` + `locked_at` and nothing else). This one is the
    *presentation* projection and, like that one, still leaves `content` out: an endpoint that
    lists versions must never serialise a scenario document.
    """

    model_config = ConfigDict(frozen=True)

    scenario_version_id: ScenarioVersionId
    scenario_id: ScenarioId
    scenario_slug: str
    schema_version: int
    version: int
    title: str
    description: str
    difficulty: int
    role_chain: tuple[RoleType, ...]
    content_sha256: str
    locked_at: datetime | None = None
    created_at: datetime
    variants: ScenarioVariants
    """The version's *supported + default* variants — declared (schema 2) or derived (HLD 70
    §70.2.2). Derived by the adapter from two facts of `content`, never the document itself."""


@runtime_checkable
class ScenarioRepository(Protocol):
    """Reference-data access for scenarios and their versions."""

    async def find_scenario_by_slug(self, slug: str) -> StoredScenario | None:
        """The `scenarios` row with this slug, or `None`."""
        ...

    async def get_scenario(self, scenario_id: ScenarioId) -> StoredScenario | None:
        """The `scenarios` row with this id, or `None`.

        Session creation needs the owning scenario's `slug` for the `SESSION_CREATED` payload
        (§10.13), and a version only knows its `scenario_id`.
        """
        ...

    async def get_version(
        self, scenario_version_id: ScenarioVersionId
    ) -> StoredScenarioVersion | None:
        """The `scenario_versions` row with this id, or `None` (the session-creation read path).

        `find_version` reads by `(scenario_id, version)`, which is the importer's key; a session
        is created against a `scenario_version_id` and needs this by-id read.
        """
        ...

    async def get_version_document(
        self, scenario_version_id: ScenarioVersionId
    ) -> Mapping[str, Any] | None:
        """The stored `content` of a version — the full validated document (§20.2), or `None`.

        Session creation turns it back into a `ScenarioVersion` with
        `ScenarioVersion.model_validate` and re-runs `validate_scenario_version` on the result;
        there is exactly one parser in the system (`app.domain.scenario`) and this method feeds
        it, it does not duplicate it.
        """
        ...

    async def list_scenarios(
        self, *, limit: int, offset: int, include_archived: bool = False
    ) -> tuple[list[StoredScenarioListing], int]:
        """One page of `scenarios`, ordered by `slug`, plus the unpaged total (`listScenarios`).

        The total is what `openapi.yaml`'s response object calls `total`: how many scenarios exist,
        not how many this page holds. `include_archived=False` (the default, I4 E32) hides every
        row with `archived_at IS NOT NULL` from both the page and the total, so a picker never
        needs to filter the response itself.
        """
        ...

    async def list_versions(
        self, scenario_id: ScenarioId
    ) -> list[StoredScenarioVersionDetail] | None:
        """Every version of one scenario, newest first, or `None` when the scenario is unknown.

        `None` rather than `[]` because `listScenarioVersions` answers `404 NOT_FOUND` for a
        scenario that does not exist and `200` with an empty page for one that has no versions.
        """
        ...

    async def get_version_detail(
        self, scenario_version_id: ScenarioVersionId
    ) -> StoredScenarioVersionDetail | None:
        """One version's presentation projection, or `None`."""
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

    async def set_archived(
        self, scenario_id: ScenarioId, *, archived: bool
    ) -> StoredScenarioListing | None:
        """`archiveScenario` / `unarchiveScenario` (I4 E32, ТЗ ¶229): idempotent either way.

        Archiving sets `archived_at` only if it is still null (leaves the original timestamp
        alone on a repeated call); unarchiving always clears it. Returns the scenario's listing
        row after the change (so the endpoint can answer with the full `ScenarioSummary`), or
        `None` when no such scenario exists. Existing `scenario_versions` and sessions are
        untouched: their FK to `scenarios` stays `RESTRICT`.
        """
        ...
