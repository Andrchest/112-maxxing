"""`instructor` router — the instructor console's own operations (`openapi.yaml` tag `instructor`).

The tag's description is the reason this module exists separately: "Instructor console. The only
place WorldTruth and gate internals are exposed." Keeping it a module of its own means the
operations that may show the hidden layers are enumerable at a glance, which is the reviewability
half of D3's structural visibility.

Exactly one operation lives here today.

TODO(E17): `getInstructorSessionOverview` (`GET /api/v1/instructor/sessions/{session_id}/overview`,
`openapi.yaml`) — the **live** instructor payload: `WorldTruth`, `CallerBelief`, `FactAccessGate`
decisions and the assignments, for a session still running. It belongs to E17 ("Full-cycle and
multi-role modes — instructor live overview", `docs/hld/90-tbd-epics.md`), not to E16: E16 owns the
*post-session* report, and the two read different things at different times. Its `assignments`
field is the same N-leg projection `app.application.reports.dds_decisions` already builds for the
report, so E17 can reuse that function rather than write a second one.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.api.schemas.reports import ReportReleaseViewSchema, report_release_schema
from app.api.security import CurrentUserDep
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
