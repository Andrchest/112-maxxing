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

import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal
from uuid import UUID

import yaml
from fastapi import APIRouter, Query, Response

from app.api.deps import ContainerDep
from app.api.export_headers import content_disposition
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
    include_archived: Annotated[bool, Query()] = False,
) -> ScenarioPage:
    """One page of scenario identities. Never content (D4).

    `include_archived` (additive, I4 E32): `false` (the default) hides every archived scenario —
    every picker therefore sees only active scenarios unless it asks for archived ones too.
    """
    listings, total = await container.list_scenarios()(
        limit=limit, offset=offset, include_archived=include_archived
    )
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


# --- I4 E32 instructor misc: archive (`71-i4-wave4.md` §71.9, ТЗ ¶229) ---------------------------


@router.post(
    "/{scenario_id}/archive",
    operation_id="archiveScenario",
    summary="Archive (= «удалить неактуальный») a scenario (INSTRUCTOR / ADMIN).",
    response_model=ScenarioSummarySchema,
    status_code=200,
)
async def archive_scenario(
    scenario_id: UUID, container: ContainerDep, _user: AdminOrInstructorDep
) -> ScenarioSummarySchema:
    """Sets `scenarios.archived_at` (idempotent). Existing sessions and versions are untouched."""
    listing = await container.archive_scenario()(ScenarioId(scenario_id))
    return scenario_summary_schema(listing)


@router.post(
    "/{scenario_id}/unarchive",
    operation_id="unarchiveScenario",
    summary="Return an archived scenario to the pickers (INSTRUCTOR / ADMIN).",
    response_model=ScenarioSummarySchema,
    status_code=200,
)
async def unarchive_scenario(
    scenario_id: UUID, container: ContainerDep, _user: AdminOrInstructorDep
) -> ScenarioSummarySchema:
    listing = await container.unarchive_scenario()(ScenarioId(scenario_id))
    return scenario_summary_schema(listing)


# --- end I4 E32 -----------------------------------------------------------------------------


# --- I7 E53: download a scenario version (G14a; ТЗ ¶222 «Создавать, редактировать…», ¶229) ------

YAML_MEDIA_TYPE = "application/yaml"
JSON_MEDIA_TYPE = "application/json"


def _render_document(document: Mapping[str, Any], format: str) -> str:
    """The stored document as YAML (block style, Cyrillic unescaped) or indented JSON.

    Either form parses back to the same mapping through `parse_scenario_document`, so uploading the
    file unchanged is the idempotent re-import.
    """
    if format == "json":
        return json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    rendered: str = yaml.safe_dump(
        dict(document), allow_unicode=True, sort_keys=False, default_flow_style=False, width=100
    )
    return rendered


@router.get(
    "/versions/{scenario_version_id}/document",
    operation_id="getScenarioVersionDocument",
    summary="Download a stored scenario version as YAML or JSON (INSTRUCTOR / ADMIN).",
    status_code=200,
    response_class=Response,
)
async def get_scenario_version_document(
    scenario_version_id: UUID,
    container: ContainerDep,
    _user: AdminOrInstructorDep,
    format: Annotated[
        Literal["yaml", "json"], Query(description="I7 E53: `yaml` (default) or `json`.")
    ] = "yaml",
) -> Response:
    """The version's full document — instructor-only, because it carries `world_truth`, the caller
    layers and the scoring rules a trainee must never read (D3). Audited like every request (E25).
    """
    detail, document = await container.get_scenario_version_document()(
        ScenarioVersionId(scenario_version_id)
    )
    file_name = f"{detail.scenario_slug}-v{detail.version}.{format}"
    ascii_name = file_name if file_name.isascii() else f"scenario-v{detail.version}.{format}"
    return Response(
        content=_render_document(document, format).encode("utf-8"),
        media_type=YAML_MEDIA_TYPE if format == "yaml" else JSON_MEDIA_TYPE,
        headers={"Content-Disposition": content_disposition(file_name, ascii_name)},
    )


# --- end I7 E53 -------------------------------------------------------------------------------
