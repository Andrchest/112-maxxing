"""`ImportScenarioVersion` — import ONE scenario document from a request body (E7, D4).

`app.application.scenarios.import_scenarios.ImportScenarios` imports a *directory* through the
`ScenarioSource` port: it is the CLI's use case (`app.tools.import_scenarios`) and it owns the
file-system conventions of D4. `openapi.yaml`'s `importScenarioVersion` posts one document as a
string in a JSON body, so it needs the same rules without the file system. Everything the two
share — `canonical_content`, `content_digest`, and the thirty §30.8 rules — is reused rather than
restated; only the *source* of the document differs.

The rules, from D4 and `openapi.yaml`'s own description:

* the document is parsed and fully validated first. Invalid ⇒ `ScenarioDocumentInvalidError`
  carrying the complete `ScenarioValidationReport` (`422 SCENARIO_INVALID`, the `ScenarioProblem`
  schema) and **nothing is written**;
* the owning `scenarios` row is created when the `scenario_id` is new;
* re-importing the **same** version with the **same** digest is a no-op and answers `201` with the
  stored row — the endpoint is idempotent, which is what makes a retried upload harmless;
* re-importing the same version with a **different** digest is refused:
  `409 SCENARIO_VERSION_LOCKED` when `locked_at` is set, `409 SCENARIO_VERSION_EXISTS` otherwise —
  "bump the version (D4)", literally as `openapi.yaml` states it.

`locked_at` is never set here; session creation sets it (D4, E5).

HLD gap (see the task report): `ScenarioImportRequest` carries no `slug`, and SPEC §4's top-level
key list has none either — the slug identifies the owning `Scenario`, not the version. The slug is
therefore resolved in the order that invents the least: the `scenarios` row this `scenario_id`
already owns, else the parent directory of the request's optional `source_path` (the D4 file
convention `scenarios/examples/<slug>/v<N>.yaml`), else a slug derived from the version's `title`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml

from app.application.ports.reference import ReferencePort
from app.application.ports.scenario_repository import StoredScenarioVersionDetail
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.reference.queries import reference_catalog
from app.application.scenarios.import_scenarios import canonical_content, content_digest
from app.application.scenarios.queries import ValidationReport, validation_report_of
from app.domain.common.errors import DomainError
from app.domain.scenario.version import ScenarioVersion

__all__ = [
    "ImportScenarioVersion",
    "ImportScenarioVersionCommand",
    "ScenarioDocumentInvalidError",
    "ScenarioVersionExistsError",
    "ScenarioVersionLockedError",
    "parse_scenario_document",
]

_SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")


class ScenarioDocumentInvalidError(DomainError):
    """The document failed §30.8 validation (`422 SCENARIO_INVALID`, `ScenarioProblem`).

    It carries the complete report, because `openapi.yaml` says so: "The problem carries the
    complete `validation_report`; nothing was written."
    """

    code = "SCENARIO_INVALID"

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        errors = [issue for issue in report.issues if issue.severity == "ERROR"]
        super().__init__(f"the scenario document has {len(errors)} validation error(s)")


class ScenarioVersionExistsError(DomainError):
    """This version number already holds different content (`409 SCENARIO_VERSION_EXISTS`, D4)."""

    code = "SCENARIO_VERSION_EXISTS"

    def __init__(self, slug: str, version: int) -> None:
        self.slug = slug
        self.version = version
        super().__init__(
            f"scenario {slug!r} version {version} is already imported with different content: "
            f"a ScenarioVersion is immutable (SPEC §4) — bump the version to v{version + 1}"
        )


class ScenarioVersionLockedError(DomainError):
    """This version is locked by a session and can never change (`409 SCENARIO_VERSION_LOCKED`)."""

    code = "SCENARIO_VERSION_LOCKED"

    def __init__(self, slug: str, version: int) -> None:
        self.slug = slug
        self.version = version
        super().__init__(
            f"scenario {slug!r} version {version} is locked by a session and its content can "
            f"never change (D4, SPEC §42 invariant 6) — bump the version to v{version + 1}"
        )


class ScenarioIdentityConflictError(DomainError):
    """The document's `scenario_id` and the slug's owner disagree (§20.2)."""

    code = "VALIDATION_ERROR"


@dataclass(frozen=True)
class ImportScenarioVersionCommand:
    """`openapi.yaml`'s `ScenarioImportRequest` — `format`, `content`, optional `source_path`."""

    format: str
    content: str
    source_path: str | None = None


def parse_scenario_document(content: str, document_format: str) -> Mapping[str, Any]:
    """Parse the request body's `content` string into a mapping, or raise `SCENARIO_INVALID`.

    `format: YAML` goes through `yaml.safe_load` — the same loader the file path uses, so a file
    that imports from disk imports identically through HTTP. `format: JSON` goes through
    `json.loads`; JSON is a subset of YAML, but parsing it as what it claims to be keeps the error
    messages honest. Nothing is written to a temporary file: the document is a string in memory
    from the request body to `scenario_versions.content`.
    """
    try:
        if document_format.upper() == "JSON":
            parsed: Any = json.loads(content)
        else:
            parsed = yaml.safe_load(content)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ScenarioDocumentInvalidError(
            _unparseable_report(f"the {document_format.upper()} document does not parse: {exc}")
        ) from exc
    if not isinstance(parsed, Mapping):
        raise ScenarioDocumentInvalidError(
            _unparseable_report("the document must be a mapping at the top level")
        )
    return parsed


def _unparseable_report(message: str) -> ValidationReport:
    """A report for a document that never became a mapping, so no rule could run against it."""
    return validation_report_of(
        {"__unparseable__": message}, content_sha256=None, scenario_slug=None
    )


class ImportScenarioVersion:
    """Validate and store one scenario version document, in one transaction (D4)."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, reference: ReferencePort | None = None
    ) -> None:
        self._unit_of_work = unit_of_work
        self._reference = reference

    async def __call__(self, command: ImportScenarioVersionCommand) -> StoredScenarioVersionDetail:
        """Import; returns the stored row. Every rejection leaves the database untouched."""
        document = parse_scenario_document(command.content, command.format)
        report = validation_report_of(
            document,
            content_sha256=None,
            scenario_slug=None,
            reference=reference_catalog(self._reference),
        )
        if not report.valid:
            raise ScenarioDocumentInvalidError(report)

        version = ScenarioVersion.model_validate(dict(document))
        content = canonical_content(version)
        digest = content_digest(content)

        async with self._unit_of_work() as uow:
            slug = await self._resolve_slug(uow, version, command.source_path)
            await self._ensure_scenario(uow, version, slug)
            await self._store_version(uow, version, slug, content, digest, command.source_path)
            detail = await uow.scenarios.get_version_detail(version.id)
            await uow.commit()

        if detail is None:  # pragma: no cover - the row was just written in this transaction
            raise ScenarioIdentityConflictError(f"scenario version {version.id} vanished on write")
        return detail

    # -- steps --------------------------------------------------------------------------------

    async def _resolve_slug(
        self, uow: UnitOfWork, version: ScenarioVersion, source_path: str | None
    ) -> str:
        """The owning `Scenario`'s slug — see this module's "HLD gap" note."""
        existing = await uow.scenarios.get_scenario(version.scenario_id)
        if existing is not None:
            return existing.slug
        if source_path:
            parent = PurePosixPath(source_path).parent.name
            if parent:
                return parent
        return slug_of(version.title)

    async def _ensure_scenario(self, uow: UnitOfWork, version: ScenarioVersion, slug: str) -> None:
        owner = await uow.scenarios.find_scenario_by_slug(slug)
        if owner is None:
            await uow.scenarios.add_scenario(version.scenario_id, slug, version.title)
            return
        if str(owner.scenario_id) != str(version.scenario_id):
            raise ScenarioIdentityConflictError(
                f"scenario slug {slug!r} is owned by scenario_id {owner.scenario_id} but the "
                f"document declares {version.scenario_id}"
            )

    async def _store_version(
        self,
        uow: UnitOfWork,
        version: ScenarioVersion,
        slug: str,
        content: Mapping[str, Any],
        digest: str,
        source_path: str | None,
    ) -> None:
        stored = await uow.scenarios.find_version(version.scenario_id, version.version)
        if stored is None:
            await uow.scenarios.add_version(version, content, digest, source_path)
            await uow.scenarios.add_scoring_rules(version.id, version.scoring_rules)
            return
        if stored.content_sha256 == digest:
            return  # idempotent: the same version with the same content is already stored
        if stored.locked_at is not None:
            raise ScenarioVersionLockedError(slug, version.version)
        raise ScenarioVersionExistsError(slug, version.version)


def slug_of(title: str) -> str:
    """A last-resort slug derived from a version's `title` (see the "HLD gap" note)."""
    lowered = _SLUG_SEPARATORS.sub("-", title.lower()).strip("-")
    return lowered or "scenario"
