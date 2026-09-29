"""`getActivityHeatmap` over HTTP (I7 E46a, admin item 6: «Активность» weekday × hour).

ADMIN only; buckets `simulation_sessions.started_at` by ISO weekday (1 = Monday … 7 = Sunday) and
hour, in Moscow wall time (`Europe/Moscow`, manager follow-up: admins read this as local hours,
the same zone every export's own "Сформировано" stamp already uses — never UTC).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import sqlalchemy as sa
from app.domain.common.ids import ScenarioVersionId, UserId

from tests.api.conftest import auth, create_demo_session, participant

pytestmark = pytest.mark.integration

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _participants(users: dict[str, UserId]) -> list[dict[str, object]]:
    return [
        participant(users["trainee1"], "OPERATOR_112"),
        participant(users["trainee2"], "DDS"),
    ]


async def test_get_activity_heatmap_counts_a_started_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    before = datetime.now(UTC)
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    start = await client.post(
        f"/api/v1/sessions/{created['id']}/start", headers=auth(tokens["instructor1"])
    )
    assert start.status_code == 200, start.text
    after = datetime.now(UTC)

    response = await client.get("/api/v1/admin/activity-heatmap", headers=auth(tokens["admin1"]))
    assert response.status_code == 200, response.text
    cells = response.json()["cells"]

    # The bucket this session's `started_at` falls into, in Moscow wall time — never UTC
    # (manager follow-up) — tolerant of the two clock reads straddling an hour boundary, the
    # same "acceptable low risk" `test_monitoring.py` takes for its own `datetime.now(UTC)` check.
    before_msk = before.astimezone(MOSCOW_TZ)
    after_msk = after.astimezone(MOSCOW_TZ)
    candidates = {
        (before_msk.isoweekday(), before_msk.hour),
        (after_msk.isoweekday(), after_msk.hour),
    }
    matching = [cell for cell in cells if (cell["weekday"], cell["hour"]) in candidates]
    assert matching, cells
    assert any(cell["session_count"] >= 1 for cell in matching)
    for cell in cells:
        assert 1 <= cell["weekday"] <= 7
        assert 0 <= cell["hour"] <= 23
        assert cell["session_count"] >= 0


async def test_get_activity_heatmap_buckets_by_moscow_time_across_a_utc_midnight(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Any,
) -> None:
    """A session started 23:30 UTC is 02:30 the *next* day in Moscow (UTC+3, no DST) — it must
    land in that next Moscow day's hour-02 bucket, never in the UTC day/hour."""
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    start = await client.post(
        f"/api/v1/sessions/{created['id']}/start", headers=auth(tokens["instructor1"])
    )
    assert start.status_code == 200, start.text

    started_at_utc = datetime(2026, 3, 9, 23, 30, tzinfo=UTC)  # a Monday in UTC
    async with unit_of_work() as uow:
        await uow.session.execute(
            sa.text("UPDATE simulation_sessions SET started_at = :ts WHERE id = :id"),
            {"ts": started_at_utc, "id": created["id"]},
        )
        await uow.commit()

    started_at_msk = started_at_utc.astimezone(MOSCOW_TZ)
    assert started_at_msk.hour == 2, "sanity: the manager's own example"
    assert started_at_msk.isoweekday() != started_at_utc.isoweekday(), (
        "crossed midnight into Tuesday"
    )

    response = await client.get("/api/v1/admin/activity-heatmap", headers=auth(tokens["admin1"]))
    assert response.status_code == 200, response.text
    cells = response.json()["cells"]

    moscow_bucket = [
        cell
        for cell in cells
        if cell["weekday"] == started_at_msk.isoweekday() and cell["hour"] == started_at_msk.hour
    ]
    assert moscow_bucket, cells
    assert moscow_bucket[0]["session_count"] >= 1

    utc_bucket = [
        cell
        for cell in cells
        if cell["weekday"] == started_at_utc.isoweekday() and cell["hour"] == started_at_utc.hour
    ]
    assert utc_bucket == [], "must not also (or instead) land in the UTC day/hour"


async def test_get_activity_heatmap_is_forbidden_for_non_admin(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.get("/api/v1/admin/activity-heatmap", headers=auth(tokens["trainee1"]))
    assert response.status_code == 403, response.text


async def test_get_activity_heatmap_requires_a_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/admin/activity-heatmap")
    assert response.status_code == 401, response.text
