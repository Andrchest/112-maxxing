"""INV 7, I3 E4a — the card-status stream does not depend on the tick rate (HLD 70 §70.1, §70.3.5).

"Same seed + actions ⇒ same world events", extended to the deadline consequences: a
`GENERATED_CARD` card whose leg is not accepted within `timers.accept_within_ms` turns
`NOT_NOTIFIED`, and that `DDS_CARD_STATUS_CHANGED` is stamped with the **deadline** offset under the
flush-before-append rule. So the same session, played with the same trainee action at the same
offset, must produce the identical stream whether the runner ticks every 100 ms, every 900 ms, or
not at all before the action — and the deadline event must precede the later-stamped command in
`seq_no` order, with offsets monotonic.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from app.domain.common.ids import SessionId

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
short_timers_version_id = _lesson_fixtures.short_timers_version_id

ACCEPT_MS = _lesson_fixtures.SHORT_ACCEPT_MS
ACTION_AT_MS = 4_000
"""The trainee acknowledges one second after the 3-second accept deadline passed."""

auth = _api_fixtures.auth


async def _run(
    client: Any,
    container: Any,
    clock: Any,
    tokens: dict[str, str],
    users: Any,
    version: Any,
    tick_ms: int | None,
) -> list[dict[str, Any]]:
    """One GENERATED_CARD session: start, tick every `tick_ms` (or never), acknowledge at 4 s."""
    created = await client.post(
        "/api/v1/sessions",
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(version),
            "session_mode": "SINGLE_ROLE",
            "participants": [{"user_id": str(users["trainee2"]), "assigned_role_type": "DDS"}],
            "variants": {"card_source": "GENERATED_CARD"},
        },
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text

    elapsed = 0
    if tick_ms is not None:
        while elapsed + tick_ms < ACTION_AT_MS:
            clock.advance_ms(tick_ms)
            elapsed += tick_ms
            await container.runner.tick_now(SessionId(UUID(session_id)))
    clock.advance_ms(ACTION_AT_MS - elapsed)
    acknowledged = await client.post(
        f"/api/v1/sessions/{session_id}/dds/acknowledge", headers=auth(tokens["trainee2"])
    )
    assert acknowledged.status_code == 200, acknowledged.text
    events = await client.get(
        f"/api/v1/sessions/{session_id}/events",
        headers=auth(tokens["instructor1"]),
        params={"limit": 1000},
    )
    assert events.status_code == 200, events.text
    items: list[dict[str, Any]] = events.json()["items"]
    return items


def _status_stream(items: list[dict[str, Any]]) -> list[tuple[int, str, str, int | None]]:
    """`(offset, previous, new, deadline)` per `DDS_CARD_STATUS_CHANGED` — no per-run ids."""
    return [
        (
            item["monotonic_offset_ms"],
            item["payload"]["previous_status"],
            item["payload"]["new_status"],
            item["payload"]["deadline_offset_ms"],
        )
        for item in items
        if item["event_type"] == "DDS_CARD_STATUS_CHANGED"
    ]


async def test_ticking_every_100_ms_or_900_ms_or_never_gives_one_card_status_stream(
    client: Any,
    container: Any,
    clock: Any,
    tokens: dict[str, str],
    users: Any,
    short_timers_version_id: Any,
) -> None:
    runs = {
        tick: await _run(client, container, clock, tokens, users, short_timers_version_id, tick)
        for tick in (100, 900, None)
    }
    streams = {tick: _status_stream(items) for tick, items in runs.items()}
    assert streams[100] == streams[900] == streams[None]
    assert streams[100] == [
        (0, "REGISTERED", "WORKED", None),
        (ACCEPT_MS, "WORKED", "NOT_NOTIFIED", ACCEPT_MS),
    ]

    for items in runs.values():
        names = [item["event_type"] for item in items]
        deadline_index = next(
            index
            for index, item in enumerate(items)
            if item["event_type"] == "DDS_CARD_STATUS_CHANGED"
            and item["payload"]["new_status"] == "NOT_NOTIFIED"
        )
        assert deadline_index < names.index("DDS_ACKNOWLEDGED"), (
            "the deadline event precedes the later-stamped command"
        )
        offsets = [item["monotonic_offset_ms"] for item in items]
        assert offsets == sorted(offsets), "offsets stay monotonic in seq_no order"
