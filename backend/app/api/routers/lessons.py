"""`lessons` router — `createLesson`, `listLessons`, `getLesson`, `startLesson`, `abortLesson`,
`getLessonReport`, `releaseLessonReport` (HLD 70 §70.3, `i3-openapi-delta.yaml`, D15), and I3
E9a's `requestWeightProposals`, `getWeightProposals`, `acceptWeightProposals` (§70.3.7): the
proposals are stored and never applied until the instructor accepts them.

The runner wiring mirrors `sessions`' (D7): `startLesson` adopts the lesson into the
`LessonRunner` **after** its commit and then ticks it once, so a card due at offset 0 arrives with
the response rather than one interval later; `abortLesson` releases the lesson's runner and every
aborted card's session runner after the commits. `SIM_RUNNER_ENABLED=false` skips adoption and
release (API tests drive `container.lesson_runner.tick_now` themselves); the immediate tick of
`startLesson` still happens, exactly as a session command's tick-after-command does.

`releaseLessonReport` is pathed under `/api/v1/instructor` like `releaseReportToTrainee`, so it
lives on a second router of this module (`instructor_router`).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import ContainerDep
from app.api.schemas.comments import (
    ResultCommentListSchema,
    ResultCommentRequestSchema,
    ResultCommentViewSchema,
    result_comment_schema,
)
from app.api.schemas.common import PageSchema
from app.api.schemas.lessons import (
    LessonCreateRequestSchema,
    LessonDetailSchema,
    LessonListItemSchema,
    LessonReportSchema,
    WeightProposalAcceptRequestSchema,
    WeightProposalSetSchema,
    lesson_detail_schema,
    lesson_list_item_schema,
    lesson_report_schema,
    weight_proposal_set_schema,
)
from app.api.schemas.sessions import AbortSessionRequestSchema
from app.api.security import AdminOrInstructorDep, CurrentUserDep, actor_of
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.lessons.create_lesson import CreateLessonCommand
from app.application.lessons.queries import assemble_lesson_detail
from app.application.reports.csv_export import CSV_MEDIA_TYPE, lesson_report_csv
from app.domain.common.ids import LessonId
from app.domain.lesson.lesson import Lesson, LessonState
from app.domain.session.variants import PartialVariants

router = APIRouter(prefix="/api/v1/lessons", tags=["lessons"])
instructor_router = APIRouter(prefix="/api/v1/instructor", tags=["lessons"])

LessonPage = PageSchema[LessonListItemSchema]


@router.post(
    "",
    operation_id="createLesson",
    summary="Create a lesson (занятие) of N cards (INSTRUCTOR / ADMIN).",
    response_model=LessonDetailSchema,
    status_code=201,
)
async def create_lesson(
    body: LessonCreateRequestSchema, container: ContainerDep, user: AdminOrInstructorDep
) -> LessonDetailSchema:
    """Every card's session is created at once, each `READY`; nothing ticks until `startLesson`."""
    lesson = await container.create_lesson()(
        CreateLessonCommand(
            title_ru=body.title_ru,
            session_mode=body.session_mode,
            actor=actor_of(user),
            participants=body.domain_participants(),
            scenario_plan=tuple(entry.to_domain() for entry in body.scenario_plan),
            variants=(
                body.variants.to_domain() if body.variants is not None else PartialVariants()
            ),
            time_scale=body.time_scale,
            group_id=body.domain_group_id(),
            pass_criteria=(None if body.pass_criteria is None else body.pass_criteria.to_domain()),
        )
    )
    return await _detail(container, lesson)


@router.get(
    "",
    operation_id="listLessons",
    summary="List lessons — mine, or all for an instructor.",
    response_model=LessonPage,
    status_code=200,
)
async def list_lessons(
    container: ContainerDep,
    user: CurrentUserDep,
    scope: Annotated[str, Query(pattern="^(MINE|ALL)$")] = "MINE",
    state: LessonState | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LessonPage:
    """`scope=ALL` is INSTRUCTOR/ADMIN only (`403 FORBIDDEN_FOR_ROLE` for a trainee)."""
    items, total = await container.list_lessons()(
        viewer=user, scope=scope, state=state, limit=limit, offset=offset
    )
    return LessonPage(items=[lesson_list_item_schema(item) for item in items], total=total)


@router.get(
    "/{lesson_id}",
    operation_id="getLesson",
    summary="A lesson with its plan and the per-card status of every session.",
    response_model=LessonDetailSchema,
    status_code=200,
)
async def get_lesson(
    lesson_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> LessonDetailSchema:
    view = await container.get_lesson()(LessonId(lesson_id), user)
    return lesson_detail_schema(view)


@router.post(
    "/{lesson_id}/start",
    operation_id="startLesson",
    summary="Start the lesson (`CREATED → ACTIVE`); the LessonRunner then starts cards by arrival.",
    response_model=LessonDetailSchema,
    status_code=200,
)
async def start_lesson(
    lesson_id: UUID, container: ContainerDep, user: AdminOrInstructorDep
) -> LessonDetailSchema:
    started = await container.start_lesson()(LessonId(lesson_id), user)
    if container.settings.runner_enabled:
        container.lesson_runner.adopt(started.lesson_id)
    await container.lesson_runner.tick_now(started.lesson_id)
    return await _detail_by_id(container, started.lesson_id, user)


@router.post(
    "/{lesson_id}/abort",
    operation_id="abortLesson",
    summary="Abort the lesson and every non-terminal card session.",
    response_model=LessonDetailSchema,
    status_code=200,
)
async def abort_lesson(
    lesson_id: UUID,
    body: AbortSessionRequestSchema,
    container: ContainerDep,
    user: AdminOrInstructorDep,
) -> LessonDetailSchema:
    aborted, sessions = await container.abort_lesson()(LessonId(lesson_id), user, body.reason)
    if container.settings.runner_enabled:
        await container.lesson_runner.release(aborted.lesson_id)
        for session_id in sessions:
            await container.runner.release(session_id)
    return await _detail(container, aborted)


@router.get(
    "/{lesson_id}/report",
    operation_id="getLessonReport",
    summary="The N card reports of a completed lesson plus the weighted sum.",
    response_model=LessonReportSchema,
    status_code=200,
)
async def get_lesson_report(
    lesson_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> LessonReportSchema:
    view = await container.get_lesson_report()(LessonId(lesson_id), user)
    return lesson_report_schema(view)


@instructor_router.post(
    "/lessons/{lesson_id}/report/release",
    operation_id="releaseLessonReport",
    summary="Release every card report of the lesson to its trainees (idempotent, no event).",
    response_model=LessonDetailSchema,
    status_code=200,
)
async def release_lesson_report(
    lesson_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> LessonDetailSchema:
    released = await container.release_lesson_report()(LessonId(lesson_id), user)
    return await _detail(container, released)


# --- I4 E32 instructor misc: lesson comments (`71-i4-wave4.md` §71.9) ----------------------------


@router.get(
    "/{lesson_id}/comments",
    operation_id="listLessonComments",
    summary="Instructor comments on a lesson result (listSessionComments' lesson equivalent).",
    response_model=ResultCommentListSchema,
    status_code=200,
)
async def list_lesson_comments(
    lesson_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> ResultCommentListSchema:
    """Trainee access follows the lesson report's release (every card released)."""
    comments = await container.list_lesson_comments()(LessonId(lesson_id), user)
    return ResultCommentListSchema(items=[result_comment_schema(c) for c in comments])


@router.post(
    "/{lesson_id}/comments",
    operation_id="createLessonComment",
    summary="Add a comment (or an edit, as a new row) to a lesson result (INSTRUCTOR / ADMIN).",
    response_model=ResultCommentViewSchema,
    status_code=201,
)
async def create_lesson_comment(
    lesson_id: UUID,
    body: ResultCommentRequestSchema,
    container: ContainerDep,
    user: AdminOrInstructorDep,
) -> ResultCommentViewSchema:
    comment = await container.create_lesson_comment()(LessonId(lesson_id), user, body.to_command())
    return result_comment_schema(comment)


# --- end I4 E32 -----------------------------------------------------------------------------


@router.post(
    "/{lesson_id}/weight-proposals",
    operation_id="requestWeightProposals",
    summary="Ask for difficulty-weight proposals for every card (stored, never applied).",
    response_model=WeightProposalSetSchema,
    status_code=201,
)
async def request_weight_proposals(
    lesson_id: UUID, container: ContainerDep, user: AdminOrInstructorDep
) -> WeightProposalSetSchema:
    view = await container.request_weight_proposals()(LessonId(lesson_id), user)
    return weight_proposal_set_schema(view)


@router.get(
    "/{lesson_id}/weight-proposals",
    operation_id="getWeightProposals",
    summary="The lesson's latest weight proposals beside the current weights.",
    response_model=WeightProposalSetSchema,
    status_code=200,
)
async def get_weight_proposals(
    lesson_id: UUID, container: ContainerDep, _user: AdminOrInstructorDep
) -> WeightProposalSetSchema:
    return weight_proposal_set_schema(await container.get_weight_proposals()(LessonId(lesson_id)))


@router.post(
    "/{lesson_id}/weight-proposals/accept",
    operation_id="acceptWeightProposals",
    summary="Accept the chosen proposals into the plan's weights.",
    response_model=WeightProposalSetSchema,
    status_code=200,
)
async def accept_weight_proposals(
    lesson_id: UUID,
    body: WeightProposalAcceptRequestSchema,
    container: ContainerDep,
    user: AdminOrInstructorDep,
) -> WeightProposalSetSchema:
    view = await container.accept_weight_proposals()(LessonId(lesson_id), body.positions, user)
    return weight_proposal_set_schema(view)


async def _detail(container: ContainerDep, lesson: Lesson) -> LessonDetailSchema:
    async with container.unit_of_work() as uow:
        view = await assemble_lesson_detail(uow, lesson)
        await uow.commit()
    return lesson_detail_schema(view)


async def _detail_by_id(
    container: ContainerDep, lesson_id: LessonId, user: AuthenticatedUser
) -> LessonDetailSchema:
    return lesson_detail_schema(await container.get_lesson()(lesson_id, user))


# --- I4 E33 reports, statistics, CSV: `getLessonReportCsv` (`71-i4-wave4.md` §71.10) -------------


@router.get(
    "/{lesson_id}/report.csv",
    operation_id="getLessonReportCsv",
    summary="The lesson report as CSV (UTF-8 with BOM, `;`, Russian headers).",
    status_code=200,
    response_class=Response,
)
async def get_lesson_report_csv(
    lesson_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> Response:
    """`getLessonReport`'s own view rendered as a file — same access, same numbers (D11)."""
    view = await container.get_lesson_report()(LessonId(lesson_id), user)
    return Response(
        content=lesson_report_csv(view),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="lesson-{lesson_id}-report.csv"'},
    )
