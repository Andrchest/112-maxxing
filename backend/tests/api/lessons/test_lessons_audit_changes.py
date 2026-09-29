"""«было → стало» on the lesson, weight, group and lesson-comment audit rows (I7 E43, Q-E15-3).

Each mutating operation leaves its one `audit_log` row carrying `changes`: `createLesson` (title,
mode, participants, plan, a card's timers, the pass criteria), `startLesson` / `abortLesson` (the
lesson's state, the cards it stopped), `releaseLessonReport`, `acceptWeightProposals` (each
accepted card's weight), `create/update/deleteTraineeGroup` and `createLessonComment` (an edit
shows the text it replaces).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.common.ids import ScenarioVersionId
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api._audit_changes import audit_ids, changes_by_field, new_row
from tests.api.lessons.conftest import Lessons, plan_entry

pytestmark = pytest.mark.integration

_CRITERIA = {"min_score_percent": 80, "max_failed_rules": 2, "fail_on_critical": True}


async def test_create_lesson_records_the_lesson_as_created(
    lessons: Lessons, demo_version_id: ScenarioVersionId, migrated_engine: AsyncEngine
) -> None:
    second = plan_entry(2, demo_version_id, offset_ms=60_000, weight=2.0)
    second["timers"] = {"accept_within_ms": 5_000}
    before = await audit_ids(migrated_engine)
    detail = await lessons.created(
        [plan_entry(1, demo_version_id), second], pass_criteria=_CRITERIA
    )

    changes = changes_by_field(await new_row(migrated_engine, before, "createLesson"))
    assert changes == {
        "lesson.title_ru": (None, "Занятие: поток карточек"),
        "lesson.session_mode": (None, "SINGLE_ROLE"),
        "lesson.participants": (None, ["trainee2"]),
        "lesson.scenario_plan": (
            None,
            [
                {"position": 1, "scenario_version_id": str(demo_version_id), "weight": 1.0},
                {"position": 2, "scenario_version_id": str(demo_version_id), "weight": 2.0},
            ],
        ),
        "lesson.timers[2]": (None, {"accept_within_ms": 5_000}),
        "lesson.pass_criteria": (None, _CRITERIA),
    }
    assert detail["state"] == "CREATED"


async def test_start_abort_and_release_record_the_lesson_state(
    lessons: Lessons, demo_version_id: ScenarioVersionId, migrated_engine: AsyncEngine
) -> None:
    lesson_id = (await lessons.created([plan_entry(1, demo_version_id)]))["lesson_id"]

    before = await audit_ids(migrated_engine)
    await lessons.start(lesson_id)
    started = await new_row(migrated_engine, before, "startLesson")
    assert changes_by_field(started) == {"lesson.state": ("CREATED", "ACTIVE")}

    before = await audit_ids(migrated_engine)
    aborted = await lessons.client.post(
        f"/api/v1/lessons/{lesson_id}/abort", headers=lessons.instructor, json={"reason": "тест"}
    )
    assert aborted.status_code == 200, aborted.text
    row = await new_row(migrated_engine, before, "abortLesson")
    assert changes_by_field(row) == {
        "lesson.state": ("ACTIVE", "ABORTED"),
        "lesson.aborted_cards": (None, 1),
    }

    before = await audit_ids(migrated_engine)
    released = await lessons.client.post(
        f"/api/v1/instructor/lessons/{lesson_id}/report/release", headers=lessons.instructor
    )
    assert released.status_code == 200, released.text
    row = await new_row(migrated_engine, before, "releaseLessonReport")
    assert changes_by_field(row) == {"lesson.report_released": (False, True)}

    # releasing again is idempotent: the row is written, with nothing changed in it
    before = await audit_ids(migrated_engine)
    again = await lessons.client.post(
        f"/api/v1/instructor/lessons/{lesson_id}/report/release", headers=lessons.instructor
    )
    assert again.status_code == 200
    assert (await new_row(migrated_engine, before, "releaseLessonReport"))["changes"] is None


async def test_accept_weight_proposals_records_each_accepted_weight(
    lessons: Lessons, demo_version_id: ScenarioVersionId, migrated_engine: AsyncEngine
) -> None:
    detail = await lessons.created(
        [plan_entry(1, demo_version_id), plan_entry(2, demo_version_id, offset_ms=60_000)]
    )
    base = f"/api/v1/lessons/{detail['lesson_id']}/weight-proposals"
    proposed = (await lessons.client.post(base, headers=lessons.instructor)).json()
    weights = {line["position"]: line["proposed_weight"] for line in proposed["proposals"]}

    before = await audit_ids(migrated_engine)
    accepted = await lessons.client.post(
        f"{base}/accept", headers=lessons.instructor, json={"positions": [2]}
    )
    assert accepted.status_code == 200, accepted.text

    expected: dict[str, tuple[Any, Any]] = {}
    if weights[2] != 1.0:
        expected["lesson.weight[2]"] = (1.0, weights[2])
    changes = changes_by_field(await new_row(migrated_engine, before, "acceptWeightProposals"))
    assert changes == expected, "only the accepted card's weight is reported"


async def test_trainee_group_create_update_delete_record_name_and_members(
    lessons: Lessons, migrated_engine: AsyncEngine
) -> None:
    before = await audit_ids(migrated_engine)
    created = await lessons.client.post(
        "/api/v1/trainee-groups",
        headers=lessons.instructor,
        json={
            "name_ru": "Группа E43",
            "member_user_ids": [str(lessons.users["trainee2"]), str(lessons.users["trainee1"])],
        },
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["group_id"]
    assert changes_by_field(await new_row(migrated_engine, before, "createTraineeGroup")) == {
        "group.name_ru": (None, "Группа E43"),
        "group.members": (None, ["trainee1", "trainee2"]),
    }

    before = await audit_ids(migrated_engine)
    updated = await lessons.client.put(
        f"/api/v1/trainee-groups/{group_id}",
        headers=lessons.instructor,
        json={"name_ru": "Группа E43-б", "member_user_ids": [str(lessons.users["trainee1"])]},
    )
    assert updated.status_code == 200, updated.text
    assert changes_by_field(await new_row(migrated_engine, before, "updateTraineeGroup")) == {
        "group.name_ru": ("Группа E43", "Группа E43-б"),
        "group.members": (["trainee1", "trainee2"], ["trainee1"]),
    }

    before = await audit_ids(migrated_engine)
    deleted = await lessons.client.delete(
        f"/api/v1/trainee-groups/{group_id}", headers=lessons.instructor
    )
    assert deleted.status_code == 204
    assert changes_by_field(await new_row(migrated_engine, before, "deleteTraineeGroup")) == {
        "group.name_ru": ("Группа E43-б", None),
        "group.members": (["trainee1"], None),
    }


async def test_lesson_comment_records_the_text_and_an_edit_the_text_it_replaces(
    lessons: Lessons, demo_version_id: ScenarioVersionId, migrated_engine: AsyncEngine
) -> None:
    lesson_id = (await lessons.created([plan_entry(1, demo_version_id)]))["lesson_id"]
    url = f"/api/v1/lessons/{lesson_id}/comments"

    before = await audit_ids(migrated_engine)
    first = await lessons.client.post(url, headers=lessons.instructor, json={"text": "Хорошо"})
    assert first.status_code == 201, first.text
    assert changes_by_field(await new_row(migrated_engine, before, "createLessonComment")) == {
        "comment.text": (None, "Хорошо")
    }

    before = await audit_ids(migrated_engine)
    edit = await lessons.client.post(
        url,
        headers=lessons.instructor,
        json={"text": "Отлично", "replaces_comment_id": first.json()["comment_id"]},
    )
    assert edit.status_code == 201, edit.text
    assert changes_by_field(await new_row(migrated_engine, before, "createLessonComment")) == {
        "comment.text": ("Хорошо", "Отлично")
    }


async def test_a_refused_request_records_no_changes(
    lessons: Lessons, demo_version_id: ScenarioVersionId, migrated_engine: AsyncEngine
) -> None:
    """A refused request's row carries no changes; the successful one before it does."""
    lesson_id = (await lessons.created([plan_entry(1, demo_version_id)]))["lesson_id"]
    before = await audit_ids(migrated_engine)
    aborted = await lessons.client.post(
        f"/api/v1/lessons/{lesson_id}/abort", headers=lessons.instructor, json={"reason": "x"}
    )
    assert aborted.status_code == 200, aborted.text
    again = await lessons.client.post(
        f"/api/v1/lessons/{lesson_id}/abort", headers=lessons.instructor, json={"reason": "x"}
    )
    assert again.status_code == 409
    async with migrated_engine.connect() as connection:
        rows = (
            await connection.execute(
                text("SELECT id, status, changes FROM audit_log WHERE operation_id = 'abortLesson'")
            )
        ).all()
    # the test clock does not move, so the two rows share `ts`: told apart by status, not order
    fresh = {row.status: row.changes for row in rows if row.id not in before}
    assert set(fresh) == {200, 409}
    assert fresh[200] is not None and fresh[409] is None
