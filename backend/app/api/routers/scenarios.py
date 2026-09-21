"""`scenarios` router — the six scenario operations of `openapi.yaml` (D3, D4).

Four reads any authenticated caller may make, and two writes `openapi.yaml` restricts to
`INSTRUCTOR` / `ADMIN` ("Import a scenario version file (INSTRUCTOR / ADMIN)", "Validate a
scenario file without importing it (INSTRUCTOR / ADMIN)").

`getScenarioVersionSummary` is readable by a trainee **because** it is the trainee-safe
projection — that is the whole reason the endpoint is separate from a "get version" that does not
exist. `getScenarioValidationReport` is instructor-only: `openapi.yaml` gives it a `403`, and a
validation report names the scenario's internal structure.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.api.schemas.common import PageSchema
from app.api.schemas.scenarios import (
    ScenarioImportRequestSchema,
    ScenarioSummarySchema,
    ScenarioValidationReportSchema,
    ScenarioVersionListItemSchema,
    ScenarioVersionTraineeSummarySchema,
    scenario_summary_schema,
    trainee_summary_schema,
    validation_report_schema,
    version_list_item_schema,
)
from app.api.security import AdminOrInstructorDep, CurrentUserDep
from app.application.scenarios.import_scenario_version import (
    ImportScenarioVersionCommand,
    parse_scenario_document,
)
from app.domain.common.ids import ScenarioId, ScenarioVersionId

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])

ScenarioPage = PageSchema[ScenarioSummarySchema]
ScenarioVersionPage = PageSchema[ScenarioVersionListItemSchema]


@router.get(
    "",
    operation_id="listScenarios",
    summary="List scenarios (identity only — slug and title).",
    response_model=ScenarioPage,
    status_code=200,
)
async def list_scenarios(
    container: ContainerDep,
    _user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ScenarioPage:
    """One page of scenario identities. Never content (D4)."""
    listings, total = await container.list_scenarios()(limit=limit, offset=offset)
    return ScenarioPage(
        items=[scenario_summary_schema(listing) for listing in listings], total=total
    )


@router.get(
    "/{scenario_id}/versions",
    operation_id="listScenarioVersions",
    summary="List the versions of one scenario.",
    response_model=ScenarioVersionPage,
    status_code=200,
)
async def list_scenario_versions(
    scenario_id: UUID, container: ContainerDep, _user: CurrentUserDep
) -> ScenarioVersionPage:
    """Versions, newest first. `locked_at` is non-null once a session used the version (D4)."""
    versions = await container.list_scenario_versions()(ScenarioId(scenario_id))
    return ScenarioVersionPage(
        items=[version_list_item_schema(version) for version in versions], total=len(versions)
    )


@router.get(
    "/versions/{scenario_version_id}/summary",
    operation_id="getScenarioVersionSummary",
    summary="Trainee-safe summary of a scenario version.",
    response_model=ScenarioVersionTraineeSummarySchema,
    status_code=200,
)
async def get_scenario_version_summary(
    scenario_version_id: UUID, container: ContainerDep, _user: CurrentUserDep
) -> ScenarioVersionTraineeSummarySchema:
    """The projection a trainee may read: nothing a briefing would not tell them (D3, SPEC §2)."""
    summary = await container.get_scenario_version_summary()(ScenarioVersionId(scenario_version_id))
    return trainee_summary_schema(summary)


@router.get(
    "/versions/{scenario_version_id}/validation-report",
    operation_id="getScenarioValidationReport",
    summary="The stored validation report of an imported version.",
    response_model=ScenarioValidationReportSchema,
    status_code=200,
)
async def get_scenario_validation_report(
    scenario_version_id: UUID, container: ContainerDep, _user: AdminOrInstructorDep
) -> ScenarioValidationReportSchema:
    """The §30.8 verdict recorded at import time, re-derived from the immutable content (D4)."""
    report = await container.get_scenario_validation_report()(
        ScenarioVersionId(scenario_version_id)
    )
    return validation_report_schema(report)


@router.post(
    "/import",
    operation_id="importScenarioVersion",
    summary="Import a scenario version file (INSTRUCTOR / ADMIN).",
    response_model=ScenarioVersionListItemSchema,
    status_code=201,
)
async def import_scenario_version(
    body: ScenarioImportRequestSchema, container: ContainerDep, _user: AdminOrInstructorDep
) -> ScenarioVersionListItemSchema:
    """Validate the complete document, then store it.

    Re-importing the same version with the same content is a no-op that still answers `201` with
    the stored row, so a retried upload is harmless. Changed content under an existing version is
    `409 SCENARIO_VERSION_LOCKED` or `409 SCENARIO_VERSION_EXISTS`; an invalid document is
    `422 SCENARIO_INVALID` carrying the complete report (D4).
    """
    detail = await container.import_scenario_version()(
        ImportScenarioVersionCommand(
            format=body.format, content=body.content, source_path=body.source_path
        )
    )
    return version_list_item_schema(detail)


@router.post(
    "/validate",
    operation_id="validateScenarioFile",
    summary="Validate a scenario file without importing it (INSTRUCTOR / ADMIN).",
    response_model=ScenarioValidationReportSchema,
    status_code=200,
)
async def validate_scenario_file(
    body: ScenarioImportRequestSchema, container: ContainerDep, _user: AdminOrInstructorDep
) -> ScenarioValidationReportSchema:
    """A dry run that writes nothing and **always answers `200`**.

    `openapi.yaml`: "Always `200`: an invalid document is reported in the body as `valid: false`
    plus issues, because this endpoint's purpose is authoring feedback, not command execution."
    A document that does not even parse is the one exception the contract cannot express, and it
    raises `422 SCENARIO_INVALID` — there is no report to put in a `200` body when there is no
    document.
    """
    document = parse_scenario_document(body.content, body.format)
    report = container.validate_scenario_document()(document)
    return validation_report_schema(report)
