"""`reports` router — the whole `reports` tag (`openapi.yaml`; SPEC §27, §28, §29; D11).

Two routers, because the contract puts the operations under two prefixes:

* `router` — `/api/v1/reports/{session_id}`: `getSessionReport` (the full SPEC §29 envelope),
  `rescoreSession` (E15-B), `listInferenceMetrics` (SPEC §27) and, appended below in their own
  marked section, the two explanation operations;
* `audio_router` — `/api/v1/sessions/{session_id}/audio/{audio_segment_id}`: `getAudioSegment`,
  which is tagged `reports` but lives under the session path because it is a session's recording,
  plus (I5 E40) `getAudioSegmentMp3` at the same resource's `/mp3` sub-path.

`rescoreSession` is the "re-score equality endpoint" `docs/hld/90-tbd-epics.md`'s E15 row names
explicitly: it re-runs `score()` over the stored log and reports whether the result still equals
what `score_results` holds (SPEC §28, §42 test 9, D11). `getSessionReport`, by contrast, **reads**
the stored score and never recomputes it (E16 R1) — the two endpoints exist to be different.

`getAudioSegment` returns a `Response` rather than a `response_model`: its body is WAV bytes, and
it is the one operation here whose status code depends on the request (`200` without a `Range`,
`206` with one).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import ContainerDep
from app.api.export_headers import content_disposition
from app.api.schemas.comments import (
    ResultCommentListSchema,
    ResultCommentRequestSchema,
    ResultCommentViewSchema,
    result_comment_schema,
)
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
from app.api.security import AdminOrInstructorDep, CurrentUserDep
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.report_explanation_repository import ExplanationAudience
from app.application.ports.report_exporter import (
    PDF_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    generated_at_moscow,
)
from app.application.reports.list_inference_metrics import DEFAULT_LIMIT, MAX_LIMIT
from app.application.reports.ml_audit import AuditReport
from app.application.reports.session_report_export import session_report_export_document
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


@router.post(
    "/{session_id}/ml-audit",
    operation_id="generateMLAudit",
    summary="Advisory atomic ML audit; never changes official scores.",
    response_model=AuditReport,
    status_code=200,
)
async def generate_ml_audit(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    regenerate: bool = False,
) -> AuditReport:
    return await container.ml_audit_service().generate(
        SessionId(session_id),
        user,
        regenerate=regenerate,
    )


@router.get(
    "/{session_id}/ml-audit",
    operation_id="getMLAudit",
    summary="Read the stored ML audit for this viewer's visible inputs.",
    response_model=AuditReport | None,
    status_code=200,
)
async def get_ml_audit(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
) -> AuditReport | None:
    return await container.ml_audit_service().get(SessionId(session_id), user)


# --- I7 E46b (owner item 6): the session report has no CSV, so it goes straight to Excel/PDF ----


@router.get(
    "/{session_id}/export",
    operation_id="getSessionReportExport",
    summary="The session report as Excel or PDF (`?format=`, same access as getSessionReport).",
    status_code=200,
    response_class=Response,
)
async def get_session_report_export(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    format: Annotated[Literal["xlsx", "pdf"], Query(description="I7 E46b: `xlsx` or `pdf`.")],
) -> Response:
    """`getSessionReport`'s own view, filtered per viewer the same way, rendered as a file — no
    CSV precedent to extend (the session report never had one), so this is a sibling endpoint
    rather than a `format=` addition to `getSessionReport` itself (whose `response_model` stays
    JSON)."""
    view = await container.get_session_report()(SessionId(session_id), user)
    # (I7 E57) Building and rendering the file is CPU-bound: a worker thread, never the loop.
    document = await asyncio.to_thread(
        session_report_export_document,
        view,
        filters_line="",
        generated_at=generated_at_moscow(container.clock),
    )
    if format == "xlsx":
        return Response(
            content=await asyncio.to_thread(container.report_exporter.render_xlsx, document),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition(
                    f"Отчёт по сессии {session_id}.xlsx", f"session-{session_id}-report.xlsx"
                )
            },
        )
    return Response(
        content=await asyncio.to_thread(container.report_exporter.render_pdf, document),
        media_type=PDF_MEDIA_TYPE,
        headers={
            "Content-Disposition": content_disposition(
                f"Отчёт по сессии {session_id}.pdf", f"session-{session_id}-report.pdf"
            )
        },
    )


# --- end I7 E46b -----------------------------------------------------------------------------


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


# --- I5 E40: MP3 download (Q-E16-3 variant b, ТЗ ¶383) -------------------------------------------


@audio_router.get(
    "/{session_id}/audio/{audio_segment_id}/mp3",
    operation_id="getAudioSegmentMp3",
    summary="Download one audio segment as MP3.",
    status_code=200,
    response_class=Response,
)
async def get_audio_segment_mp3(
    session_id: UUID,
    audio_segment_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
) -> Response:
    """Mono, 64 kbit/s CBR, encoded on demand and cached under `DATA_DIR/recordings` by content
    hash (I5 E40, Q-E16-3 variant b: ТЗ ¶383 requires MP3 alongside the WAV of `getAudioSegment`).
    `410 AUDIO_PURGED` once retention removed the recording; the access rule is `getAudioSegment`'s
    (E16 R3/R7) — a trainee refused the WAV gets the same refusal here."""
    served = await container.serve_audio_segment_mp3()(
        SessionId(session_id), audio_segment_id, user
    )
    headers = {"Content-Length": str(len(served.content))}
    return Response(
        content=served.content, status_code=200, media_type=served.media_type, headers=headers
    )


# --- end I5 E40 -----------------------------------------------------------------------------------


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


# --- I4 E32 instructor misc: session comments (`71-i4-wave4.md` §71.9, ТЗ ¶236, ¶237) ------------


@router.get(
    "/{session_id}/comments",
    operation_id="listSessionComments",
    summary="Instructor comments on a session result — ТЗ ¶236, ¶237, ¶267.",
    response_model=ResultCommentListSchema,
    status_code=200,
)
async def list_session_comments(
    session_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> ResultCommentListSchema:
    """INSTRUCTOR / ADMIN always; the trainee exactly when the report is visible to them (the
    same `report_visibility` gate, else `403 REPORT_NOT_RELEASED`). Superseded rows are returned
    with `superseded: true`."""
    comments = await container.list_session_comments()(SessionId(session_id), user)
    return ResultCommentListSchema(items=[result_comment_schema(c) for c in comments])


@router.post(
    "/{session_id}/comments",
    operation_id="createSessionComment",
    summary="Add a comment (or an edit, as a new row) to a session result (INSTRUCTOR / ADMIN).",
    response_model=ResultCommentViewSchema,
    status_code=201,
)
async def create_session_comment(
    session_id: UUID,
    body: ResultCommentRequestSchema,
    container: ContainerDep,
    user: AdminOrInstructorDep,
) -> ResultCommentViewSchema:
    comment = await container.create_session_comment()(
        SessionId(session_id), user, body.to_command()
    )
    return result_comment_schema(comment)


# --- end I4 E32 -----------------------------------------------------------------------------
