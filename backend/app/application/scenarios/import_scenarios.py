"""`ImportScenarios` — discover, validate and persist scenario files (D4, HLD §20.2, SPEC §4).

One run of the use case is one Unit of Work transaction over every `<slug>/v<N>.yaml` file under
the given root, so a rejected file leaves the database exactly as it was.

Per file (D4, "The DB stores the full validated document … Re-importing a changed file under an
existing version number is rejected; bump the version"):

* the file is loaded and **fully validated** through the `ScenarioSource` port — an invalid file
  raises `ScenarioValidationError` and the whole import is rolled back;
* the owning `scenarios` row is created if the slug is new;
* `scenario_versions` gets the validated document in `content` plus its `content_sha256`;
* the version's `scoring_rules` are materialised as reference rows (§20.2);
* re-importing the **same** version with the **same** digest is a no-op — the import is idempotent;
* re-importing the same version with a **different** digest raises `ScenarioVersionChangedError`,
  which tells the author to bump the version.

Locking is deliberately *not* done here: `locked_at` is set by session creation in the same
transaction that creates the first session using the version (D4, E5), through
`ScenarioRepository.lock_scenario_version`.

HLD gap (see the task report): `scenarios.title_ru` (§20.2) has no counterpart key in the SPEC §4
scenario document — a version file carries `title` and no `*_ru` scenario-level title. The reading
closest to SPEC §4 is to project the newest imported version's `title` into `scenarios.title_ru`
rather than to invent a product requirement for a new YAML key; that is what `_scenario_title`
does.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.application.ports.scenario_repository import ScenarioRepository
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.errors import DomainError
from app.domain.scenario.version import ScenarioVersion

__all__ = [
    "ImportReport",
    "ImportScenarios",
    "ScenarioIdentityConflictError",
    "ScenarioSource",
    "ScenarioVersionChangedError",
    "canonical_content",
    "content_digest",
]


class ScenarioVersionChangedError(DomainError):
    """A file changed under a version number that is already imported (D4, SPEC §42 test 6)."""

    def __init__(self, slug: str, version: int, stored_sha256: str, file_sha256: str) -> None:
        self.slug = slug
        self.version = version
        self.stored_sha256 = stored_sha256
        self.file_sha256 = file_sha256
        super().__init__(
            f"scenario {slug!r} version {version} is already imported with content_sha256 "
            f"{stored_sha256} but the file hashes to {file_sha256}: a ScenarioVersion is "
            f"immutable (SPEC §4) — bump the version to v{version + 1} instead of "
            f"editing v{version}"
        )


class ScenarioIdentityConflictError(DomainError):
    """A slug is already owned by a different `scenario_id` than the file declares (§20.2)."""

    def __init__(self, slug: str, stored_scenario_id: str, file_scenario_id: str) -> None:
        self.slug = slug
        self.stored_scenario_id = stored_scenario_id
        self.file_scenario_id = file_scenario_id
        super().__init__(
            f"scenario slug {slug!r} is owned by scenario_id {stored_scenario_id} but the file "
            f"declares {file_scenario_id}"
        )


@runtime_checkable
class ScenarioSource(Protocol):
    """Where scenario files come from — the application side of the YAML loader (D2).

    The adapter lives with the loader in `app.infrastructure` / `app.tools`; the use case may not
    import either, so the capability is declared here.
    """

    def discover(self, root: Path) -> Sequence[Path]:
        """Every `<slug>/v<N>.yaml` file under `root`, sorted by (slug, version)."""
        ...

    def slug_for(self, path: Path) -> str:
        """The owning `Scenario`'s slug for one file."""
        ...

    def load(self, path: Path) -> ScenarioVersion:
        """Load, parse and fully validate one file; raises `ScenarioValidationError`."""
        ...


@dataclass(frozen=True)
class ImportReport:
    """What one import run did; `versions_created == 0` on a repeated run (idempotence)."""

    files: int = 0
    scenarios_created: int = 0
    versions_created: int = 0
    versions_unchanged: int = 0


def canonical_content(scenario_version: ScenarioVersion) -> dict[str, Any]:
    """The validated scenario document as stored in `scenario_versions.content` (§20.2).

    JSON mode, so every enum, UUID and tuple is already a JSON-native value and PostgreSQL's
    `jsonb` round-trips it unchanged.
    """
    return scenario_version.model_dump(mode="json")


def content_digest(content: Mapping[str, Any]) -> str:
    """`scenario_versions.content_sha256`: SHA-256 over a canonical JSON serialisation.

    Keys are sorted and separators are tight, so two imports of the same document produce the same
    digest regardless of YAML key order or whitespace — which is what makes "same version + same
    sha = no-op" and "same version + different sha = rejected" decidable (D4).
    """
    serialised = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


class ImportScenarios:
    """Import every scenario file under a root directory in one transaction."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, source: ScenarioSource) -> None:
        self._unit_of_work = unit_of_work
        self._source = source

    async def __call__(self, root: Path) -> ImportReport:
        """Import `root`; raises on the first invalid, conflicting or changed file."""
        paths = list(self._source.discover(root))
        report = ImportReport(files=len(paths))

        async with self._unit_of_work() as uow:
            for path in paths:
                report = await self._import_one(uow.scenarios, path, report)
            await uow.commit()
        return report

    async def _import_one(
        self, scenarios: ScenarioRepository, path: Path, report: ImportReport
    ) -> ImportReport:
        scenario_version = self._source.load(path)
        slug = self._source.slug_for(path)
        content = canonical_content(scenario_version)
        digest = content_digest(content)

        scenarios_created = report.scenarios_created
        stored_scenario = await scenarios.find_scenario_by_slug(slug)
        if stored_scenario is None:
            await scenarios.add_scenario(
                scenario_version.scenario_id, slug, _scenario_title(scenario_version)
            )
            scenarios_created += 1
        elif str(stored_scenario.scenario_id) != str(scenario_version.scenario_id):
            raise ScenarioIdentityConflictError(
                slug, str(stored_scenario.scenario_id), str(scenario_version.scenario_id)
            )

        stored_version = await scenarios.find_version(
            scenario_version.scenario_id, scenario_version.version
        )
        if stored_version is None:
            await scenarios.add_version(scenario_version, content, digest, str(path))
            await scenarios.add_scoring_rules(scenario_version.id, scenario_version.scoring_rules)
            return ImportReport(
                files=report.files,
                scenarios_created=scenarios_created,
                versions_created=report.versions_created + 1,
                versions_unchanged=report.versions_unchanged,
            )

        if stored_version.content_sha256 != digest:
            raise ScenarioVersionChangedError(
                slug, scenario_version.version, stored_version.content_sha256, digest
            )
        return ImportReport(
            files=report.files,
            scenarios_created=scenarios_created,
            versions_created=report.versions_created,
            versions_unchanged=report.versions_unchanged + 1,
        )


def _scenario_title(scenario_version: ScenarioVersion) -> str:
    """`scenarios.title_ru` — see the HLD gap in this module's docstring."""
    return scenario_version.title
