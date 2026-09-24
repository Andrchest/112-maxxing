"""INV 7, I3 E5b — the scripted-responder stream does not depend on the tick rate (HLD 70 §70.1,
§70.4.5).

"Same seed + actions ⇒ same world events", extended to the scripted responders: a `SCRIPTED` leg
(a notified service no ДДС participant is bound to) walks its `expected_response.responders`
script, fired by stage automation as SIMULATION and **stamped with each step's due offset** (the
leg's `HANDOFF_RECEIVED` + `after_ms`), never with the tick's. Interleaved with them are the
card-status deadline events (`DDS_CARD_STATUS_CHANGED`, flush-before-append, §70.3.5): the scripted
legs accept after the accept window, so the card turns «Не оповещено» *between* two scripted steps.

The same session — the schema-2 example `street-rubbish-fire` with a short explicit script for
every unbound service and a one-second accept window, `trainee2` bound to Служба 101 and doing
nothing — is run three times: ticking every 100 ms, every 900 ms, and not at all until the end. The
scripted `DDS_SERVICE_STATUS_SET` stream and the card-status stream must be identical, and offsets
stay monotonic in `seq_no` order.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import yaml
from app.application.scenarios.import_scenarios import canonical_content, content_digest
from app.domain.common.ids import ScenarioId, ScenarioVersionId, SessionId
from app.domain.scenario.version import ScenarioVersion

from tests.api import conftest as _api_fixtures
from tests.api.handoff import conftest as _handoff_fixtures

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

auth = _api_fixtures.auth

EXAMPLE_PATH = (
    Path(__file__).resolve().parents[3] / "scenarios/examples/street-rubbish-fire/v1.yaml"
)
END_MS = 4_000
"""Every script below has ended by then."""

SCRIPTS: dict[str, list[dict[str, Any]]] = {
    "TSODD": [
        {"after_ms": 0, "status": "RECEIVED"},
        {"after_ms": 1_450, "status": "ACCEPTED", "order_number": "Ц-1"},
        {"after_ms": 2_050, "status": "RESPONSE_STARTED"},
        {"after_ms": 2_700, "status": "ARRIVED"},
        {"after_ms": 2_750, "status": "WORKING"},
        {"after_ms": 3_900, "status": "COMPLETED"},
    ],
    "OATI": [
        {"after_ms": 350, "status": "RECEIVED"},
        {"after_ms": 1_250, "status": "NOT_ACCEPTED", "comment_ru": "Не наша компетенция"},
    ],
    "DDS_DISTRICT_SHCHUKINO": [
        {"after_ms": 1_550, "status": "ACCEPTED"},
        {"after_ms": 2_050, "status": "REFUSED", "comment_ru": "Нет сил"},
    ],
    "DDS_PREFECTURE_SZAO": [
        {"after_ms": 0, "status": "RECEIVED"},
        {"after_ms": 850, "status": "ACCEPTED"},
        {"after_ms": 3_333, "status": "RESPONSE_STARTED"},
    ],
}
"""Scripts for every service but the bound one: steps on and between tick boundaries, a decline
and a refusal, an implicit `receive` (the district ДДС), one leg accepted inside the accept window
(the prefecture) and the rest after it."""


@pytest.fixture
async def scripted_version_id(unit_of_work: Any) -> ScenarioVersionId:
    """The example with a one-second accept window and `SCRIPTS` (self-healing)."""
    slug = "street-rubbish-fire-short-scripts"
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(slug)
        row = await uow.scenarios.find_version(stored.scenario_id, 1) if stored else None
        await uow.commit()
    if row is not None:
        return ScenarioVersionId(row.scenario_version_id)
    document: dict[str, Any] = copy.deepcopy(yaml.safe_load(EXAMPLE_PATH.read_text("utf-8")))
    document["id"] = str(uuid4())
    document["scenario_id"] = str(uuid4())
    document["timers"] = {"accept_within_ms": 1_000, "not_completed_after_ms": 3_500}
    document["expected_response"]["responders"] = SCRIPTS
    version = ScenarioVersion(**document)
    content = canonical_content(version)
    async with unit_of_work() as uow:
        await uow.scenarios.add_scenario(
            ScenarioId(UUID(document["scenario_id"])), slug, version.title
        )
        await uow.scenarios.add_version(version, content, content_digest(content))
        await uow.scenarios.add_scoring_rules(version.id, version.scoring_rules)
        await uow.commit()
    return version.id


async def _run(
    client: Any,
    container: Any,
    clock: Any,
    tokens: dict[str, str],
    users: Any,
    version: Any,
    tick_ms: int | None,
) -> list[dict[str, Any]]:
    """One memo session, `trainee2` bound to Служба 101; tick every `tick_ms` (or at the end)."""
    created = await client.post(
        "/api/v1/sessions",
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(version),
            "session_mode": "SINGLE_ROLE",
            "participants": [
                {
                    "user_id": str(users["trainee2"]),
                    "assigned_role_type": "DDS",
                    "assigned_service_id": "FIRE_RESCUE",
                }
            ],
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
        while elapsed + tick_ms < END_MS:
            clock.advance_ms(tick_ms)
            elapsed += tick_ms
            await container.runner.tick_now(SessionId(UUID(session_id)))
    clock.advance_ms(END_MS - elapsed)
    await container.runner.tick_now(SessionId(UUID(session_id)))
    events = await client.get(
        f"/api/v1/sessions/{session_id}/events",
        headers=auth(tokens["instructor1"]),
        params={"limit": 1000},
    )
    assert events.status_code == 200, events.text
    items: list[dict[str, Any]] = events.json()["items"]
    return items


def _stream(items: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """The scripted status steps and the card-status changes, in `seq_no` order, without ids."""
    stream: list[tuple[Any, ...]] = []
    for item in items:
        payload = item["payload"]
        if item["event_type"] == "DDS_SERVICE_STATUS_SET":
            stream.append(
                (
                    item["monotonic_offset_ms"],
                    item["actor_type"],
                    payload["service_type"],
                    payload["previous_status"],
                    payload["new_status"],
                    payload["trigger"],
                    payload["source"],
                    payload["order_number"],
                    payload["comment_ru"],
                )
            )
        elif item["event_type"] == "DDS_CARD_STATUS_CHANGED":
            stream.append(
                (
                    item["monotonic_offset_ms"],
                    "CARD",
                    payload["previous_status"],
                    payload["new_status"],
                    payload["reason"],
                    payload["deadline_offset_ms"],
                )
            )
    return stream


async def test_ticking_every_100_ms_or_900_ms_or_once_gives_one_scripted_stream(
    client: Any,
    container: Any,
    clock: Any,
    tokens: dict[str, str],
    users: Any,
    scripted_version_id: Any,
) -> None:
    runs = {
        tick: await _run(client, container, clock, tokens, users, scripted_version_id, tick)
        for tick in (100, 900, None)
    }
    streams = {tick: _stream(items) for tick, items in runs.items()}
    assert streams[100] == streams[900] == streams[None]

    scripted = [entry for entry in streams[100] if entry[1] == "SIMULATION"]
    assert {entry[6] for entry in scripted} == {"SCRIPTED_RESPONDER"}
    by_service: dict[str, list[tuple[int, str]]] = {}
    for entry in scripted:
        by_service.setdefault(entry[2], []).append((entry[0], entry[4]))
    assert by_service == {
        "TSODD": [
            (0, "RECEIVED"),
            (1_450, "ACCEPTED"),
            (2_050, "RESPONSE_STARTED"),
            (2_700, "ARRIVED"),
            (2_750, "WORKING"),
            (3_900, "COMPLETED"),
        ],
        "OATI": [(350, "RECEIVED"), (1_250, "NOT_ACCEPTED")],
        "DDS_DISTRICT_SHCHUKINO": [(1_550, "RECEIVED"), (1_550, "ACCEPTED"), (2_050, "REFUSED")],
        "DDS_PREFECTURE_SZAO": [(0, "RECEIVED"), (850, "ACCEPTED"), (3_333, "RESPONSE_STARTED")],
    }
    card = [entry for entry in streams[100] if entry[1] == "CARD"]
    assert (1_000, "CARD", "WORKED", "NOT_NOTIFIED", "ACCEPT_DEADLINE_MISSED", 1_000) in card

    for items in runs.values():
        offsets = [item["monotonic_offset_ms"] for item in items]
        assert offsets == sorted(offsets), "offsets stay monotonic in seq_no order"
        deadline = next(
            index
            for index, item in enumerate(items)
            if item["event_type"] == "DDS_CARD_STATUS_CHANGED"
            and item["payload"]["new_status"] == "NOT_NOTIFIED"
        )
        later = next(
            index
            for index, item in enumerate(items)
            if item["event_type"] == "DDS_SERVICE_STATUS_SET"
            and item["monotonic_offset_ms"] > 1_000
        )
        assert deadline < later, "the deadline precedes the later-stamped scripted step"
