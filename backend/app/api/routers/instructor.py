"""`instructor` router — the instructor console's own operations (`openapi.yaml` tag `instructor`).

The tag's description is the reason this module exists separately: "Instructor console. The only
place WorldTruth and gate internals are exposed." Keeping it a module of its own means the
operations that may show the hidden layers are enumerable at a glance, which is the reviewability
half of D3's structural visibility.

Two operations live here: `releaseReportToTrainee` (E16) and `getInstructorSessionOverview` (E17
R4) — the **live** instructor payload: `WorldTruth`, `CallerBelief`, `FactAccessGate` decisions and
the assignments, for a session in any state after creation. It is distinct from E16's
`getSessionReport`: that one is the post-session read, gated on `COMPLETED` and on release; this
one is the live console's own read and has neither gate — an instructor may open it the moment a
session is created and again after it completes or aborts.

**`inference_health` is folded here, not in the use case.** `app.api.routers.health` explains why
the health fold "lives [in the API layer] rather than in the application layer": it is a
precedence rule over `ComponentReading`s the health-probe port already produced, nothing more, and
`Container.health_probes` is the same set `getHealthReady` probes. This route runs the identical
fold (`overall_status`, the same `HEALTH_COMPONENTS` ordering) rather than inventing a second one.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter

from app.api.container import HEALTH_COMPONENTS, REQUIRED_HEALTH_COMPONENTS
from app.api.deps import ContainerDep
from app.api.routers.health import overall_status
from app.api.schemas.health import (
    ComponentHealthSchema,
    HealthReadyResponseSchema,
    component_health_schema,
)
from app.api.schemas.instructor import (
    InstructorSessionOverviewSchema,
    instructor_session_overview_schema,
)
from app.api.schemas.reports import ReportReleaseViewSchema, report_release_schema
from app.api.security import CurrentUserDep
from app.application.ports.health_probe import ComponentReading
from app.domain.common.ids import SessionId

router = APIRouter(prefix="/api/v1/instructor", tags=["instructor"])


@router.post(
    "/sessions/{session_id}/report/release",
    operation_id="releaseReportToTrainee",
    summary="Release the report to the trainee.",
    response_model=ReportReleaseViewSchema,
    status_code=200,
)
async def release_report_to_trainee(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
) -> ReportReleaseViewSchema:
    """A visibility flag, not a scoring operation (D11): it emits no event and touches no score.

    Idempotent — a second call returns the first release unchanged. The session must be
    `COMPLETED`, else `409 REPORT_NOT_READY`.
    """
    release = await container.release_report_to_trainee()(SessionId(session_id), user)
    return report_release_schema(SessionId(session_id), release)


@router.get(
    "/sessions/{session_id}/overview",
    operation_id="getInstructorSessionOverview",
    summary="Live instructor overview — includes WorldTruth and gate internals.",
    response_model=InstructorSessionOverviewSchema,
    status_code=200,
)
async def get_instructor_session_overview(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
) -> InstructorSessionOverviewSchema:
    """`x-visibility: INSTRUCTOR`; a `TRAINEE` gets `403 FORBIDDEN_FOR_ROLE` (`openapi.yaml`).

    A read: it emits no event and writes no row, in every session state after creation.
    """
    view = await container.get_instructor_session_overview()(SessionId(session_id), user)
    readings = await asyncio.gather(*(probe.check() for probe in container.health_probes))
    health = HealthReadyResponseSchema(
        overall=overall_status(readings, required=REQUIRED_HEALTH_COMPONENTS),
        components=_ordered_components(readings),
        required_components=list(REQUIRED_HEALTH_COMPONENTS),
        require_inference_ready=container.settings.require_inference_ready,
        model_profile=container.settings.model_profile,  # type: ignore[arg-type]
    )
    return instructor_session_overview_schema(view, inference_health=health)


def _ordered_components(readings: list[ComponentReading]) -> list[ComponentHealthSchema]:
    """The readings in `HEALTH_COMPONENTS` order — the same ordering `getHealthReady` uses, so the
    instructor console's health row never reshuffles relative to the health page's."""
    by_component = {reading.component: reading for reading in readings}
    ordered = [by_component[name] for name in HEALTH_COMPONENTS if name in by_component]
    ordered.extend(reading for reading in readings if reading.component not in HEALTH_COMPONENTS)
    return [component_health_schema(reading) for reading in ordered]
