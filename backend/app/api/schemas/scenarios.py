"""`scenarios` schemas (`openapi.yaml`, D3, D4).

`ScenarioVersionTraineeSummarySchema` is the one to read twice. `openapi.yaml`: "Deliberately free
of `world_truth`, `caller_knowledge`, `disclosure_rules`, `expected_response`, `world_events` and
`scoring_rules`: a trainee who can read this endpoint must learn nothing a briefing would not tell
them (SPEC §2, D3)." The model below therefore has no field through which any of those could
arrive, and `app.application.scenarios.queries.scenario_version_trainee_summary` builds its input
by naming each allowed field rather than by deleting keys from a dump.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.ports.scenario_repository import (
    StoredScenarioListing,
    StoredScenarioVersionDetail,
)
from app.application.scenarios.queries import (
    CHECKED_RULE_COUNT,
    TraineeSummary,
    ValidationReport,
)
from app.domain.enums import AgeGroup, CallerRelationship, RoleType

__all__ = [
    "ScenarioImportRequestSchema",
    "ScenarioSummarySchema",
    "ScenarioValidationIssueSchema",
    "ScenarioValidationReportSchema",
    "ScenarioVersionListItemSchema",
    "ScenarioVersionTraineeSummarySchema",
    "scenario_summary_schema",
    "trainee_summary_schema",
    "validation_report_schema",
    "version_list_item_schema",
]


class ScenarioSummarySchema(ApiModel):
    """`openapi.yaml`'s `ScenarioSummary` — "identity only (D4): slug and title, never content"."""

    scenario_id: UUID
    slug: str
    title_ru: str
    version_count: int = Field(ge=0)
    latest_version: int | None = Field(default=None, ge=1)


class ScenarioVersionListItemSchema(ApiModel):
    """`openapi.yaml`'s `ScenarioVersionListItem`."""

    id: UUID
    scenario_id: UUID
    schema_version: int = Field(ge=1)
    version: int = Field(ge=1)
    title: str
    description: str
    difficulty: int
    role_chain: list[RoleType]
    content_sha256: str
    locked_at: datetime | None = None
    created_at: datetime


class ScenarioVersionTraineeSummarySchema(ApiModel):
    """`openapi.yaml`'s `ScenarioVersionTraineeSummary` — see this module's docstring."""

    id: UUID
    scenario_id: UUID
    scenario_slug: str
    version: int = Field(ge=1)
    title: str
    description: str
    difficulty: int
    role_chain: list[RoleType]
    caller_display_ru: str
    caller_language: str
    caller_age_group: AgeGroup
    caller_relationship: CallerRelationship
    estimated_duration_seconds: int | None = Field(default=None, ge=0)
    resource_count: int = Field(ge=0)


class ScenarioImportRequestSchema(ApiModel):
    """`openapi.yaml`'s `ScenarioImportRequest`.

    `content` is the complete document as a string. It is parsed from the request body in memory
    and written straight into `scenario_versions.content`; no temporary file is ever created.
    """

    format: Literal["YAML", "JSON"]
    content: str
    source_path: str | None = None


class ScenarioValidationIssueSchema(ApiModel):
    """`openapi.yaml`'s `ScenarioValidationIssue` — one §30.8 violation."""

    rule_number: int = Field(ge=1, le=30)
    severity: Literal["ERROR", "WARNING"]
    location: str
    message: str
    fact_id: str | None = None
    field_path: str | None = None


class ScenarioValidationReportSchema(ApiModel):
    """`openapi.yaml`'s `ScenarioValidationReport`.

    `checked_rule_count` is a `const: 30`: "The complete §30.8 list is always run; a partial run is
    never reported as valid."
    """

    valid: bool
    scenario_slug: str | None = None
    version: int | None = Field(default=None, ge=1)
    schema_version: int | None = Field(default=None, ge=1)
    content_sha256: str | None = None
    issues: list[ScenarioValidationIssueSchema]
    checked_rule_count: Literal[30] = CHECKED_RULE_COUNT


def scenario_summary_schema(listing: StoredScenarioListing) -> ScenarioSummarySchema:
    """`StoredScenarioListing` → `ScenarioSummary`."""
    return ScenarioSummarySchema(
        scenario_id=UUID(str(listing.scenario_id)),
        slug=listing.slug,
        title_ru=listing.title_ru,
        version_count=listing.version_count,
        latest_version=listing.latest_version,
    )


def version_list_item_schema(
    detail: StoredScenarioVersionDetail,
) -> ScenarioVersionListItemSchema:
    """`StoredScenarioVersionDetail` → `ScenarioVersionListItem`."""
    return ScenarioVersionListItemSchema(
        id=UUID(str(detail.scenario_version_id)),
        scenario_id=UUID(str(detail.scenario_id)),
        schema_version=detail.schema_version,
        version=detail.version,
        title=detail.title,
        description=detail.description,
        difficulty=detail.difficulty,
        role_chain=list(detail.role_chain),
        content_sha256=detail.content_sha256,
        locked_at=detail.locked_at,
        created_at=detail.created_at,
    )


def trainee_summary_schema(summary: TraineeSummary) -> ScenarioVersionTraineeSummarySchema:
    """`TraineeSummary` → `ScenarioVersionTraineeSummary`."""
    return ScenarioVersionTraineeSummarySchema(
        id=UUID(str(summary.scenario_version_id)),
        scenario_id=UUID(str(summary.scenario_id)),
        scenario_slug=summary.scenario_slug,
        version=summary.version,
        title=summary.title,
        description=summary.description,
        difficulty=summary.difficulty,
        role_chain=list(summary.role_chain),
        caller_display_ru=summary.caller_display_ru,
        caller_language=summary.caller_language,
        caller_age_group=summary.caller_age_group,
        caller_relationship=summary.caller_relationship,
        estimated_duration_seconds=summary.estimated_duration_seconds,
        resource_count=summary.resource_count,
    )


def validation_report_schema(report: ValidationReport) -> ScenarioValidationReportSchema:
    """`ValidationReport` → `ScenarioValidationReport`."""
    return ScenarioValidationReportSchema(
        valid=report.valid,
        scenario_slug=report.scenario_slug,
        version=report.version,
        schema_version=report.schema_version,
        content_sha256=report.content_sha256,
        issues=[
            ScenarioValidationIssueSchema(
                rule_number=issue.rule_number,
                severity="WARNING" if issue.severity == "WARNING" else "ERROR",
                location=issue.location,
                message=issue.message,
                field_path=issue.field_path,
            )
            for issue in report.issues
        ],
    )
