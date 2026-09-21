"""Scenario reference-data use cases (D4).

`ImportScenarios` imports a directory through the `ScenarioSource` port (the CLI);
`ImportScenarioVersion` imports one document from a request body (E7's `importScenarioVersion`).
Both share `canonical_content` / `content_digest` and the thirty §30.8 rules. `queries` holds the
read side: the scenario list, the version list, the trainee-safe summary and the validation report.
"""

from __future__ import annotations

from app.application.scenarios.import_scenario_version import (
    ImportScenarioVersion,
    ImportScenarioVersionCommand,
    ScenarioDocumentInvalidError,
    ScenarioVersionExistsError,
    ScenarioVersionLockedError,
    parse_scenario_document,
)
from app.application.scenarios.import_scenarios import (
    ImportReport,
    ImportScenarios,
    ScenarioIdentityConflictError,
    ScenarioSource,
    ScenarioVersionChangedError,
    canonical_content,
    content_digest,
)
from app.application.scenarios.queries import (
    CHECKED_RULE_COUNT,
    GetScenarioValidationReport,
    GetScenarioVersionSummary,
    ListScenarios,
    ListScenarioVersions,
    ScenarioNotFoundError,
    TraineeSummary,
    ValidateScenarioDocument,
    ValidationIssue,
    ValidationReport,
    scenario_version_trainee_summary,
    validation_report_of,
)

__all__ = [
    "CHECKED_RULE_COUNT",
    "GetScenarioValidationReport",
    "GetScenarioVersionSummary",
    "ImportReport",
    "ImportScenarioVersion",
    "ImportScenarioVersionCommand",
    "ImportScenarios",
    "ListScenarioVersions",
    "ListScenarios",
    "ScenarioDocumentInvalidError",
    "ScenarioIdentityConflictError",
    "ScenarioNotFoundError",
    "ScenarioSource",
    "ScenarioVersionChangedError",
    "ScenarioVersionExistsError",
    "ScenarioVersionLockedError",
    "TraineeSummary",
    "ValidateScenarioDocument",
    "ValidationIssue",
    "ValidationReport",
    "canonical_content",
    "content_digest",
    "parse_scenario_document",
    "scenario_version_trainee_summary",
    "validation_report_of",
]
