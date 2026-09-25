"""`listLessonComments` / `createLessonComment` over HTTP (I4 E32, `71-i4-wave4.md` §71.9).

The lesson equivalent of `tests/api/reports/test_comments.py`: comment visibility follows the
lesson report's release (every card released) rather than a per-session one, because an aborted
lesson's cards have no per-session release of their own to ride on.
"""

from __future__ import annotations

import httpx
import pytest
from app.domain.common.ids import ScenarioVersionId

from tests.api.lessons.conftest import Lessons, plan_entry

pytestmark = pytest.mark.integration


async def _created_and_started(lessons: Lessons, demo_version_id: ScenarioVersionId) -> str:
    """A lesson with one DDS-assigned trainee (`trainee2`, the `lessons.create` default),
    started then immediately aborted — the cheapest road to a terminal, releasable lesson."""
    detail = await lessons.created([plan_entry(1, demo_version_id)])
    lesson_id: str = detail["lesson_id"]
    await lessons.start(lesson_id)
    aborted = await lessons.client.post(
        f"/api/v1/lessons/{lesson_id}/abort", headers=lessons.instructor, json={"reason": "тест"}
    )
    assert aborted.status_code == 200, aborted.text
    assert aborted.json()["state"] == "ABORTED"
    return lesson_id


async def _comments(lessons: Lessons, lesson_id: str, *, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else lessons.instructor
    return await lessons.client.get(f"/api/v1/lessons/{lesson_id}/comments", headers=headers)


async def _post_comment(
    lessons: Lessons, lesson_id: str, *, token: str | None, **body: object
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else lessons.instructor
    return await lessons.client.post(
        f"/api/v1/lessons/{lesson_id}/comments", headers=headers, json=body
    )


async def test_lesson_comment_visibility_follows_the_lesson_release(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    lesson_id = await _created_and_started(lessons, demo_version_id)
    trainee_token = lessons.tokens["trainee2"]

    created = await _post_comment(
        lessons, lesson_id, token=None, text="Итог занятия: неплохо, но карту заполняли долго."
    )
    assert created.status_code == 201, created.text
    assert created.json()["lesson_id"] == lesson_id
    assert created.json()["session_id"] is None

    as_instructor = await _comments(lessons, lesson_id, token=None)
    assert as_instructor.status_code == 200
    assert len(as_instructor.json()["items"]) == 1

    before_release = await _comments(lessons, lesson_id, token=trainee_token)
    assert before_release.status_code == 403, before_release.text
    assert before_release.json()["code"] == "REPORT_NOT_RELEASED"

    released = await lessons.client.post(
        f"/api/v1/instructor/lessons/{lesson_id}/report/release", headers=lessons.instructor
    )
    assert released.status_code == 200, released.text

    after_release = await _comments(lessons, lesson_id, token=trainee_token)
    assert after_release.status_code == 200, after_release.text
    assert len(after_release.json()["items"]) == 1


async def test_lesson_comment_edit_is_a_new_row(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    lesson_id = await _created_and_started(lessons, demo_version_id)

    first = await _post_comment(lessons, lesson_id, token=None, text="Черновик.")
    assert first.status_code == 201, first.text
    first_id = first.json()["comment_id"]

    edited = await _post_comment(
        lessons, lesson_id, token=None, text="Итоговая версия.", replaces_comment_id=first_id
    )
    assert edited.status_code == 201, edited.text

    listed = await _comments(lessons, lesson_id, token=None)
    items = {item["comment_id"]: item for item in listed.json()["items"]}
    assert len(items) == 2
    assert items[first_id]["superseded"] is True
    assert items[edited.json()["comment_id"]]["superseded"] is False


async def test_create_lesson_comment_is_instructor_only(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    lesson_id = await _created_and_started(lessons, demo_version_id)
    refused = await _post_comment(lessons, lesson_id, token=lessons.tokens["trainee2"], text="…")
    assert refused.status_code == 403
    assert refused.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_lesson_comments_on_an_unknown_lesson_is_404(lessons: Lessons) -> None:
    response = await lessons.client.get(
        "/api/v1/lessons/00000000-0000-4000-8000-000000000000/comments",
        headers=lessons.instructor,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
