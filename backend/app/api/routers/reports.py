"""`reports` router — the whole `reports` tag (`openapi.yaml`; SPEC §27, §28, §29; D11).

Two routers, because the contract puts the operations under two prefixes:

* `router` — `/api/v1/reports/{session_id}`: `getSessionReport` (the full SPEC §29 envelope),
  `rescoreSession` (E15-B), `listInferenceMetrics` (SPEC §27) and, appended below in their own
  marked section, the two explanation operations;
* `audio_router` — `/api/v1/sessions/{session_id}/audio/{audio_segment_id}`: `getAudioSegment`,
  which is tagged `reports` but lives under the session path because it is a session's recording.

`rescoreSession` is the "re-score equality endpoint" `docs/hld/90-tbd-epics.md`'s E15 row names
explicitly: it re-runs `score()` over the stored log and reports whether the result still equals
what `score_results` holds (SPEC §28, §42 test 9, D11). `getSessionReport`, by contrast, **reads**
the stored score and never recomputes it (E16 R1) — the two endpoints exist to be different.

`getAudioSegment` returns a `Response` rather than a `response_model`: its body is WAV bytes, and
it is the one operation here whose status code depends on the request (`200` without a `Range`,
`206` with one).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import ContainerDep
from app.api.schemas.reports import (
    GenerateExplanationRequestSchema,
    InferenceMetricsPageSchema,
    ReportExplanationSchema,
    RescoreRequestSchema,
    RescoreResultSchema,
    SessionReportSchema,
    inference_metrics_page_schema,
    report_explanation_schema,
    rescore_result_schema,
    session_report_schema,
)
from app.api.security import CurrentUserDep
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.report_explanation_repository import ExplanationAudience
from app.application.reports.list_inference_metrics import DEFAULT_LIMIT, MAX_LIMIT
from app.application.scoring.rescore_session import RescoreOutcome
from app.domain.common.ids import SessionId

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
audio_router = APIRouter(prefix="/api/v1/sessions", tags=["reports"])


@router.get(
    "/{session_id}",
    operation_id="getSessionReport",
    summary="The post-session report (SPEC §29, every item).",
    response_model=SessionReportSchema,
    status_code=200,
)
async def get_session_report(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
) -> SessionReportSchema:
    """Every SPEC §29 item, filtered per viewer by one pure rule
    (`app.application.reports.visibility`). The stored score is read, never recomputed (E16 R1);
    an unfinished, aborted or unscored session is refused with `409 REPORT_NOT_READY`."""
    view = await container.get_session_report()(SessionId(session_id), user)
    return session_report_schema(view)


@router.get(
    "/{session_id}/inference-metrics",
    operation_id="listInferenceMetrics",
    summary="Inference latency telemetry for one session (SPEC §27).",
    response_model=InferenceMetricsPageSchema,
    status_code=200,
)
async def list_inference_metrics(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    component: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> InferenceMetricsPageSchema:
    """The rows plus the session-wide aggregate. `total` counts the rows that match `component`
    before `limit`; `timing_metrics` is the whole session's and does not move with the filter."""
    page = await container.list_inference_metrics()(
        SessionId(session_id), user, component=component, limit=limit
    )
    return inference_metrics_page_schema(page)


@audio_router.get(
    "/{session_id}/audio/{audio_segment_id}",
    operation_id="getAudioSegment",
    summary="Download one audio segment, with HTTP Range.",
    status_code=200,
    response_class=Response,
)
async def get_audio_segment(
    session_id: UUID,
    audio_segment_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """WAV bytes, with real Range support: `200` for the whole segment, `206` + `Content-Range`
    for a range, `416` for an unsatisfiable one and `410 AUDIO_PURGED` once retention removed the
    recording (D9). The access rule is the transcript's (E16 R3/R7)."""
    served = await container.serve_audio_segment()(
        SessionId(session_id), audio_segment_id, user, range_header=range_header
    )
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(len(served.content))}
    if served.content_range is not None:
        headers["Content-Range"] = served.content_range
    return Response(
        content=served.content,
        status_code=served.status_code,
        media_type=served.media_type,
        headers=headers,
    )


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


# --- explanation routes (E16-B) ---
#
# `openapi.yaml`'s `getReportExplanation` (`:1460-1481`) declares only `SessionIdParam` — no
# `audience` query parameter — even though `report_explanations` is keyed `(session_id,
# audience)` and up to two rows (TRAINEE, INSTRUCTOR) can exist for one session. The contract is
# silent on how the GET selects between them; the reading closest to SPEC (§2's "the explanation
# is displayed beside the scores" for whoever is looking at them) is the caller's own role: an
# INSTRUCTOR/ADMIN reads the INSTRUCTOR-toned explanation, a TRAINEE reads their own TRAINEE-toned
# one. `GetExplanation` itself still takes `audience` as an explicit parameter (so it is testable
# without a route), but nothing about it is client-supplied. See this task's report ("HLD gaps").


def _viewer_audience(user: AuthenticatedUser) -> ExplanationAudience:
    return "INSTRUCTOR" if user.is_instructor_or_admin else "TRAINEE"


@router.get(
    "/{session_id}/explanation",
    operation_id="getReportExplanation",
    summary="The stored LLM explanation of an already-computed report.",
    response_model=ReportExplanationSchema,
    status_code=200,
)
async def get_report_explanation(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
) -> ReportExplanationSchema:
    """A separate resource from the report on purpose (D11): generated only from an already
    persisted `ScoreReport`, stored separately, `404` when none exists for this viewer's
    audience. A stale explanation (a rescore happened since) is still returned, with its own
    `score_report_checksum`, so the client can show it is out of date rather than have it vanish."""
    explanation = await container.get_explanation()(
        SessionId(session_id), user, audience=_viewer_audience(user)
    )
    return report_explanation_schema(explanation)


@router.post(
    "/{session_id}/explanation",
    operation_id="generateReportExplanation",
    summary="Generate the LLM explanation of an already-computed report.",
    response_model=ReportExplanationSchema,
    status_code=201,
)
async def generate_report_explanation(
    session_id: UUID,
    body: GenerateExplanationRequestSchema | None,
    container: ContainerDep,
    user: CurrentUserDep,
) -> ReportExplanationSchema:
    """Reads the persisted `ScoreReport` and produces prose; **cannot alter scores** — the use
    case has no write path to `score_results`/`score_evidence` (SPEC §2, D11, R8). `409
    REPORT_NOT_READY` before scoring has run, `409 EXPLANATION_ALREADY_EXISTS` on a second call
    without `regenerate: true`, `503 LLM_UNAVAILABLE` if the model does not answer."""
    regenerate = False if body is None else body.regenerate
    audience: ExplanationAudience = "TRAINEE" if body is None else body.audience
    explanation = await container.generate_explanation()(
        SessionId(session_id), user, audience=audience, regenerate=regenerate
    )
    return report_explanation_schema(explanation)
