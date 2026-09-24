"""`lessons` router — `createLesson`, `listLessons`, `getLesson`, `startLesson`, `abortLesson`,
`getLessonReport`, `releaseLessonReport` (HLD 70 §70.3, `i3-openapi-delta.yaml`, D15).

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

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.api.schemas.common import PageSchema
from app.api.schemas.lessons import (
    LessonCreateRequestSchema,
    LessonDetailSchema,
    LessonListItemSchema,
    LessonReportSchema,
    lesson_detail_schema,
    lesson_list_item_schema,
    lesson_report_schema,
)
from app.api.schemas.sessions import AbortSessionRequestSchema
from app.api.security import AdminOrInstructorDep, CurrentUserDep, actor_of
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.lessons.create_lesson import CreateLessonCommand
from app.application.lessons.queries import assemble_lesson_detail
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


async def _detail(container: ContainerDep, lesson: Lesson) -> LessonDetailSchema:
    async with container.unit_of_work() as uow:
        view = await assemble_lesson_detail(uow, lesson)
        await uow.commit()
    return lesson_detail_schema(view)


async def _detail_by_id(
    container: ContainerDep, lesson_id: LessonId, user: AuthenticatedUser
) -> LessonDetailSchema:
    return lesson_detail_schema(await container.get_lesson()(lesson_id, user))
