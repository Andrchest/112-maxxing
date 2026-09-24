"""«Отметить ошибку в карточке» — `flagDdsCardIssue` under `dds_card_check` (I3 E5b, HLD 70
§70.2.4, §70.4.4, §70.7; C1, D19).

The switch defaults `OFF` (the customer's 23.09 answer: the ДДС does not check the 112 card), and
then the action does not exist — `409 ACTION_NOT_AVAILABLE`. `ON` (the 18.09 reading) offers it in
the memo `ACKNOWLEDGED` state: one TRAINEE `DDS_CARD_ISSUE_FLAGGED`, recorded against the frozen
snapshot only, visible to the ДДС and the instructor, and carried into the report's DDS decisions.
Sessions are the committed schema-2 example `street-rubbish-fire` (memo by default, card check
supported `OFF`/`ON`).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
from app.domain.common.ids import ScenarioVersionId, UserId

from tests.api.conftest import auth, participant

pytestmark = pytest.mark.integration

API = "/api/v1/sessions"


@pytest.fixture
async def rubbish_version_id(
    unit_of_work: Any, demo_version_id: ScenarioVersionId
) -> ScenarioVersionId:
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug("street-rubbish-fire")
        assert stored is not None
        version = await uow.scenarios.find_version(stored.scenario_id, 1)
        assert version is not None
        await uow.commit()
    return version.scenario_version_id


async def _session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    version_id: ScenarioVersionId,
    *,
    card_check: str | None,
    assigned_service_id: str | None = None,
    dds_mode: str | None = None,
) -> UUID:
    member = participant(users["trainee2"], "DDS")
    if assigned_service_id is not None:
        member["assigned_service_id"] = assigned_service_id
    body: dict[str, Any] = {
        "scenario_version_id": str(version_id),
        "session_mode": "SINGLE_ROLE",
        "participants": [member],
    }
    variants = {"dds_card_check": card_check, "dds_mode": dds_mode}
    if any(value is not None for value in variants.values()):
        body["variants"] = {key: value for key, value in variants.items() if value is not None}
    created = await client.post(API, headers=auth(tokens["instructor1"]), json=body)
    assert created.status_code == 201, created.text
    session_id = UUID(created.json()["id"])
    started = await client.post(f"{API}/{session_id}/start", headers=auth(tokens["instructor1"]))
    assert started.status_code == 200, started.text
    return session_id


async def _legs(client: httpx.AsyncClient, token: str, session_id: UUID) -> dict[str, Any]:
    response = await client.get(f"{API}/{session_id}/dds/legs", headers=auth(token))
    assert response.status_code == 200, response.text
    return {leg["service_type"]: leg for leg in response.json()}


async def _flag(
    client: httpx.AsyncClient, token: str, session_id: UUID, **body: Any
) -> httpx.Response:
    return await client.post(f"{API}/{session_id}/dds/card-issues", headers=auth(token), json=body)


async def _accept(client: httpx.AsyncClient, token: str, session_id: UUID, leg: Any) -> None:
    response = await client.post(
        f"{API}/{session_id}/dds/legs/{leg['assignment_id']}/status",
        headers=auth(token),
        json={"status": "ACCEPTED"},
    )
    assert response.status_code == 200, response.text


async def _events(client: httpx.AsyncClient, token: str, session_id: UUID) -> list[dict[str, Any]]:
    response = await client.get(
        f"{API}/{session_id}/events", headers=auth(token), params={"limit": 1000}
    )
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def test_card_check_off_is_the_default_and_offers_no_flag(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
) -> None:
    token = tokens["trainee2"]
    session_id = await _session(client, tokens, users, rubbish_version_id, card_check=None)
    detail = await client.get(f"{API}/{session_id}", headers=auth(tokens["instructor1"]))
    assert detail.json()["variants"]["dds_card_check"] == "OFF"
    fire = (await _legs(client, token, session_id))["FIRE_RESCUE"]
    await _accept(client, token, session_id, fire)

    response = await _flag(
        client,
        token,
        session_id,
        assignment_id=fire["assignment_id"],
        issue_kind="WRONG",
        comment_ru="Адрес не тот",
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"
    snapshot = await client.get(f"{API}/{session_id}/snapshot", headers=auth(token))
    actions = {action["action_id"] for action in snapshot.json()["available_actions"]}
    assert "flag_card_issue" not in actions


async def test_card_check_on_records_a_flag_against_the_snapshot(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
) -> None:
    token = tokens["trainee2"]
    session_id = await _session(client, tokens, users, rubbish_version_id, card_check="ON")
    fire = (await _legs(client, token, session_id))["FIRE_RESCUE"]

    # Offered in memo ACKNOWLEDGED only: before the first decision the stage is RECEIVED.
    early = await _flag(
        client,
        token,
        session_id,
        assignment_id=fire["assignment_id"],
        issue_kind="MISSING",
        comment_ru="Нет подъезда",
    )
    assert early.status_code == 409, early.text
    assert early.json()["code"] == "ACTION_NOT_AVAILABLE"

    await _accept(client, token, session_id, fire)
    snapshot = await client.get(f"{API}/{session_id}/snapshot", headers=auth(token))
    actions = [action["action_id"] for action in snapshot.json()["available_actions"]]
    assert actions == ["set_service_status", "send_status_update", "flag_card_issue", "close"]

    blank = await _flag(
        client,
        token,
        session_id,
        assignment_id=fire["assignment_id"],
        issue_kind="OTHER",
        comment_ru="   ",
    )
    assert blank.status_code == 422, blank.text
    assert blank.json()["code"] == "COMMENT_REQUIRED"
    unknown = await _flag(
        client,
        token,
        session_id,
        assignment_id=fire["assignment_id"],
        field_path="no.such.path",
        issue_kind="WRONG",
        comment_ru="?",
    )
    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["code"] == "CARD_FIELD_UNKNOWN"

    flagged = await _flag(
        client,
        token,
        session_id,
        assignment_id=fire["assignment_id"],
        field_path="address.house",
        issue_kind="WRONG",
        comment_ru="Номер дома не совпадает с описанием",
    )
    assert flagged.status_code == 201, flagged.text
    view = flagged.json()
    assert view["assignment_id"] == fire["assignment_id"]
    assert (view["field_path"], view["issue_kind"]) == ("address.house", "WRONG")

    for reader in (token, tokens["instructor1"]):
        log = await _events(client, reader, session_id)
        events = [item for item in log if item["event_type"] == "DDS_CARD_ISSUE_FLAGGED"]
        assert len(events) == 1
        assert events[0]["actor_type"] == "TRAINEE"
        assert events[0]["payload"]["comment_ru"] == "Номер дома не совпадает с описанием"
        assert events[0]["payload"]["field_path"] == "address.house"


async def test_a_flag_is_raised_by_the_service_that_plays_the_leg(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
) -> None:
    """A trainee bound to Служба 101 cannot flag on a scripted service's leg (§70.4.5)."""
    token = tokens["trainee2"]
    session_id = await _session(
        client,
        tokens,
        users,
        rubbish_version_id,
        card_check="ON",
        assigned_service_id="FIRE_RESCUE",
    )
    by_service = await _legs(client, token, session_id)
    await _accept(client, token, session_id, by_service["FIRE_RESCUE"])

    response = await _flag(
        client,
        token,
        session_id,
        assignment_id=by_service["TSODD"]["assignment_id"],
        issue_kind="CONTRADICTION",
        comment_ru="Противоречие в описании",
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_SERVICE"


@pytest.mark.parametrize(("card_check", "status"), [("ON", 201), ("OFF", 409)])
async def test_a_picker_session_flags_under_card_check_on_only(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
    card_check: str,
    status: int,
) -> None:
    """§70.11 supports card check in both modes: the picker ДДС flags once it holds the card
    (`ACKNOWLEDGED` onwards); `OFF` is the ordinary `409 ACTION_NOT_AVAILABLE`."""
    token = tokens["trainee2"]
    session_id = await _session(
        client,
        tokens,
        users,
        rubbish_version_id,
        card_check=card_check,
        dds_mode="RESOURCE_PICKER",
    )
    acknowledged = await client.post(f"{API}/{session_id}/dds/acknowledge", headers=auth(token))
    assert acknowledged.status_code == 200, acknowledged.text
    actions = {action["action_id"] for action in acknowledged.json()["available_actions"]}
    assert ("flag_card_issue" in actions) is (card_check == "ON")
    fire = (await _legs(client, token, session_id))["FIRE_RESCUE"]

    response = await _flag(
        client,
        token,
        session_id,
        assignment_id=fire["assignment_id"],
        field_path="address.house",
        issue_kind="WRONG",
        comment_ru="Номер дома не совпадает",
    )
    assert response.status_code == status, response.text
    if status == 409:
        assert response.json()["code"] == "ACTION_NOT_AVAILABLE"
    else:
        log = await _events(client, tokens["instructor1"], session_id)
        assert [item["event_type"] for item in log].count("DDS_CARD_ISSUE_FLAGGED") == 1
