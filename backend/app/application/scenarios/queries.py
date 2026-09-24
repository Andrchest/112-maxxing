"""Scenario read use cases (E7, D4, `openapi.yaml` `listScenarios` … `validateScenarioFile`).

Five reads, one class each, all over the existing `ScenarioRepository`:

* `ListScenarios` — `listScenarios`, identity only (D4: "slug and title, never content");
* `ListScenarioVersions` — `listScenarioVersions`, newest first;
* `GetScenarioVersionSummary` — `getScenarioVersionSummary`, the **trainee-safe** projection;
* `GetScenarioValidationReport` — `getScenarioValidationReport`, the §30.8 verdict of a stored
  version;
* `ValidateScenarioDocument` — `validateScenarioFile`, the same verdict for a document that was
  never imported.

The trainee summary is the one that carries a rule rather than a query. `openapi.yaml` is explicit:
"Deliberately free of `world_truth`, `caller_knowledge`, `disclosure_rules`, `expected_response`,
`world_events` and `scoring_rules`: a trainee who can read this endpoint must learn nothing a
briefing would not tell them (SPEC §2, D3)." `_trainee_summary` below is therefore built by naming
each allowed field, never by dumping the version and deleting keys — a new scenario section added
later must be *added* to this function to become visible, which is the direction D3 wants the
mistake to point.

The validation report is derived, not stored: `scenario_versions` has no report column (§20.2) and
the document is immutable once locked (D4), so re-running `scenario_version_violations` on the
stored content reproduces exactly the report recorded at import time. That is cheaper than a
column and cannot go stale. See the report's "HLD gaps".
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.application.ports.scenario_repository import (
    StoredScenarioListing,
    StoredScenarioVersionDetail,
)
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.errors import DomainError
from app.domain.common.ids import ScenarioId, ScenarioVersionId
from app.domain.enums import AgeGroup, CallerRelationship, RoleType
from app.domain.scenario.validation import VALIDATION_RULE_NUMBERS, validate_scenario_document
from app.domain.scenario.version import ScenarioVersion
from app.domain.session.variants import ScenarioVariants

__all__ = [
    "GetScenarioValidationReport",
    "GetScenarioVersionSummary",
    "ListScenarioVersions",
    "ListScenarios",
    "ScenarioNotFoundError",
    "ValidateScenarioDocument",
    "ValidationIssue",
    "ValidationReport",
    "scenario_version_trainee_summary",
    "validation_report_of",
]

CHECKED_RULE_COUNT = len(VALIDATION_RULE_NUMBERS)
"""`ScenarioValidationReport.checked_rule_count` — how many §30.8 rules a run executes.

Derived from the validation rule registry (`VALIDATION_RULE_NUMBERS`), never written as a literal:
"The complete §30.8 list is always run; a partial run is never reported as valid", and
`scenario_version_violations` runs every registered rule, so the count is a statement of fact that
grows as later epics register R37-R39."""

_VIOLATION_PREFIX = re.compile(r"^R(?P<rule>\d{1,2}):\s*(?P<rest>.*)$", re.DOTALL)
"""`scenario_version_violations` starts every message with `R<nn>:` (`validation.py` docstring)."""

_LOCATION = re.compile(r"^(?P<location>[A-Za-z_][\w.\[\]'\"-]*)(?::\s*|\s+)(?P<message>.*)$")
"""…then the offending id or dotted path, which becomes `ScenarioValidationIssue.location`."""


class ScenarioNotFoundError(DomainError):
    """No such `scenarios` or `scenario_versions` row (`openapi.yaml`, `404 NOT_FOUND`)."""

    code = "NOT_FOUND"


class ValidationIssue:
    """One `ScenarioValidationIssue`, parsed out of a `scenario_version_violations` message.

    `severity` is always `ERROR`: `scenario_version_violations` returns only violations that make
    a version invalid, and `scenario_version_warnings` — the `WARNING` half of §30.6.4 — is a
    separate function this report folds in as `WARNING` issues.
    """

    __slots__ = ("field_path", "location", "message", "rule_number", "severity")

    def __init__(
        self,
        *,
        rule_number: int,
        severity: str,
        location: str,
        message: str,
        field_path: str | None = None,
    ) -> None:
        self.rule_number = rule_number
        self.severity = severity
        self.location = location
        self.message = message
        self.field_path = field_path

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ValidationIssue(R{self.rule_number}, {self.location!r}, {self.message!r})"


class ValidationReport:
    """`openapi.yaml`'s `ScenarioValidationReport`, property names literal."""

    __slots__ = (
        "content_sha256",
        "issues",
        "scenario_slug",
        "schema_version",
        "valid",
        "version",
    )

    def __init__(
        self,
        *,
        valid: bool,
        scenario_slug: str | None,
        version: int | None,
        schema_version: int | None,
        content_sha256: str | None,
        issues: Sequence[ValidationIssue],
    ) -> None:
        self.valid = valid
        self.scenario_slug = scenario_slug
        self.version = version
        self.schema_version = schema_version
        self.content_sha256 = content_sha256
        self.issues = tuple(issues)


class TraineeSummary:
    """`openapi.yaml`'s `ScenarioVersionTraineeSummary`, property names literal.

    Every field here is one a briefing would give a trainee. Nothing sourced from `world_truth`,
    `caller_knowledge`, `disclosure_rules`, `expected_response`, `world_events` or `scoring_rules`
    may ever be added to it (D3, SPEC §2).
    """

    __slots__ = (
        "caller_age_group",
        "caller_display_ru",
        "caller_language",
        "caller_relationship",
        "description",
        "difficulty",
        "estimated_duration_seconds",
        "resource_count",
        "role_chain",
        "scenario_id",
        "scenario_slug",
        "scenario_version_id",
        "title",
        "variants",
        "version",
    )

    def __init__(
        self,
        *,
        scenario_version_id: ScenarioVersionId,
        scenario_id: ScenarioId,
        scenario_slug: str,
        version: int,
        title: str,
        description: str,
        difficulty: int,
        role_chain: tuple[RoleType, ...],
        caller_display_ru: str,
        caller_language: str,
        caller_age_group: AgeGroup,
        caller_relationship: CallerRelationship,
        estimated_duration_seconds: int | None,
        resource_count: int,
        variants: ScenarioVariants,
    ) -> None:
        self.scenario_version_id = scenario_version_id
        self.scenario_id = scenario_id
        self.scenario_slug = scenario_slug
        self.version = version
        self.title = title
        self.description = description
        self.difficulty = difficulty
        self.role_chain = role_chain
        self.caller_display_ru = caller_display_ru
        self.caller_language = caller_language
        self.caller_age_group = caller_age_group
        self.caller_relationship = caller_relationship
        self.estimated_duration_seconds = estimated_duration_seconds
        self.resource_count = resource_count
        self.variants = variants


# ---------------------------------------------------------------------------------------------
# Pure projections
# ---------------------------------------------------------------------------------------------


def scenario_version_trainee_summary(
    version: ScenarioVersion, scenario_slug: str
) -> TraineeSummary:
    """The trainee-safe projection of a parsed version (D3, SPEC §2).

    `estimated_duration_seconds` is `None`: `openapi.yaml` makes it nullable and no SPEC §4 key
    carries an estimate, so inventing one would be inventing a product requirement. See the
    report's "HLD gaps".
    """
    profile = version.caller_profile
    return TraineeSummary(
        scenario_version_id=version.id,
        scenario_id=version.scenario_id,
        scenario_slug=scenario_slug,
        version=version.version,
        title=version.title,
        description=version.description,
        difficulty=version.difficulty,
        role_chain=tuple(version.role_chain),
        caller_display_ru=profile.identity_ru,
        caller_language=profile.language,
        caller_age_group=profile.age_group,
        caller_relationship=profile.relationship,
        estimated_duration_seconds=None,
        # A count, never the list: "How many resources the DDS board will show" (`openapi.yaml`).
        resource_count=len(version.available_resources),
        # What an instructor may run it as (HLD 70 §70.2.2) — switch values, not content.
        variants=version.scenario_variants,
    )


def _issue_of(violation: str, severity: str) -> ValidationIssue:
    """Turn one `R<nn>: <location>: <message>` string into a `ScenarioValidationIssue`."""
    matched = _VIOLATION_PREFIX.match(violation)
    if matched is None:
        # Not a rule-numbered message. Rule 1 is §30.8's "the document parses / has no unknown
        # keys" rule, which is the only one a bare parse failure can be attributed to.
        return ValidationIssue(
            rule_number=1, severity=severity, location="", message=violation.strip()
        )
    rule_number = int(matched.group("rule"))
    rest = matched.group("rest").strip()
    located = _LOCATION.match(rest)
    if located is None:
        return ValidationIssue(
            rule_number=rule_number, severity=severity, location="", message=rest
        )
    return ValidationIssue(
        rule_number=rule_number,
        severity=severity,
        location=located.group("location"),
        message=located.group("message").strip(),
    )


def validation_report_of(
    document: Mapping[str, Any], *, content_sha256: str | None, scenario_slug: str | None
) -> ValidationReport:
    """Run the complete §30.8 list over a raw document and render the report.

    `valid` is "no issue has `severity: ERROR`", exactly as the schema defines it. Identity fields
    are read from the raw mapping rather than from a parsed `ScenarioVersion`, because a document
    that fails to parse still has a slug and a version the author needs to see in the report.
    """
    violations = validate_scenario_document(document)
    warnings = _warnings_of(document)
    issues = [_issue_of(violation, "ERROR") for violation in violations]
    issues.extend(_issue_of(warning, "WARNING") for warning in warnings)
    return ValidationReport(
        valid=not violations,
        scenario_slug=scenario_slug if scenario_slug is not None else _text(document, "slug"),
        version=_positive_int(document, "version"),
        schema_version=_positive_int(document, "schema_version"),
        content_sha256=content_sha256,
        issues=issues,
    )


def _warnings_of(document: Mapping[str, Any]) -> list[str]:
    """`scenario_version_warnings` for a document that parses; `[]` for one that does not."""
    from app.domain.scenario.validation import scenario_version_warnings

    try:
        version = ScenarioVersion.model_validate(dict(document))
    except Exception:
        return []
    return scenario_version_warnings(version)


def _text(document: Mapping[str, Any], key: str) -> str | None:
    value = document.get(key)
    return value if isinstance(value, str) else None


def _positive_int(document: Mapping[str, Any], key: str) -> int | None:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


# ---------------------------------------------------------------------------------------------
# Use cases
# ---------------------------------------------------------------------------------------------


class ListScenarios:
    """`listScenarios` — one page of scenario identities (D4)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, *, limit: int, offset: int) -> tuple[list[StoredScenarioListing], int]:
        """The page and the unpaged total."""
        async with self._unit_of_work() as uow:
            page = await uow.scenarios.list_scenarios(limit=limit, offset=offset)
            await uow.commit()
        return page


class ListScenarioVersions:
    """`listScenarioVersions` — every version of one scenario, newest first."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, scenario_id: ScenarioId) -> list[StoredScenarioVersionDetail]:
        """The versions; raises `ScenarioNotFoundError` when the scenario does not exist."""
        async with self._unit_of_work() as uow:
            versions = await uow.scenarios.list_versions(scenario_id)
            await uow.commit()
        if versions is None:
            raise ScenarioNotFoundError(f"no scenario {scenario_id}")
        return versions


class GetScenarioVersionSummary:
    """`getScenarioVersionSummary` — the trainee-safe projection of one version (D3)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, scenario_version_id: ScenarioVersionId) -> TraineeSummary:
        """The summary; raises `ScenarioNotFoundError` when the version does not exist."""
        async with self._unit_of_work() as uow:
            detail = await uow.scenarios.get_version_detail(scenario_version_id)
            document = await uow.scenarios.get_version_document(scenario_version_id)
            await uow.commit()
        if detail is None or document is None:
            raise ScenarioNotFoundError(f"no scenario version {scenario_version_id}")
        version = ScenarioVersion.model_validate(dict(document))
        return scenario_version_trainee_summary(version, detail.scenario_slug)


class GetScenarioValidationReport:
    """`getScenarioValidationReport` — the §30.8 verdict of a stored version."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, scenario_version_id: ScenarioVersionId) -> ValidationReport:
        """The report; raises `ScenarioNotFoundError` when the version does not exist."""
        async with self._unit_of_work() as uow:
            detail = await uow.scenarios.get_version_detail(scenario_version_id)
            document = await uow.scenarios.get_version_document(scenario_version_id)
            await uow.commit()
        if detail is None or document is None:
            raise ScenarioNotFoundError(f"no scenario version {scenario_version_id}")
        return validation_report_of(
            document,
            content_sha256=detail.content_sha256,
            scenario_slug=detail.scenario_slug,
        )


class ValidateScenarioDocument:
    """`validateScenarioFile` — a dry run that writes nothing and always answers `200`.

    "An invalid document is reported in the body as `valid: false` plus issues, because this
    endpoint's purpose is authoring feedback, not command execution" (`openapi.yaml`). It takes no
    Unit of Work: nothing is read from and nothing is written to the database.
    """

    def __call__(
        self, document: Mapping[str, Any], *, content_sha256: str | None = None
    ) -> ValidationReport:
        """The report for a document that was never imported."""
        return validation_report_of(document, content_sha256=content_sha256, scenario_slug=None)
