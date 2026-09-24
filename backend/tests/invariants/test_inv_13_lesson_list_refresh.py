"""INV 13, I3 E4a — a refresh of the lesson and incident lists loses no state (HLD 70 §70.1).

The lists are REST read models (`GET /lessons/{id}`, `GET /incidents`) over materialised columns
(`incidents.card_status`, `display_number`) and persisted clocks: reading them again — from a
second client, or from a brand-new container as after a backend restart — returns the same
statuses, the same numbers and the same deadlines, and a status the server changed in between
(a deadline passed) is what the refreshed list shows, without any client-side derivation.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.api.container import Container
from app.api.main import create_app
from app.db.session import create_session_factory
from app.infrastructure.persistence.unit_of_work import unit_of_work_factory

from tests.api import conftest as _api_fixtures
from tests.api.handoff import conftest as _handoff_fixtures
from tests.api.lessons import conftest as _lesson_fixtures

pytestmark = pytest.mark.integration

client = _api_fixtures.client
clean_database = _api_fixtures.clean_database
api_settings = _api_fixtures.api_settings
tokens = _api_fixtures.tokens
users = _api_fixtures.users
hasher = _api_fixtures.hasher
inference = _api_fixtures.inference
publisher = _api_fixtures.publisher
redis_client = _api_fixtures.redis_client
unit_of_work = _api_fixtures.unit_of_work
clock = _handoff_fixtures.clock
container = _handoff_fixtures.container
idempotency = _handoff_fixtures.idempotency
lessons = _lesson_fixtures.lessons
short_timers_version_id = _lesson_fixtures.short_timers_version_id
plan_entry = _lesson_fixtures.plan_entry
auth = _api_fixtures.auth

_VOLATILE = ("session_offset_ms",)


def _stable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in row.items() if k not in _VOLATILE} for row in rows]


async def _lists(http: httpx.AsyncClient, token: str, lesson_id: str) -> tuple[Any, Any]:
    lesson = await http.get(f"/api/v1/lessons/{lesson_id}", headers=auth(token))
    incidents = await http.get(
        "/api/v1/incidents", headers=auth(token), params={"lesson_id": lesson_id}
    )
    assert lesson.status_code == 200, lesson.text
    assert incidents.status_code == 200, incidents.text
    return lesson.json(), _stable(incidents.json()["items"])


async def test_the_lesson_and_incident_lists_survive_a_refresh_and_a_restart(
    lessons: Any,
    short_timers_version_id: Any,
    tokens: dict[str, str],
    api_settings: Any,
    migrated_engine: Any,
    redis_client: Any,
    publisher: Any,
    hasher: Any,
    inference: Any,
    clock: Any,
) -> None:
    detail = await lessons.created(
        [plan_entry(1, short_timers_version_id), plan_entry(2, short_timers_version_id)]
    )
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    token = tokens["trainee2"]

    first = await _lists(lessons.client, token, lesson_id)
    second = await _lists(lessons.client, token, lesson_id)
    assert first == second
    assert [row["card_status"] for row in first[1]] == ["WORKED", "WORKED"]

    # A deadline passes on the server; the refreshed list shows it, derived by nobody but the
    # server.
    clock.advance_ms(_lesson_fixtures.SHORT_ACCEPT_MS)
    for card in detail["sessions"]:
        await lessons.tick_session(card["session_id"])
    lesson_after, incidents_after = await _lists(lessons.client, token, lesson_id)
    assert [card["card_status"] for card in lesson_after["sessions"]] == ["NOT_NOTIFIED"] * 2
    assert [row["card_status"] for row in incidents_after] == ["NOT_NOTIFIED"] * 2

    # A restarted backend: a new container over the same database reads the same lists.
    session_factory = create_session_factory(migrated_engine)
    restarted = Container(
        api_settings,
        engine=migrated_engine,
        session_factory=session_factory,
        redis=redis_client,
        publisher=publisher,
        clock=clock,
        unit_of_work=unit_of_work_factory(session_factory, clock, publisher),
        hasher=hasher,
        inference=inference,
        owns_engine=False,
        owns_redis=False,
    )
    transport = httpx.ASGITransport(app=create_app(restarted))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as fresh:
        assert await _lists(fresh, token, lesson_id) == (lesson_after, incidents_after)
