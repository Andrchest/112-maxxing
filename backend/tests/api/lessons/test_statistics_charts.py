"""`getStatisticsCharts` over HTTP (I7 E46a, owner item 6).

* INSTRUCTOR / ADMIN only — a TRAINEE gets `403`;
* an INSTRUCTOR's scope is their own lessons only: a second instructor who created nothing sees
  an empty `score_timeline` and every `error_heatmap` cell `null`;
* an ADMIN's scope is every scored session, unrestricted;
* `score_timeline` has one point per scored session, `error_heatmap` has one row per trainee with
  `share_percent` in `[0, 100]` or `null`;
* no evaluator runs and no score moves (D11): reading the endpoint leaves `score_results` alone.

Completion flow and fixtures copied from `test_typical_errors.py` (its own module doc: no
cross-module private import).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from app.application.ports.user_repository import UserRole
from app.application.testing.fakes import FakePasswordHasher
from app.domain.common.ids import ScenarioVersionId, UserId

from tests.api.conftest import auth
from tests.api.lessons.conftest import Lessons, plan_entry

pytestmark = pytest.mark.integration

ACCEPT_AFTER_MS = 12_000
INSTRUCTOR2 = "instructor2-statistics-charts"
INSTRUCTOR2_PASSWORD = "instructor-two-statistics-charts-pw"


async def _complete_dds_card(lessons: Lessons, session_id: str) -> None:
    """The demo's DDS stage to a closed, scored session (copied, see module docstring)."""
    base = f"/api/v1/sessions/{session_id}"
    headers = auth(lessons.tokens["trainee2"])

    async def post(suffix: str, json: Any = None) -> Any:
        response = await lessons.client.post(f"{base}{suffix}", headers=headers, json=json)
        assert response.status_code in (200, 201), response.text
        return response.json()

    async def to(offset_ms: int) -> None:
        detail = (await lessons.client.get(base, headers=headers)).json()
        lessons.clock.advance_ms(offset_ms - int(detail["monotonic_offset_ms"]))
        await lessons.tick_session(session_id)

    await to(ACCEPT_AFTER_MS)
    await post("/dds/acknowledge")
    await post("/dds/resources/selection/open")
    await to(300_000)
    board = (await lessons.client.get(f"{base}/dds/resources", headers=headers)).json()["items"]
    engine_row = next(item for item in board if item["callsign"] == "АЦ-1")
    await post("/dds/resources/select", {"resource_id": engine_row["resource_id"]})
    await post("/dds/resources/dispatch", {"note_ru": None})
    await to(560_000)
    await post("/dds/close", {"closure_reason": "RESOLVED"})


async def _scored_lesson(lessons: Lessons, version_id: ScenarioVersionId) -> tuple[str, str]:
    """One lesson, one card, completed and scored. Returns `(lesson_id, session_id)`."""
    detail = await lessons.created([plan_entry(1, version_id)])
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    (session_id,) = (card["session_id"] for card in detail["sessions"])
    await _complete_dds_card(lessons, session_id)
    assert (await lessons.tick(lesson_id)).completed
    return lesson_id, session_id


@pytest.fixture
async def instructor2_token(
    client: httpx.AsyncClient, unit_of_work: Any, hasher: FakePasswordHasher
) -> str:
    """A second INSTRUCTOR account that created no lesson (the "own lessons" scoping's outside
    case) — inline, mirroring `test_typical_errors.py`'s own fixture."""
    async with unit_of_work() as uow:
        await uow.users.upsert(
            user_id=UserId(uuid4()),
            username=INSTRUCTOR2,
            display_name_ru="Инструктор без занятий (charts)",
            user_role=UserRole.INSTRUCTOR,
            password_hash=hasher.hash(INSTRUCTOR2_PASSWORD),
            is_active=True,
        )
        await uow.commit()
    response = await client.post(
        "/api/v1/auth/login", json={"username": INSTRUCTOR2, "password": INSTRUCTOR2_PASSWORD}
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


async def _score_row_count(unit_of_work: Any, session_id: str) -> int:
    async with unit_of_work() as uow:
        result = await uow.session.execute(
            sa.text("SELECT count(*) FROM score_results WHERE session_id = :s"),
            {"s": session_id},
        )
        count = int(result.scalar_one())
        await uow.commit()
    return count


async def test_a_trainee_may_not_read_statistics_charts(lessons: Lessons) -> None:
    response = await lessons.client.get(
        "/api/v1/statistics/charts", headers=auth(lessons.tokens["trainee1"])
    )
    assert response.status_code == 403, response.text


async def test_an_instructor_sees_only_their_own_lessons(
    lessons: Lessons, demo_version_id: ScenarioVersionId, instructor2_token: str
) -> None:
    await _scored_lesson(lessons, demo_version_id)

    own = await lessons.client.get("/api/v1/statistics/charts", headers=lessons.instructor)
    assert own.status_code == 200, own.text
    own_body = own.json()
    assert len(own_body["score_timeline"]["points"]) >= 1
    for point in own_body["score_timeline"]["points"]:
        assert 0 <= point["score_percent"] <= 100
    categories = own_body["error_heatmap"]["categories"]
    assert len(categories) == 7
    for row in own_body["error_heatmap"]["rows"]:
        assert len(row["cells"]) == len(categories)
        for cell in row["cells"]:
            assert cell["share_percent"] is None or 0 <= cell["share_percent"] <= 100

    other = await lessons.client.get("/api/v1/statistics/charts", headers=auth(instructor2_token))
    assert other.status_code == 200, other.text
    other_body = other.json()
    assert other_body["score_timeline"]["points"] == [], "a second instructor created no lesson"
    for row in other_body["error_heatmap"]["rows"]:
        assert all(cell["share_percent"] is None for cell in row["cells"])


async def test_an_admin_sees_every_scored_session_unrestricted(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    await _scored_lesson(lessons, demo_version_id)
    own = await lessons.client.get("/api/v1/statistics/charts", headers=lessons.instructor)
    admin = await lessons.client.get(
        "/api/v1/statistics/charts", headers=auth(lessons.tokens["admin1"])
    )
    assert own.status_code == admin.status_code == 200
    assert len(admin.json()["score_timeline"]["points"]) >= len(
        own.json()["score_timeline"]["points"]
    ), "an ADMIN's scope is never narrower than the owning instructor's"


async def test_reading_the_charts_writes_nothing(
    lessons: Lessons, demo_version_id: ScenarioVersionId, unit_of_work: Any
) -> None:
    _lesson_id, session_id = await _scored_lesson(lessons, demo_version_id)
    before = await _score_row_count(unit_of_work, session_id)

    response = await lessons.client.get("/api/v1/statistics/charts", headers=lessons.instructor)
    assert response.status_code == 200, response.text

    assert await _score_row_count(unit_of_work, session_id) == before
