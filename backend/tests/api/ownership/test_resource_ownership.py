"""Instructors see everything but change only their own — I5 E39 (Q-E9b-4 variant а, ТЗ ¶245).

Every MUTATING instructor operation on a lesson, a session, its report or a trainee group is run
three times over real HTTP against a resource `instructor1` created:

* by `instructor1` (the owner) — the operation's own success status;
* by `instructor2` — `403 NOT_RESOURCE_OWNER`, and nothing changes;
* by `admin1` — the success status (ADMIN is not subject to the check).

The operations are grouped by the state they need (a fresh resource, a `COMPLETED` session, a
session in `ROLE_TRANSITION`), one parametrised test per group over one shared table. Reads, and
the append-only result comments, stay open to every instructor. The NULL-owner (legacy) rule is
the pure function's — every owner column is `NOT NULL` today — and is covered in
`tests/unit/application/auth/test_ownership.py`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from app.api.container import Container
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import ScenarioVersionId, UserId

from tests.api.conftest import auth, create_demo_session, participant
from tests.api.lessons.conftest import Lessons, plan_entry
from tests.api.reports.conftest import OperatorFlow

pytestmark = pytest.mark.integration

ACTORS = ("owner", "other", "admin")


@dataclass
class World:
    """Who is who, and the levers to build a resource as its owner (`instructor1`)."""

    client: httpx.AsyncClient
    tokens: dict[str, str]
    users: dict[str, UserId]
    other_token: str
    version_id: ScenarioVersionId
    lessons: Lessons

    @property
    def owner(self) -> dict[str, str]:
        return auth(self.tokens["instructor1"])

    def headers(self, actor: str) -> dict[str, str]:
        token = {
            "owner": self.tokens["instructor1"],
            "other": self.other_token,
            "admin": self.tokens["admin1"],
        }[actor]
        return auth(token)

    async def session(self) -> str:
        """A `READY` session `instructor1` created."""
        body = await create_demo_session(
            self.client,
            self.tokens["instructor1"],
            self.version_id,
            [participant(self.users["trainee1"], None)],
            session_mode="FULL_CYCLE_SINGLE_TRAINEE",
        )
        return str(body["id"])

    async def lesson(self) -> str:
        """A `CREATED` one-card lesson `instructor1` created."""
        return str((await self.lessons.created([plan_entry(1, self.version_id)]))["lesson_id"])

    async def aborted_lesson(self) -> str:
        lesson_id = await self.lesson()
        response = await self.client.post(
            f"/api/v1/lessons/{lesson_id}/abort", headers=self.owner, json={"reason": "конец"}
        )
        assert response.status_code == 200, response.text
        return lesson_id

    async def lesson_with_proposals(self) -> str:
        lesson_id = await self.lesson()
        response = await self.client.post(
            f"/api/v1/lessons/{lesson_id}/weight-proposals", headers=self.owner
        )
        assert response.status_code == 201, response.text
        return lesson_id

    async def group(self) -> str:
        response = await self.client.post(
            "/api/v1/trainee-groups",
            headers=self.owner,
            json={"name_ru": "Группа 1", "member_user_ids": [str(self.users["trainee1"])]},
        )
        assert response.status_code == 201, response.text
        return str(response.json()["group_id"])


@pytest.fixture
def world(
    client: httpx.AsyncClient,
    container: Container,
    clock: FakeClock,
    tokens: dict[str, str],
    users: dict[str, UserId],
    instructor2: tuple[UserId, str],
    demo_version_id: ScenarioVersionId,
) -> World:
    return World(
        client=client,
        tokens=tokens,
        users=users,
        other_token=instructor2[1],
        version_id=demo_version_id,
        lessons=Lessons(
            client=client, container=container, clock=clock, tokens=tokens, users=users
        ),
    )


# ---------------------------------------------------------------------------------------------
# Operations on a freshly created resource
# ---------------------------------------------------------------------------------------------

Act = Callable[[World, dict[str, str]], Awaitable[httpx.Response]]


async def _start_session(world: World, headers: dict[str, str]) -> httpx.Response:
    session_id = await world.session()
    return await world.client.post(f"/api/v1/sessions/{session_id}/start", headers=headers)


async def _abort_session(world: World, headers: dict[str, str]) -> httpx.Response:
    session_id = await world.session()
    return await world.client.post(
        f"/api/v1/sessions/{session_id}/abort", headers=headers, json={"reason": "стоп"}
    )


async def _start_lesson(world: World, headers: dict[str, str]) -> httpx.Response:
    lesson_id = await world.lesson()
    return await world.client.post(f"/api/v1/lessons/{lesson_id}/start", headers=headers)


async def _abort_lesson(world: World, headers: dict[str, str]) -> httpx.Response:
    lesson_id = await world.lesson()
    return await world.client.post(
        f"/api/v1/lessons/{lesson_id}/abort", headers=headers, json={"reason": "стоп"}
    )


async def _release_lesson_report(world: World, headers: dict[str, str]) -> httpx.Response:
    lesson_id = await world.aborted_lesson()
    return await world.client.post(
        f"/api/v1/instructor/lessons/{lesson_id}/report/release", headers=headers
    )


async def _request_weight_proposals(world: World, headers: dict[str, str]) -> httpx.Response:
    lesson_id = await world.lesson()
    return await world.client.post(f"/api/v1/lessons/{lesson_id}/weight-proposals", headers=headers)


async def _accept_weight_proposals(world: World, headers: dict[str, str]) -> httpx.Response:
    lesson_id = await world.lesson_with_proposals()
    return await world.client.post(
        f"/api/v1/lessons/{lesson_id}/weight-proposals/accept",
        headers=headers,
        json={"positions": [1]},
    )


async def _update_group(world: World, headers: dict[str, str]) -> httpx.Response:
    group_id = await world.group()
    return await world.client.put(
        f"/api/v1/trainee-groups/{group_id}",
        headers=headers,
        json={"name_ru": "Группа 2", "member_user_ids": [str(world.users["trainee2"])]},
    )


async def _delete_group(world: World, headers: dict[str, str]) -> httpx.Response:
    group_id = await world.group()
    return await world.client.delete(f"/api/v1/trainee-groups/{group_id}", headers=headers)


#: operationId → (arrange-and-act, success status).
FRESH: dict[str, tuple[Act, int]] = {
    "startSession": (_start_session, 200),
    "abortSession": (_abort_session, 200),
    "startLesson": (_start_lesson, 200),
    "abortLesson": (_abort_lesson, 200),
    "releaseLessonReport": (_release_lesson_report, 200),
    "requestWeightProposals": (_request_weight_proposals, 201),
    "acceptWeightProposals": (_accept_weight_proposals, 200),
    "updateTraineeGroup": (_update_group, 200),
    "deleteTraineeGroup": (_delete_group, 204),
}


def _assert_outcome(response: httpx.Response, actor: str, success: int) -> None:
    if actor == "other":
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "NOT_RESOURCE_OWNER"
    else:
        assert response.status_code == success, response.text


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("operation", sorted(FRESH))
async def test_a_mutating_operation_is_the_owners_or_an_admins(
    world: World, operation: str, actor: str
) -> None:
    act, success = FRESH[operation]
    _assert_outcome(await act(world, world.headers(actor)), actor, success)


async def test_a_refused_change_changes_nothing(world: World) -> None:
    """The refusal comes before any write: the lesson is still `CREATED`, the group unchanged."""
    lesson_id = await world.lesson()
    refused = await world.client.post(
        f"/api/v1/lessons/{lesson_id}/start", headers=world.headers("other")
    )
    assert refused.status_code == 403
    assert (await world.lessons.get(lesson_id))["state"] == "CREATED"

    group_id = await world.group()
    refused = await world.client.put(
        f"/api/v1/trainee-groups/{group_id}",
        headers=world.headers("other"),
        json={"name_ru": "Чужая", "member_user_ids": []},
    )
    assert refused.status_code == 403
    group = await world.client.get(f"/api/v1/trainee-groups/{group_id}", headers=world.owner)
    assert group.json()["name_ru"] == "Группа 1"


async def test_a_trainee_is_still_refused_on_role(world: World) -> None:
    lesson_id = await world.lesson()
    response = await world.client.post(
        f"/api/v1/lessons/{lesson_id}/start", headers=auth(world.tokens["trainee1"])
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


# ---------------------------------------------------------------------------------------------
# Operations on a COMPLETED session's report
# ---------------------------------------------------------------------------------------------

REPORT: dict[str, tuple[str, dict[str, Any] | None, int]] = {
    "releaseReportToTrainee": ("/api/v1/instructor/sessions/{id}/report/release", None, 200),
    "rescoreSession(persist)": ("/api/v1/reports/{id}/rescore", {"persist": True}, 200),
}


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("operation", sorted(REPORT))
async def test_a_report_operation_is_the_owners_or_an_admins(
    completed: OperatorFlow, world: World, operation: str, actor: str
) -> None:
    path, body, success = REPORT[operation]
    response = await world.client.post(
        path.format(id=completed.session_id), headers=world.headers(actor), json=body
    )
    _assert_outcome(response, actor, success)


# ---------------------------------------------------------------------------------------------
# continueToNextStage — the instructor path of a session in ROLE_TRANSITION
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("actor", ACTORS)
async def test_continuing_a_stage_is_the_owners_or_an_admins(
    in_transition: OperatorFlow, clock: FakeClock, world: World, actor: str
) -> None:
    clock.advance_ms(11_000)
    response = await world.client.post(
        f"/api/v1/sessions/{in_transition.session_id}/stage/continue",
        headers=world.headers(actor),
    )
    _assert_outcome(response, actor, 200)


# ---------------------------------------------------------------------------------------------
# Reads (and the append-only comments) stay open to every instructor
# ---------------------------------------------------------------------------------------------


async def test_another_instructor_reads_everything_and_may_comment(
    completed: OperatorFlow, world: World
) -> None:
    other = world.headers("other")
    session_id = completed.session_id
    for path in (
        f"/api/v1/sessions/{session_id}",
        f"/api/v1/instructor/sessions/{session_id}/overview",
        f"/api/v1/reports/{session_id}",
        f"/api/v1/reports/{session_id}/comments",
    ):
        response = await world.client.get(path, headers=other)
        assert response.status_code == 200, (path, response.text)
    dry_run = await world.client.post(
        f"/api/v1/reports/{session_id}/rescore", headers=other, json={"persist": False}
    )
    assert dry_run.status_code == 200, dry_run.text
    assert dry_run.json()["persisted"] is False
    comment = await world.client.post(
        f"/api/v1/reports/{session_id}/comments", headers=other, json={"text": "Хорошо"}
    )
    assert comment.status_code == 201, comment.text

    lesson_id = await world.lesson_with_proposals()
    detail = await world.client.get(f"/api/v1/lessons/{lesson_id}", headers=other)
    assert detail.status_code == 200, detail.text
    assert detail.json()["created_by_user_id"] == str(world.users["instructor1"])
    proposals = await world.client.get(
        f"/api/v1/lessons/{lesson_id}/weight-proposals", headers=other
    )
    assert proposals.status_code == 200, proposals.text
    aborted = await world.aborted_lesson()
    report = await world.client.get(f"/api/v1/lessons/{aborted}/report", headers=other)
    assert report.status_code == 200, report.text
    lesson_comment = await world.client.post(
        f"/api/v1/lessons/{aborted}/comments", headers=other, json={"text": "Замечание"}
    )
    assert lesson_comment.status_code == 201, lesson_comment.text

    group_id = await world.group()
    group = await world.client.get(f"/api/v1/trainee-groups/{group_id}", headers=other)
    assert group.status_code == 200, group.text
    listed = await world.client.get("/api/v1/lessons", headers=other, params={"scope": "ALL"})
    assert listed.status_code == 200 and listed.json()["total"] >= 1
