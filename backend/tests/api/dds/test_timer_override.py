"""`createSession` with a timer override, over HTTP (I4 E31, HLD 71 §71.8, D34; ТЗ ¶240).

The instructor sets the card's timers at creation (`SessionCreateRequest.timers`); they resolve as
scenario ← request, key by key, and `SESSION_CREATED.timers` records the result. A `DEADLINE` rule
with `max_offset_timer: accept_within_ms` then scores the ДДС decision against the recorded value.

The scenario is the committed memo example `street-rubbish-fire` plus the tickets' memo decision
rule (`memo_main_service_decision_in_time`, as E31 rewrote it) — a real schema-2 document through
the real import and validation, as `test_memo_mode.py`'s `ambulance_version_id` does.

INV 9 over the wire: a session created with a 60 s accept timer, whose Служба 101 decision comes
45 s after the card arrived, is stored with that rule **passed** (the scenario's 30 s would have
failed it), and `rescoreSession` answers `identical_to_stored: true`.
"""

from __future__ import annotations

import copy
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import yaml
from app.application.scenarios.import_scenarios import canonical_content, content_digest
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import ScenarioId, ScenarioVersionId, UserId
from app.domain.scenario.version import ScenarioVersion

from tests.api.conftest import auth, participant
from tests.api.dds.test_memo_mode import (
    API,
    EXAMPLE_PATH,
    OTHERS,
    close,
    events,
    legs,
    set_status,
    walk,
)

pytestmark = pytest.mark.integration

MEMO_RULE = "memo_main_service_decision_in_time"
TIMER_RULE: dict[str, Any] = {
    "rule_id": MEMO_RULE,
    "name_ru": "Решение по службе «Пожарно-спасательная служба» в течение 30 секунд",
    "description_ru": "От поступления карточки до статуса «Принята» или «Не принята».",
    "category": "TIMELINESS",
    "max_points": 4,
    "critical": False,
    "evaluator_type": "DEADLINE",
    "applies_to_roles": ["DDS"],
    "applies_to_variants": {"dds_mode": ["MEMO_STATUSES"]},
    "min_evidence": 1,
    "config": {
        "from_event_type": "HANDOFF_RECEIVED",
        "to_event_type": "DDS_SERVICE_STATUS_SET",
        "to_payload_match": {
            "service_type": "FIRE_RESCUE",
            "new_status": ["ACCEPTED", "NOT_ACCEPTED"],
        },
        "max_offset_timer": "accept_within_ms",
        "points": 4,
        "penalty_if_late": -2,
        "scale": "STEP",
        "linear_zero_ms": None,
    },
}


@pytest.fixture
async def timer_version_id(
    unit_of_work: Any, demo_version_id: ScenarioVersionId
) -> ScenarioVersionId:
    """The memo example with the tickets' timer-driven decision rule (self-healing)."""
    slug = "street-rubbish-fire-accept-timer"
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(slug)
        row = await uow.scenarios.find_version(stored.scenario_id, 1) if stored else None
        await uow.commit()
    if row is not None:
        return ScenarioVersionId(row.scenario_version_id)
    document: dict[str, Any] = copy.deepcopy(yaml.safe_load(EXAMPLE_PATH.read_text("utf-8")))
    document["id"] = str(uuid4())
    document["scenario_id"] = str(uuid4())
    document["scoring_rules"].append(copy.deepcopy(TIMER_RULE))
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


async def _create(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    version_id: ScenarioVersionId,
    timers: dict[str, int] | None,
) -> httpx.Response:
    body: dict[str, Any] = {
        "scenario_version_id": str(version_id),
        "session_mode": "SINGLE_ROLE",
        "participants": [participant(users["trainee2"], "DDS")],
    }
    if timers is not None:
        body["timers"] = timers
    return await client.post(API, headers=auth(tokens["instructor1"]), json=body)


async def _recorded_timers(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID
) -> dict[str, Any]:
    created = next(
        e for e in await events(client, tokens, session_id) if e["event_type"] == "SESSION_CREATED"
    )
    timers: dict[str, Any] = created["payload"]["timers"]
    return timers


async def test_the_override_is_resolved_per_key_and_recorded(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    timer_version_id: ScenarioVersionId,
) -> None:
    overridden = await _create(
        client, tokens, users, timer_version_id, {"accept_within_ms": 60_000}
    )
    assert overridden.status_code == 201, overridden.text
    assert await _recorded_timers(client, tokens, UUID(overridden.json()["id"])) == {
        "accept_within_ms": 60_000,
        "fill_within_ms": 180_000,
        "not_completed_after_ms": 172_800_000,
    }

    plain = await _create(client, tokens, users, timer_version_id, None)
    assert plain.status_code == 201, plain.text
    assert (await _recorded_timers(client, tokens, UUID(plain.json()["id"])))[
        "accept_within_ms"
    ] == 30_000, "no override keeps the scenario's timers"


@pytest.mark.parametrize(
    "timers",
    [
        {"not_completed_after_ms": 20_000},  # R39: below the scenario's 30 s accept timer
        {"accept_within_ms": 0},
        {"accept_within_ms": 30_000, "handoff_within_ms": 1},
    ],
)
async def test_an_invalid_override_is_422_and_creates_nothing(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    timer_version_id: ScenarioVersionId,
    timers: dict[str, int],
) -> None:
    listed = await client.get(API, headers=auth(tokens["instructor1"]))
    before = listed.json()["total"]
    response = await _create(client, tokens, users, timer_version_id, timers)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    after = (await client.get(API, headers=auth(tokens["instructor1"]))).json()["total"]
    assert after == before


async def test_an_overridden_session_is_scored_by_its_recorded_timer_and_rescores_identically(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    clock: FakeClock,
    timer_version_id: ScenarioVersionId,
) -> None:
    """INV 9 with an overridden timer, through the real endpoints and PostgreSQL."""
    created = await _create(client, tokens, users, timer_version_id, {"accept_within_ms": 60_000})
    assert created.status_code == 201, created.text
    session_id = UUID(created.json()["id"])
    started = await client.post(f"{API}/{session_id}/start", headers=auth(tokens["instructor1"]))
    assert started.status_code == 200, started.text

    token = tokens["trainee2"]
    by_service = await legs(client, token, session_id)
    clock.advance_ms(45_000)  # later than the scenario's 30 s, within the session's 60 s
    await walk(
        client,
        token,
        session_id,
        by_service["FIRE_RESCUE"]["assignment_id"],
        "ACCEPTED",
        "RESPONSE_STARTED",
        "ARRIVED",
        "WORKING",
        "COMPLETED",
    )
    for service in OTHERS:
        declined = await set_status(
            client,
            token,
            session_id,
            by_service[service]["assignment_id"],
            "NOT_ACCEPTED",
            comment_ru="Не наша компетенция",
        )
        assert declined.status_code == 200, declined.text
    closed = await close(client, token, session_id)
    assert closed.status_code == 200, closed.text

    report = await client.get(f"/api/v1/reports/{session_id}", headers=auth(tokens["instructor1"]))
    assert report.status_code == 200, report.text
    memo = next(r for r in report.json()["score_report"]["results"] if r["rule_id"] == MEMO_RULE)
    assert memo["passed"] is True and memo["points_awarded"] == 4
    assert any("при норме 60000 мс" in item["note_ru"] for item in memo["evidence"])

    rescored = await client.post(
        f"/api/v1/reports/{session_id}/rescore",
        headers=auth(tokens["instructor1"]),
        json={"persist": False},
    )
    assert rescored.status_code == 200, rescored.text
    outcome = rescored.json()
    assert outcome["identical_to_stored"] is True
    assert outcome["stored_checksum"] == outcome["recomputed_checksum"]
    assert outcome["differences"] == []
