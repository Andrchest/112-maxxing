"""INV 5, I3 E4a — "a lesson of 3 cards = 3 sessions × 1 incident" (HLD 70 §70.1, §70.3, D15).

`uq_incidents_session` is kept literally (SPEC §1, §13): a stream of cards is a lesson of N
ordinary sessions, never N incidents in one session. Over real HTTP and PostgreSQL: a three-card
lesson, every card started, gives three sessions, each with exactly one incident and one unbroken
timeline of its own, and three distinct incidents with three distinct «Происшествие» numbers.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

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
demo_version_id = _api_fixtures.demo_version_id
unit_of_work = _api_fixtures.unit_of_work
clock = _handoff_fixtures.clock
container = _handoff_fixtures.container
idempotency = _handoff_fixtures.idempotency
lessons = _lesson_fixtures.lessons
plan_entry = _lesson_fixtures.plan_entry


async def test_a_lesson_of_three_cards_is_three_sessions_of_one_incident_each(
    lessons: Any, demo_version_id: Any, unit_of_work: Any
) -> None:
    detail = await lessons.created(
        [
            plan_entry(1, demo_version_id, offset_ms=0),
            plan_entry(2, demo_version_id, offset_ms=1_000),
            plan_entry(3, demo_version_id, offset_ms=2_000),
        ]
    )
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    await lessons.at(lesson_id, 2_000)
    cards = (await lessons.get(lesson_id))["sessions"]
    assert [card["state"] for card in cards] == ["ACTIVE", "ACTIVE", "ACTIVE"]

    session_ids = [card["session_id"] for card in cards]
    assert len(set(session_ids)) == 3
    async with unit_of_work() as uow:
        rows = (
            await uow.session.execute(
                sa.text(
                    "SELECT session_id, count(*) AS n, min(display_number) AS number"
                    " FROM incidents WHERE session_id = ANY(CAST(:ids AS uuid[]))"
                    " GROUP BY session_id"
                ),
                {"ids": session_ids},
            )
        ).all()
        await uow.commit()
    assert {str(row.session_id) for row in rows} == set(session_ids)
    assert all(row.n == 1 for row in rows), (
        "exactly one incident per session (uq_incidents_session)"
    )
    assert len({row.number for row in rows}) == 3
    assert len({card["incident_id"] for card in cards}) == 3

    for position, session_id in enumerate(session_ids, start=1):
        events = await lessons.events(session_id)
        seq_nos = [event["seq_no"] for event in events]
        assert seq_nos == list(range(1, len(seq_nos) + 1)), "one gap-free timeline per card"
        created = events[0]
        assert created["event_type"] == "SESSION_CREATED"
        assert created["payload"]["lesson_position"] == position
