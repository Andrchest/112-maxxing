"""«Случайный порядок карточек» over HTTP (I7 E53, G12a; ТЗ ¶340; HLD 71 §71.19.53).

* `shuffle: true` → the server draws a seed, `LessonDetail.shuffle_seed` carries it on create and
  on every `getLesson`, and the stored plan is exactly `shuffle_plan(request plan, seed)`: the
  cards (told apart by weight here) permuted, every position keeping its arrival;
* the cards are created in the permuted order (a card's session carries its plan position);
* no `shuffle` → `shuffle_seed: null` and the request's own order, unchanged;
* the seed is in the «было → стало» record of `createLesson` (I7 E43).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.common.ids import ScenarioVersionId
from app.domain.lesson.plan import PlanEntry
from app.domain.lesson.shuffle import shuffle_plan
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api._audit_changes import audit_ids, changes_by_field, new_row
from tests.api.lessons.conftest import Lessons, plan_entry

pytestmark = pytest.mark.integration

_WEIGHTS = [1.0, 2.0, 3.0, 4.0, 5.0]


def _plan(version_id: ScenarioVersionId) -> list[dict[str, Any]]:
    return [
        plan_entry(index + 1, version_id, offset_ms=index * 60_000, weight=weight)
        for index, weight in enumerate(_WEIGHTS)
    ]


async def test_shuffle_records_a_seed_and_stores_the_seeded_order(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    request = _plan(demo_version_id)
    detail = await lessons.created(request, shuffle=True)

    seed = detail["shuffle_seed"]
    assert isinstance(seed, int) and 0 <= seed <= 2**53 - 1
    expected = shuffle_plan([PlanEntry.model_validate(entry) for entry in request], seed)
    plan = detail["scenario_plan"]
    assert [entry["weight"] for entry in plan] == [entry.weight for entry in expected]
    assert sorted(entry["weight"] for entry in plan) == _WEIGHTS
    # every slot keeps its arrival: the lesson's clock is the instructor's, only the cards move
    assert [entry["arrival"]["offset_ms"] for entry in plan] == [
        index * 60_000 for index in range(len(_WEIGHTS))
    ]
    assert [card["position"] for card in detail["sessions"]] == [1, 2, 3, 4, 5]

    again = await lessons.get(detail["lesson_id"])
    assert again["shuffle_seed"] == seed
    assert again["scenario_plan"] == plan


async def test_without_shuffle_the_order_is_the_requests_own(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await lessons.created(_plan(demo_version_id))

    assert detail["shuffle_seed"] is None
    assert [entry["weight"] for entry in detail["scenario_plan"]] == _WEIGHTS
    assert (await lessons.get(detail["lesson_id"]))["shuffle_seed"] is None


async def test_the_seed_is_in_the_create_audit_record(
    lessons: Lessons, demo_version_id: ScenarioVersionId, migrated_engine: AsyncEngine
) -> None:
    before = await audit_ids(migrated_engine)
    detail = await lessons.created(_plan(demo_version_id), shuffle=True)

    changes = changes_by_field(await new_row(migrated_engine, before, "createLesson"))
    assert changes["lesson.shuffle_seed"] == (None, detail["shuffle_seed"])
    assert changes["lesson.scenario_plan"][1] == [
        {
            "position": entry["position"],
            "scenario_version_id": str(demo_version_id),
            "weight": entry["weight"],
        }
        for entry in detail["scenario_plan"]
    ]
