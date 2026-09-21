"""`reports` router — `rescoreSession` only (epic E15-B; `openapi.yaml` tag `reports`, SPEC §28/§29,
D11).

`rescoreSession` is the "re-score equality endpoint" `docs/hld/90-tbd-epics.md`'s E15 row names
explicitly: it re-runs `score()` over the stored log and reports whether the result still equals
what `score_results` holds (SPEC §28, §42 test 9, D11).

TODO(E16): the rest of the `reports` tag is out of scope here (R9) — `getSessionReport` (the full
SPEC §29 envelope: timeline, transcript, audio, truth-vs-card diff, DDS decisions, resource
timeline, timing metrics), `getReportExplanation` / `generateReportExplanation` (the LLM
explanation layer, which may only read an already-persisted `ScoreReport` and never write to
`score_results`/`score_evidence`, SPEC §2/§29) and `listInferenceMetrics` (SPEC §27 telemetry).
None of the four has a route registered; adding one is this file's next slice.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.api.schemas.reports import (
    RescoreRequestSchema,
    RescoreResultSchema,
    rescore_result_schema,
)
from app.api.security import CurrentUserDep
from app.application.scoring.rescore_session import RescoreOutcome
from app.domain.common.ids import SessionId

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.post(
    "/{session_id}/rescore",
    operation_id="rescoreSession",
    summary="Re-score deterministically from the event log.",
    response_model=RescoreResultSchema,
    status_code=200,
)
async def rescore_session(
    session_id: UUID,
    body: RescoreRequestSchema | None,
    container: ContainerDep,
    user: CurrentUserDep,
) -> RescoreResultSchema:
    """`score()` again over `(scenario_versions.content, ordered session_events)`; `persist: false`
    (the default, and an absent body) leaves `score_results` / `score_evidence` untouched."""
    persist = False if body is None else body.persist
    outcome: RescoreOutcome = await container.rescore_session()(
        SessionId(session_id), user, persist=persist
    )
    return rescore_result_schema(outcome)
