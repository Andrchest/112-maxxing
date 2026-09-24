"""The ДДС in memo mode, over HTTP (I3 E5a/E5b, HLD 70 §70.4.1–§70.4.6; D16).

A memo session is the committed schema-2 example `street-rubbish-fire` as the product creates it:
its `variants` support `MEMO_STATUSES` and default to it, and it declares `responders: DEFAULT`
(rule R36, I3 E5b) — so `createSession` with no variant request resolves `dds_mode:
MEMO_STATUSES`. Nothing is patched. The prefab handoff materialises at start, one leg per notified
service (Служба 101, ЦОДД, ОАТИ — «КАРТОЧКА 112.docx» image 19 — and the territorial ДДС the
resolver adds), each in `ADDED`. The trainee then
walks each leg's `ServiceResponseStatus` one step at a time with `setDdsServiceStatus`, and closes
through the additive `ACKNOWLEDGED --close--> RESOLVED` row once every leg is terminal.

The 103 policy (`NO_REFUSAL`) needs an ambulance leg, which image 19 does not notify: that one test
runs the same example with `AMBULANCE` added to its prefab's recipients (`ambulance_version_id`) —
a real schema-2 document through the real import and validation, not a patch.

E5b adds the service binding: a ДДС participant bound to one service plays that leg, and every
other notified service is played by the scenario's scripted responder
(`test_a_bound_trainee_plays_one_leg_and_the_script_plays_the_others`).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
import yaml
from app.api.container import Container
from app.application.scenarios.import_scenarios import canonical_content, content_digest
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import ScenarioId, ScenarioVersionId, SessionId, UserId
from app.domain.scenario.version import ScenarioVersion
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.conftest import auth, participant

pytestmark = pytest.mark.integration

API = "/api/v1/sessions"
EXAMPLE_SLUG = "street-rubbish-fire"
EXAMPLE_PATH = (
    Path(__file__).resolve().parents[4] / "scenarios/examples/street-rubbish-fire/v1.yaml"
)
SERVICES = {"FIRE_RESCUE", "TSODD", "OATI", "DDS_DISTRICT_SHCHUKINO", "DDS_PREFECTURE_SZAO"}
"""The example's notification list (auto ∪ manual): image 19's services bar plus the territorial
ДДС of the district and the okrug the resolver adds (HLD 70 §70.6.4)."""
OTHERS = sorted(SERVICES - {"FIRE_RESCUE"})
"""Every leg but Служба 101 — the ones most tests simply decline to make the card closable."""


# ---------------------------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------------------------


@pytest.fixture
async def rubbish_version_id(
    unit_of_work: Any, demo_version_id: ScenarioVersionId
) -> ScenarioVersionId:
    """The committed example — `demo_version_id` imports every file under `scenarios/examples`."""
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(EXAMPLE_SLUG)
        assert stored is not None
        version = await uow.scenarios.find_version(stored.scenario_id, 1)
        assert version is not None
        await uow.commit()
    return version.scenario_version_id


@pytest.fixture
async def ambulance_version_id(unit_of_work: Any) -> ScenarioVersionId:
    """The example with `AMBULANCE` (103, `NO_REFUSAL`) added to its prefab's recipients."""
    slug = "street-rubbish-fire-with-103"
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(slug)
        row = await uow.scenarios.find_version(stored.scenario_id, 1) if stored else None
        await uow.commit()
    if row is not None:
        return ScenarioVersionId(row.scenario_version_id)
    document: dict[str, Any] = copy.deepcopy(yaml.safe_load(EXAMPLE_PATH.read_text("utf-8")))
    document["id"] = str(uuid4())
    document["scenario_id"] = str(uuid4())
    document["expected_response"]["prefab_handoff"]["recipient_services"].append("AMBULANCE")
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


async def start_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    version_id: ScenarioVersionId,
    *,
    assigned_service_id: str | None = None,
) -> UUID:
    """A started `SINGLE_ROLE` session of the example played by `trainee2` as the ДДС — no
    variant request, so the scenario's own default (`MEMO_STATUSES`) applies."""
    member = participant(users["trainee2"], "DDS")
    if assigned_service_id is not None:
        member["assigned_service_id"] = assigned_service_id
    created = await client.post(
        API,
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(version_id),
            "session_mode": "SINGLE_ROLE",
            "participants": [member],
        },
    )
    assert created.status_code == 201, created.text
    session_id = UUID(created.json()["id"])
    started = await client.post(f"{API}/{session_id}/start", headers=auth(tokens["instructor1"]))
    assert started.status_code == 200, started.text
    return session_id


@pytest.fixture
async def memo_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
) -> UUID:
    """The example's generated card in memo mode: legs `FIRE_RESCUE`, `TSODD`, `OATI`."""
    return await start_session(client, tokens, users, rubbish_version_id)


@pytest.fixture
async def ambulance_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    ambulance_version_id: ScenarioVersionId,
) -> UUID:
    """A memo session with a 103 leg besides the example's three."""
    return await start_session(client, tokens, users, ambulance_version_id)


async def legs(client: httpx.AsyncClient, token: str, session_id: UUID) -> dict[str, Any]:
    """`listDdsLegs`, keyed by service."""
    response = await client.get(f"{API}/{session_id}/dds/legs", headers=auth(token))
    assert response.status_code == 200, response.text
    return {leg["service_type"]: leg for leg in response.json()}


async def set_status(
    client: httpx.AsyncClient,
    token: str,
    session_id: UUID,
    assignment_id: str,
    status: str,
    **extra: Any,
) -> httpx.Response:
    """`setDdsServiceStatus`."""
    return await client.post(
        f"{API}/{session_id}/dds/legs/{assignment_id}/status",
        headers=auth(token),
        json={"status": status, **extra},
    )


async def walk(
    client: httpx.AsyncClient, token: str, session_id: UUID, assignment_id: str, *statuses: str
) -> dict[str, Any]:
    """Set each status in turn, asserting each step is accepted; returns the last leg view."""
    body: dict[str, Any] = {}
    for status in statuses:
        response = await set_status(client, token, session_id, assignment_id, status)
        assert response.status_code == 200, response.text
        body = response.json()
    return body


async def events(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID
) -> list[dict[str, Any]]:
    """The session's whole log, as the instructor reads it."""
    response = await client.get(
        f"{API}/{session_id}/events",
        headers=auth(tokens["instructor1"]),
        params={"limit": 1000},
    )
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def dds_state(client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID) -> str:
    """The DDS stage's state, read off `getSession`."""
    response = await client.get(f"{API}/{session_id}", headers=auth(tokens["instructor1"]))
    assert response.status_code == 200, response.text
    stage = next(item for item in response.json()["stages"] if item["role_type"] == "DDS")
    return str(stage["state"])


async def close(
    client: httpx.AsyncClient, token: str, session_id: UUID, reason: str = "RESOLVED"
) -> httpx.Response:
    """`closeDdsIncident`."""
    return await client.post(
        f"{API}/{session_id}/dds/close",
        headers=auth(token),
        json={"closure_reason": reason},
    )


# ---------------------------------------------------------------------------------------------
# The session and its legs
# ---------------------------------------------------------------------------------------------


async def test_a_memo_session_records_memo_and_starts_every_leg_added(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    log = await events(client, tokens, memo_session)
    created = next(item for item in log if item["event_type"] == "SESSION_CREATED")
    assert created["payload"]["variants"]["dds_mode"] == "MEMO_STATUSES"
    received = [item["payload"] for item in log if item["event_type"] == "HANDOFF_RECEIVED"]
    assert {payload["service_type"] for payload in received} == SERVICES
    for payload in received:
        assert payload["responder"] == "TRAINEE"
        assert payload["bound_user_id"] is None
        assert payload["initial_response_status"] == "ADDED"

    by_service = await legs(client, tokens["trainee2"], memo_session)
    assert {leg["response_status"] for leg in by_service.values()} == {"ADDED"}
    assert all(leg["is_mine"] for leg in by_service.values())
    assert {leg["responder"] for leg in by_service.values()} == {"TRAINEE"}
    for leg in by_service.values():
        assert {action["action_id"] for action in leg["available_actions"]} == {"accept", "decline"}


async def test_the_103_leg_offers_complete_without_brigade(
    client: httpx.AsyncClient, tokens: dict[str, str], ambulance_session: UUID
) -> None:
    by_service = await legs(client, tokens["trainee2"], ambulance_session)
    assert set(by_service) == SERVICES | {"AMBULANCE"}
    assert by_service["AMBULANCE"]["service_name_ru"] == "Скорая медицинская помощь"
    ambulance_actions = {
        action["action_id"] for action in by_service["AMBULANCE"]["available_actions"]
    }
    assert ambulance_actions == {"accept", "complete_without_brigade"}


async def test_no_resource_action_and_no_picker_acknowledge_in_memo_mode(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    for suffix in ("/dds/acknowledge", "/dds/resources/selection/open"):
        response = await client.post(
            f"{API}/{memo_session}{suffix}", headers=auth(tokens["trainee2"])
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


async def test_every_participant_reads_every_leg_but_only_the_ddss_may_set(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    trainee = await legs(client, tokens["trainee2"], memo_session)
    await walk(
        client,
        tokens["trainee2"],
        memo_session,
        trainee["FIRE_RESCUE"]["assignment_id"],
        "ACCEPTED",
    )

    instructor = await legs(client, tokens["instructor1"], memo_session)
    assert set(instructor) == SERVICES
    assert [entry["new_status"] for entry in instructor["FIRE_RESCUE"]["history"]] == [
        "RECEIVED",
        "ACCEPTED",
    ]
    assert not any(leg["is_mine"] for leg in instructor.values())
    assert all(leg["available_actions"] == [] for leg in instructor.values())
    response = await set_status(
        client,
        tokens["instructor1"],
        memo_session,
        instructor["TSODD"]["assignment_id"],
        "ACCEPTED",
    )
    assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------------------------
# The walk and the closure (the brief's two checks)
# ---------------------------------------------------------------------------------------------


async def test_one_leg_walks_every_status_and_the_stage_closes_through_resolved(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID, uow_factory: Any
) -> None:
    token = tokens["trainee2"]
    by_service = await legs(client, token, memo_session)
    fire = by_service["FIRE_RESCUE"]["assignment_id"]

    opened = await client.post(f"{API}/{memo_session}/dds/legs/{fire}/open", headers=auth(token))
    assert opened.status_code == 200, opened.text
    assert opened.json()["response_status"] == "RECEIVED"
    assert await dds_state(client, tokens, memo_session) == "RECEIVED"

    accepted = await walk(client, token, memo_session, fire, "ACCEPTED")
    assert accepted["response_status"] == "ACCEPTED"
    assert await dds_state(client, tokens, memo_session) == "ACKNOWLEDGED"

    final = await walk(
        client, token, memo_session, fire, "RESPONSE_STARTED", "ARRIVED", "WORKING", "COMPLETED"
    )
    assert final["response_status"] == "COMPLETED"
    assert [entry["new_status"] for entry in final["history"]] == [
        "RECEIVED",
        "ACCEPTED",
        "RESPONSE_STARTED",
        "ARRIVED",
        "WORKING",
        "COMPLETED",
    ]
    assert final["available_actions"] == []
    # The stage never left ACKNOWLEDGED while the legs moved (70 §70.4.4).
    assert await dds_state(client, tokens, memo_session) == "ACKNOWLEDGED"

    # Every other service declines (a comment each): straight from ADDED, receive first.
    for service in OTHERS:
        declined = await set_status(
            client,
            token,
            memo_session,
            by_service[service]["assignment_id"],
            "NOT_ACCEPTED",
            comment_ru="Не наша компетенция",
        )
        assert declined.status_code == 200, declined.text
        assert [entry["new_status"] for entry in declined.json()["history"]] == [
            "RECEIVED",
            "NOT_ACCEPTED",
        ]

    before = len(await events(client, tokens, memo_session))
    closed = await close(client, token, memo_session)
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "COMPLETED"
    log = await events(client, tokens, memo_session)
    emitted = [item for item in log[before:] if item["event_type"] != "SCORING_RULE_EVALUATED"]
    assert [item["event_type"] for item in emitted[:4]] == [
        "STAGE_STATE_CHANGED",
        "DDS_INCIDENT_CLOSED",
        "ROLE_STAGE_COMPLETED",
        "STAGE_STATE_CHANGED",
    ]
    moves = [
        (item["payload"]["previous_state"], item["payload"]["new_state"])
        for item in emitted
        if item["event_type"] == "STAGE_STATE_CHANGED"
    ]
    assert moves == [("ACKNOWLEDGED", "RESOLVED"), ("RESOLVED", "CLOSED")]
    assert "SESSION_COMPLETED" in [item["event_type"] for item in emitted]
    states = [
        item["payload"]["new_state"] for item in log if item["event_type"] == "STAGE_STATE_CHANGED"
    ]
    for never in ("RESOURCE_SELECTION", "DISPATCHED", "EN_ROUTE", "ARRIVED", "WORKING"):
        assert never not in states

    card = [item["payload"] for item in log if item["event_type"] == "DDS_CARD_STATUS_CHANGED"]
    assert card[-1]["new_status"] == "REFUSED"
    assert card[-1]["reason"] == "LEG_DECLINED_OR_REFUSED"
    async with uow_factory() as uow:
        assert isinstance(uow, SqlAlchemyUnitOfWork)
        stored = (
            await uow.session.execute(
                sa.text("SELECT card_status FROM incidents WHERE session_id = :id"),
                {"id": memo_session},
            )
        ).scalar_one()
        history_rows = (
            await uow.session.execute(
                sa.text("SELECT count(*) FROM dds_service_status_history WHERE session_id = :id"),
                {"id": memo_session},
            )
        ).scalar_one()
        await uow.commit()
    assert stored == "REFUSED"
    status_events = [item for item in log if item["event_type"] == "DDS_SERVICE_STATUS_SET"]
    assert history_rows == len(status_events) == 6 + 2 * len(OTHERS)


async def test_every_leg_not_accepted_closes_cleanly(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    """The O-1 case: no service takes the card, and the incident still closes."""
    token = tokens["trainee2"]
    by_service = await legs(client, token, memo_session)
    for service in sorted(SERVICES):
        response = await set_status(
            client,
            token,
            memo_session,
            by_service[service]["assignment_id"],
            "NOT_ACCEPTED",
            comment_ru="Не наша компетенция",
        )
        assert response.status_code == 200, response.text
        assert response.json()["response_status"] == "NOT_ACCEPTED"
    assert await dds_state(client, tokens, memo_session) == "ACKNOWLEDGED"

    log = await events(client, tokens, memo_session)
    acknowledged = [item for item in log if item["event_type"] == "DDS_ACKNOWLEDGED"]
    assert len(acknowledged) == 1, "only the first primary decision acknowledges the stage"
    card = [item["payload"] for item in log if item["event_type"] == "DDS_CARD_STATUS_CHANGED"]
    assert card[-1]["new_status"] == "REFUSED"

    closed = await close(client, token, memo_session, reason="TRANSFERRED")
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "COMPLETED"
    assert await dds_state(client, tokens, memo_session) == "CLOSED"


async def test_close_with_a_leg_still_open_is_409_invalid_transition(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    token = tokens["trainee2"]
    by_service = await legs(client, token, memo_session)
    await walk(client, token, memo_session, by_service["FIRE_RESCUE"]["assignment_id"], "ACCEPTED")
    before = len(await events(client, tokens, memo_session))

    response = await close(client, token, memo_session)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "INVALID_TRANSITION"
    assert len(await events(client, tokens, memo_session)) == before
    assert await dds_state(client, tokens, memo_session) == "ACKNOWLEDGED"


# ---------------------------------------------------------------------------------------------
# The leg machine's refusals
# ---------------------------------------------------------------------------------------------


async def test_skipping_a_status_is_409_and_appends_nothing(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    """A-8: one step at a time — `ACCEPTED → ARRIVED` skips «Начало реагирования»."""
    token = tokens["trainee2"]
    fire = (await legs(client, token, memo_session))["FIRE_RESCUE"]["assignment_id"]
    await walk(client, token, memo_session, fire, "ACCEPTED")
    before = len(await events(client, tokens, memo_session))

    for status in ("ARRIVED", "WORKING", "COMPLETED", "ADDED"):
        response = await set_status(client, token, memo_session, fire, status)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "INVALID_TRANSITION"

    assert len(await events(client, tokens, memo_session)) == before


@pytest.mark.parametrize("comment", [None, "", "   "])
async def test_not_accepted_without_a_comment_is_422_comment_required(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID, comment: str | None
) -> None:
    token = tokens["trainee2"]
    fire = (await legs(client, token, memo_session))["FIRE_RESCUE"]["assignment_id"]
    before = len(await events(client, tokens, memo_session))

    response = await set_status(
        client, token, memo_session, fire, "NOT_ACCEPTED", comment_ru=comment
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "COMMENT_REQUIRED"
    assert len(await events(client, tokens, memo_session)) == before


async def test_refusal_without_a_comment_is_422_and_with_one_is_terminal(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    token = tokens["trainee2"]
    fire = (await legs(client, token, memo_session))["FIRE_RESCUE"]["assignment_id"]
    await walk(client, token, memo_session, fire, "ACCEPTED", "RESPONSE_STARTED")

    missing = await set_status(client, token, memo_session, fire, "REFUSED")
    assert missing.status_code == 422, missing.text
    assert missing.json()["code"] == "COMMENT_REQUIRED"

    refused = await set_status(
        client, token, memo_session, fire, "REFUSED", comment_ru="Нет свободных расчётов"
    )
    assert refused.status_code == 200, refused.text
    assert refused.json()["response_status"] == "REFUSED"
    assert refused.json()["last_comment_ru"] == "Нет свободных расчётов"
    assert refused.json()["available_actions"] == []


async def test_103_cannot_refuse_and_completes_without_a_brigade(
    client: httpx.AsyncClient, tokens: dict[str, str], ambulance_session: UUID
) -> None:
    """REQ-5290: the `NO_REFUSAL` policy replaces «Не принята»/«Отказ» with
    `complete_without_brigade`; a `DEFAULT` service cannot use that shortcut."""
    token = tokens["trainee2"]
    by_service = await legs(client, token, ambulance_session)
    ambulance = by_service["AMBULANCE"]["assignment_id"]
    fire = by_service["FIRE_RESCUE"]["assignment_id"]

    declined = await set_status(
        client, token, ambulance_session, ambulance, "NOT_ACCEPTED", comment_ru="Не можем"
    )
    assert declined.status_code == 409, declined.text
    assert declined.json()["code"] == "INVALID_TRANSITION"
    shortcut = await set_status(client, token, ambulance_session, fire, "COMPLETED")
    assert shortcut.status_code == 409, shortcut.text

    await walk(client, token, ambulance_session, ambulance, "ACCEPTED", "RESPONSE_STARTED")
    refused = await set_status(
        client, token, ambulance_session, ambulance, "REFUSED", comment_ru="Не можем"
    )
    assert refused.status_code == 409, refused.text
    done = await walk(client, token, ambulance_session, ambulance, "COMPLETED")
    assert done["response_status"] == "COMPLETED"
    last = done["history"][-1]
    assert (last["previous_status"], last["completion_reason"]) == (
        "RESPONSE_STARTED",
        "WITHOUT_BRIGADE",
    )
    log = await events(client, tokens, ambulance_session)
    status_set = [item for item in log if item["event_type"] == "DDS_SERVICE_STATUS_SET"]
    assert status_set[-1]["payload"]["trigger"] == "complete_without_brigade"


# ---------------------------------------------------------------------------------------------
# Entries, opening, correction
# ---------------------------------------------------------------------------------------------


async def test_the_order_number_is_kept_per_entry(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    """A-2: «Номер наряда» is free text, optional, one per status entry — both kept."""
    token = tokens["trainee2"]
    fire = (await legs(client, token, memo_session))["FIRE_RESCUE"]["assignment_id"]
    first = await set_status(
        client, token, memo_session, fire, "ACCEPTED", order_number="Н-101", comment_ru="Приняли"
    )
    assert first.status_code == 200, first.text
    second = await set_status(
        client, token, memo_session, fire, "RESPONSE_STARTED", order_number="Н-102"
    )
    assert second.status_code == 200, second.text

    view = second.json()
    assert view["order_number"] == "Н-102"
    assert view["last_comment_ru"] is None
    entries = view["history"]
    assert [(entry["new_status"], entry["order_number"]) for entry in entries] == [
        ("RECEIVED", None),
        ("ACCEPTED", "Н-101"),
        ("RESPONSE_STARTED", "Н-102"),
    ]
    assert entries[1]["comment_ru"] == "Приняли"
    assert entries[1]["source"] == "TRAINEE"
    assert entries[0]["source"] == "SYSTEM"
    assert entries[0]["actor_display_ru"] == "Система"
    assert entries[1]["actor_display_ru"] != "Система"


async def test_opening_the_card_is_idempotent(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    token = tokens["trainee2"]
    fire = (await legs(client, token, memo_session))["FIRE_RESCUE"]["assignment_id"]
    url = f"{API}/{memo_session}/dds/legs/{fire}/open"

    first = await client.post(url, headers=auth(token))
    assert first.status_code == 200, first.text
    count = len(await events(client, tokens, memo_session))
    second = await client.post(url, headers=auth(token))
    assert second.status_code == 200, second.text

    assert len(await events(client, tokens, memo_session)) == count
    log = await events(client, tokens, memo_session)
    opened = [item for item in log if item["event_type"] == "DDS_CARD_OPENED"]
    assert len(opened) == 1
    assert opened[0]["actor_type"] == "TRAINEE"
    received = [item for item in log if item["event_type"] == "DDS_SERVICE_STATUS_SET"]
    assert [(item["actor_type"], item["payload"]["source"]) for item in received] == [
        ("SIMULATION", "SYSTEM")
    ]


async def test_an_unknown_leg_is_404(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    response = await set_status(client, tokens["trainee2"], memo_session, str(uuid4()), "ACCEPTED")
    assert response.status_code == 404, response.text


async def test_a_decline_can_be_corrected_to_accepted(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    """REQ-5327: Не принята → Принята; the card leaves «Отказ» (`LEG_STATUS_CORRECTED`)."""
    token = tokens["trainee2"]
    fire = (await legs(client, token, memo_session))["FIRE_RESCUE"]["assignment_id"]
    declined = await set_status(
        client, token, memo_session, fire, "NOT_ACCEPTED", comment_ru="Ошибочно"
    )
    assert declined.status_code == 200, declined.text
    corrected = await walk(client, token, memo_session, fire, "ACCEPTED")
    assert corrected["response_status"] == "ACCEPTED"

    log = await events(client, tokens, memo_session)
    card = [item["payload"] for item in log if item["event_type"] == "DDS_CARD_STATUS_CHANGED"]
    assert [(item["new_status"], item["reason"]) for item in card[-2:]] == [
        ("REFUSED", "LEG_DECLINED_OR_REFUSED"),
        ("WORKED", "LEG_STATUS_CORRECTED"),
    ]


# ---------------------------------------------------------------------------------------------
# Picker mode is untouched
# ---------------------------------------------------------------------------------------------


async def test_a_picker_session_refuses_set_service_status_and_open_card(
    client: httpx.AsyncClient, tokens: dict[str, str], dds_only_session: UUID
) -> None:
    """`dds_mode: RESOURCE_PICKER` ⇒ `409 ACTION_NOT_AVAILABLE` (the contract)."""
    by_service = await legs(client, tokens["trainee2"], dds_only_session)
    leg = next(iter(by_service.values()))
    assert leg["is_mine"] is False
    assert leg["available_actions"] == []

    status = await set_status(
        client, tokens["trainee2"], dds_only_session, leg["assignment_id"], "ACCEPTED"
    )
    assert status.status_code == 409, status.text
    assert status.json()["code"] == "ACTION_NOT_AVAILABLE"
    opened = await client.post(
        f"{API}/{dds_only_session}/dds/legs/{leg['assignment_id']}/open",
        headers=auth(tokens["trainee2"]),
    )
    assert opened.status_code == 409, opened.text
    assert opened.json()["code"] == "ACTION_NOT_AVAILABLE"


# ---------------------------------------------------------------------------------------------
# INV 9 — a memo session rescores identically
# ---------------------------------------------------------------------------------------------


async def test_a_memo_session_rescores_identically(
    client: httpx.AsyncClient, tokens: dict[str, str], memo_session: UUID
) -> None:
    """HLD 70 §70.1 (D5, INV 9): scoring reads `(ScenarioVersion, events)` only — the legs, their
    history and `incidents.card_status` are read models — so a closed memo session's stored report
    and a fresh `score()` over its log are the same checksum."""
    token = tokens["trainee2"]
    by_service = await legs(client, token, memo_session)
    fire = by_service["FIRE_RESCUE"]["assignment_id"]
    await walk(
        client,
        token,
        memo_session,
        fire,
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
            memo_session,
            by_service[service]["assignment_id"],
            "NOT_ACCEPTED",
            comment_ru="Не наша компетенция",
        )
        assert declined.status_code == 200, declined.text
    closed = await close(client, token, memo_session)
    assert closed.status_code == 200, closed.text

    rescored = await client.post(
        f"/api/v1/reports/{memo_session}/rescore",
        headers=auth(tokens["instructor1"]),
        json={"persist": False},
    )
    assert rescored.status_code == 200, rescored.text
    outcome = rescored.json()
    assert outcome["identical_to_stored"] is True
    assert outcome["stored_checksum"] == outcome["recomputed_checksum"]
    assert outcome["differences"] == []


# ---------------------------------------------------------------------------------------------
# I3 E5b — a bound ДДС trainee plays one leg, the scripted responders play the others
# ---------------------------------------------------------------------------------------------


async def test_a_bound_trainee_plays_one_leg_and_the_script_plays_the_others(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
    container: Container,
    clock: FakeClock,
) -> None:
    """HLD 70 §70.4.5, no test patching: `trainee2` is bound to Служба 101 (A); every other
    notified service (B) has no bound participant and answers by `responders: DEFAULT`. A's
    statuses are set by the trainee, B's by the script (SIMULATION, due-stamped), and the stage
    closes through the memo row once every leg is terminal."""
    token = tokens["trainee2"]
    session_id = await start_session(
        client, tokens, users, rubbish_version_id, assigned_service_id="FIRE_RESCUE"
    )
    log = await events(client, tokens, session_id)
    created = next(item for item in log if item["event_type"] == "SESSION_CREATED")
    assert created["payload"]["variants"]["dds_mode"] == "MEMO_STATUSES"
    received = {
        item["payload"]["service_type"]: item["payload"]
        for item in log
        if item["event_type"] == "HANDOFF_RECEIVED"
    }
    assert set(received) == SERVICES
    assert received["FIRE_RESCUE"]["responder"] == "TRAINEE"
    assert received["FIRE_RESCUE"]["bound_user_id"] == str(users["trainee2"])
    for service in OTHERS:
        assert (received[service]["responder"], received[service]["bound_user_id"]) == (
            "SCRIPTED",
            None,
        )

    by_service = await legs(client, token, session_id)
    fire = by_service["FIRE_RESCUE"]
    assert (fire["is_mine"], fire["responder"]) == (True, "TRAINEE")
    for service in OTHERS:
        assert by_service[service]["is_mine"] is False
        assert by_service[service]["available_actions"] == []

    # The trainee may not play a scripted leg — neither a status nor opening its card.
    scripted = by_service["TSODD"]["assignment_id"]
    refused = await set_status(client, token, session_id, scripted, "ACCEPTED")
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "FORBIDDEN_FOR_SERVICE"
    opened = await client.post(f"{API}/{session_id}/dds/legs/{scripted}/open", headers=auth(token))
    assert opened.status_code == 403, opened.text
    assert opened.json()["code"] == "FORBIDDEN_FOR_SERVICE"

    # A: the trainee's own walk; the first decision acknowledges the stage.
    await walk(client, token, session_id, fire["assignment_id"], "ACCEPTED")
    assert await dds_state(client, tokens, session_id) == "ACKNOWLEDGED"
    final = await walk(
        client,
        token,
        session_id,
        fire["assignment_id"],
        "RESPONSE_STARTED",
        "ARRIVED",
        "WORKING",
        "COMPLETED",
    )
    assert {entry["source"] for entry in final["history"][1:]} == {"TRAINEE"}

    # B is not done before its schedule: closing is the ordinary 409.
    early = await close(client, token, session_id)
    assert early.status_code == 409, early.text
    assert early.json()["code"] == "INVALID_TRANSITION"

    clock.advance_ms(600_000)
    await container.runner.tick_now(SessionId(session_id))
    by_service = await legs(client, token, session_id)
    for service in OTHERS:
        leg = by_service[service]
        assert leg["response_status"] == "COMPLETED"
        history = leg["history"]
        assert [entry["new_status"] for entry in history] == [
            "RECEIVED",
            "ACCEPTED",
            "RESPONSE_STARTED",
            "ARRIVED",
            "WORKING",
            "COMPLETED",
        ]
        assert [entry["at_offset_ms"] for entry in history] == [
            0,
            15_000,
            60_000,
            180_000,
            200_000,
            600_000,
        ]
        assert {entry["source"] for entry in history} == {"SCRIPTED_RESPONDER"}
        assert {entry["actor_display_ru"] for entry in history} == {leg["service_name_ru"]}

    closed = await close(client, token, session_id)
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "COMPLETED"
    log = await events(client, tokens, session_id)
    moves = [
        (item["payload"]["previous_state"], item["payload"]["new_state"])
        for item in log
        if item["event_type"] == "STAGE_STATE_CHANGED"
    ]
    assert moves[-2:] == [("ACKNOWLEDGED", "RESOLVED"), ("RESOLVED", "CLOSED")]
    scripted_events = [
        item
        for item in log
        if item["event_type"] == "DDS_SERVICE_STATUS_SET"
        and item["payload"]["source"] == "SCRIPTED_RESPONDER"
    ]
    assert len(scripted_events) == 6 * len(OTHERS)
    assert {item["actor_type"] for item in scripted_events} == {"SIMULATION"}
