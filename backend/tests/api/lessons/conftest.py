"""Fixtures for the lesson API tests (I3 E4a, HLD 70 §70.3) — real HTTP, a movable clock.

The container is the handoff package's `FakeClock` one, so a lesson's wall clock (arrivals) and
every card's session clock (timers) move only when a test moves them. `runner_enabled` is false
for API tests: nothing ticks by itself, and a test drives `container.lesson_runner.tick_now` and
`container.runner.tick_now` — the same calls the loops make — exactly when it wants a tick.

The demo scenario (`apartment-fire`, chain `[OPERATOR_112, DDS]`, with a prefab handoff) plays
every card. A `GENERATED_CARD` card is its DDS suffix, played by `trainee2`; a `CALLER_VOICE` card
is the whole chain under `MULTI_TRAINEE`, `trainee1` at the 112 desk. `short_timers_version_id` is
the same document as schema 2 with a 3-second accept window, so deadline tests tick a few seconds
rather than thirty.
"""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from app.api.container import Container
from app.application.scenarios.import_scenarios import canonical_content, content_digest
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import LessonId, ScenarioId, ScenarioVersionId, SessionId, UserId
from app.domain.scenario.version import ScenarioVersion
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth
from tests.api.handoff import conftest as _handoff_fixtures
from tests.fixtures.scenarios import demo_document

pytestmark = pytest.mark.integration

clock = _handoff_fixtures.clock
container = _handoff_fixtures.container
idempotency = _handoff_fixtures.idempotency

GENERATED_CARD = {"card_source": "GENERATED_CARD"}
CALLER_VOICE = {"card_source": "CALLER_VOICE"}
SHORT_ACCEPT_MS = 3_000


@pytest.fixture(scope="package", autouse=True)
async def _remove_this_packages_scenarios(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """Leave the shared catalog without the extra version written here (see the handoff twin)."""
    yield
    async with migrated_engine.begin() as connection:
        await connection.execute(sa.text("TRUNCATE TABLE scenarios RESTART IDENTITY CASCADE"))


@pytest.fixture
async def short_timers_version_id(unit_of_work: Any) -> ScenarioVersionId:
    """The demo document as schema 2 with `timers.accept_within_ms: 3000` (self-healing)."""
    slug = "lesson-short-timers"
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(slug)
        row = await uow.scenarios.find_version(stored.scenario_id, 1) if stored else None
        await uow.commit()
    if row is not None:
        return row.scenario_version_id
    document: dict[str, Any] = copy.deepcopy(demo_document())
    document["id"] = str(uuid4())
    document["scenario_id"] = str(uuid4())
    document["schema_version"] = 2
    document["timers"] = {"accept_within_ms": SHORT_ACCEPT_MS, "not_completed_after_ms": 600_000}
    version = ScenarioVersion(**document)
    content = canonical_content(version)
    async with unit_of_work() as uow:
        await uow.scenarios.add_scenario(ScenarioId(UUID(document["scenario_id"])), slug, "Урок")
        await uow.scenarios.add_version(version, content, content_digest(content))
        await uow.scenarios.add_scoring_rules(version.id, version.scoring_rules)
        await uow.commit()
    return version.id


def plan_entry(
    position: int,
    version_id: ScenarioVersionId,
    *,
    kind: str = "AT_OFFSET",
    offset_ms: int | None = 0,
    delay_ms: int = 0,
    variants: dict[str, str] | None = None,
    participants: list[UserId] | None = None,
    weight: float = 1.0,
) -> dict[str, Any]:
    arrival: dict[str, Any] = {"kind": kind, "delay_ms": delay_ms}
    if kind == "AT_OFFSET":
        arrival["offset_ms"] = offset_ms
    entry: dict[str, Any] = {
        "position": position,
        "scenario_version_id": str(version_id),
        "arrival": arrival,
        "weight": weight,
    }
    if variants is not None:
        entry["variants"] = variants
    if participants is not None:
        entry["participants"] = [str(user_id) for user_id in participants]
    return entry


@dataclass
class Lessons:
    """The levers of one test: HTTP as the instructor, the clock, the two runners."""

    client: httpx.AsyncClient
    container: Container
    clock: FakeClock
    tokens: dict[str, str]
    users: dict[str, UserId]

    @property
    def instructor(self) -> dict[str, str]:
        return auth(self.tokens["instructor1"])

    async def create(
        self, plan: list[dict[str, Any]], *, session_mode: str = "SINGLE_ROLE", **extra: Any
    ) -> httpx.Response:
        participants = extra.pop(
            "participants", [{"user_id": str(self.users["trainee2"]), "assigned_role_type": "DDS"}]
        )
        body = {
            "title_ru": "Занятие: поток карточек",
            "session_mode": session_mode,
            "participants": participants,
            "variants": GENERATED_CARD,
            "scenario_plan": plan,
            **extra,
        }
        return await self.client.post("/api/v1/lessons", headers=self.instructor, json=body)

    async def created(self, plan: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        response = await self.create(plan, **extra)
        assert response.status_code == 201, response.text
        body: dict[str, Any] = response.json()
        return body

    async def get(self, lesson_id: str, token: str | None = None) -> dict[str, Any]:
        headers = auth(token) if token else self.instructor
        response = await self.client.get(f"/api/v1/lessons/{lesson_id}", headers=headers)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def start(self, lesson_id: str) -> dict[str, Any]:
        response = await self.client.post(
            f"/api/v1/lessons/{lesson_id}/start", headers=self.instructor
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def tick(self, lesson_id: str) -> Any:
        return await self.container.lesson_runner.tick_now(LessonId(UUID(lesson_id)))

    async def at(self, lesson_id: str, lesson_ms: int) -> Any:
        """Put the lesson wall clock at `lesson_ms` since `startLesson` and tick the lesson."""
        started_at = (await self.get(lesson_id))["started_at"]
        assert started_at is not None
        elapsed = int((self.clock.now() - _parse(started_at)).total_seconds() * 1000)
        assert lesson_ms >= elapsed, f"cannot go back from {elapsed} to {lesson_ms}"
        self.clock.advance_ms(lesson_ms - elapsed)
        return await self.tick(lesson_id)

    async def states(self, lesson_id: str) -> list[str]:
        return [card["state"] for card in (await self.get(lesson_id))["sessions"]]

    async def events(self, session_id: str) -> list[dict[str, Any]]:
        response = await self.client.get(
            f"/api/v1/sessions/{session_id}/events",
            headers=self.instructor,
            params={"limit": 1000},
        )
        assert response.status_code == 200, response.text
        items: list[dict[str, Any]] = response.json()["items"]
        return items

    async def tick_session(self, session_id: str) -> None:
        await self.container.runner.tick_now(SessionId(UUID(session_id)))


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
def lessons(
    client: httpx.AsyncClient,
    container: Container,
    clock: FakeClock,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> Lessons:
    return Lessons(client=client, container=container, clock=clock, tokens=tokens, users=users)
