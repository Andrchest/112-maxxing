"""`MULTI_TRAINEE` with two distinct participants, end to end over real HTTP (E17-D, R6).

`create_demo_session`'s own default mode (`tests.api.conftest`) is already `MULTI_TRAINEE`, and
`flow`/`handed_off`/`in_transition`/`dds_active` (`tests.api.operator.conftest`,
`tests.api.handoff.conftest`) already build it with two *distinct* users — `trainee1` on
`OPERATOR_112`, `trainee2` on `DDS` (`ONE_PARTICIPANT_PER_STAGE`, §10.10). What no existing
module proves is the three things R6 asks for about that split:

1. each trainee may act **only** on their own stage — the operator user gets `403` on a `DDS`
   command and the DDS user gets `403` on an `OPERATOR_112` one, in both directions and on both
   sides of the hand-over;
2. the second user's (`DDS`'s) view is `DDS`-redacted **before their own stage is even active**:
   their snapshot never carries the live `OperatorCard` or the DDS work item before the hand-over
   completes, and `GET /events` — documented (`app.api.routers.realtime`'s own docstring) to be
   byte-identical to the WebSocket's own redaction — never carries an `OPERATOR_112`-only event
   type (`CARD_FIELD_CHANGED`) for them, though the instructor's unredacted view does;
3. only the next-stage holder or the instructor may `continueToNextStage` (§10.8's guard, restated
   here for `MULTI_TRAINEE` specifically rather than relied on from `tests/api/handoff`);
4. (I3 E5b, HLD 70 §70.4.5) **two ДДС trainees** in one memo session of the schema-2 example
   `street-rubbish-fire`, each bound to a service (`assigned_service_id`, distinct per session):
   each plays only their own leg (`403 FORBIDDEN_FOR_SERVICE` on the other's), both see every
   leg, either may issue memo commands, the unbound services answer by script, and the report
   carries each leg's status history and the per-participant totals.

CONCURRENCY: no concrete offset is asserted anywhere near the transition (E17-B); no exact
dispatch/closure payload key set is asserted (E17-A).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
from app.api.container import Container
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId

from tests.api.conftest import auth, participant
from tests.api.dds.conftest import event_types as _dds_event_types
from tests.api.handoff.conftest import OperatorFlow

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------------------------
# 1. Each trainee may act only on their own stage
# ---------------------------------------------------------------------------------------------


async def test_the_operator_trainee_cannot_issue_a_dds_command_before_the_handover(
    handed_off: OperatorFlow,
) -> None:
    response = await handed_off.post("/dds/acknowledge", token=handed_off.operator_token)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_dds_trainee_cannot_issue_a_dds_command_before_the_handover(
    handed_off: OperatorFlow,
) -> None:
    """The `DDS` participant is bound to the *next* stage, not the active one — still `403`."""
    response = await handed_off.post("/dds/acknowledge", token=handed_off.dds_token)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_dds_trainee_may_act_once_their_stage_is_active(
    dds_active: OperatorFlow,
) -> None:
    response = await dds_active.post("/dds/acknowledge", token=dds_active.dds_token)
    assert response.status_code == 200, response.text


async def test_the_operator_trainee_may_not_act_once_the_dds_stage_is_active(
    dds_active: OperatorFlow,
) -> None:
    """Their own stage is `STAGE_COMPLETED`, and it is no longer the session's active stage."""
    response = await dds_active.put(
        "/operator/card/field",
        token=dds_active.operator_token,
        json={"field_path": "description.text", "new_value": "x"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_dds_trainee_may_not_issue_an_operator_command(dds_active: OperatorFlow) -> None:
    response = await dds_active.put(
        "/operator/card/field",
        token=dds_active.dds_token,
        json={"field_path": "description.text", "new_value": "x"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


# ---------------------------------------------------------------------------------------------
# 2. The second user's (DDS's) view is DDS-redacted before their own stage starts
# ---------------------------------------------------------------------------------------------


async def test_the_dds_trainees_snapshot_never_carries_the_operator_card(
    handed_off: OperatorFlow,
) -> None:
    """`createHandoff` has already run (legs exist), and still: not the card, not the work item —
    the DDS stage is not the *active* one yet, and `getSessionSnapshot`'s `work_item` branch is
    gated on that, not merely on the legs existing (`app.application.sessions.get_snapshot`)."""
    operator_view = (await handed_off.snapshot(token=handed_off.operator_token)).json()
    assert operator_view["card"] is not None
    assert operator_view["card"]["values"]["description.text"], "the operator's own card, live"

    dds_view = (await handed_off.snapshot(token=handed_off.dds_token)).json()
    assert dds_view["card"] is None, "D3: the DDS participant never receives the live card"
    assert dds_view["work_item"] is None, "not the active stage yet, so no work item either"
    assert dds_view["available_actions"] == [], "not their stage's turn"


async def test_events_visible_to_the_dds_trainee_exclude_operator_only_event_types(
    handed_off: OperatorFlow,
) -> None:
    """§40.4: `CARD_FIELD_CHANGED` is `OPERATOR_112`-only. Same redaction function as the
    WebSocket (`app.application.realtime.redaction.redact`, `GET /events` and the socket are
    documented byte-identical), so this is a faithful stand-in for "the DDS trainee's WS frames
    are DDS-redacted" without needing a second live socket in this module."""
    operator_seen = await _dds_event_types(handed_off, token=handed_off.operator_token)
    dds_seen = await _dds_event_types(handed_off, token=handed_off.dds_token)
    instructor_seen = await _dds_event_types(handed_off, token=handed_off.instructor_token)

    assert "CARD_FIELD_CHANGED" in operator_seen
    assert "CARD_FIELD_CHANGED" in instructor_seen, "the instructor sees every event type (§40.1)"
    assert "CARD_FIELD_CHANGED" not in dds_seen, "the DDS trainee never sees an operator-only type"


# ---------------------------------------------------------------------------------------------
# 3. Only the next-stage holder or the instructor may continue
# ---------------------------------------------------------------------------------------------


async def test_the_operator_trainee_may_not_continue_their_own_finished_stage(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    """The 112 trainee's stage is over; the next stage belongs to a different user entirely."""
    clock.advance_ms(11_000)  # MULTI_TRAINEE's pause is 10 s (§10.10)

    response = await in_transition.post("/stage/continue", token=in_transition.operator_token)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_dds_trainee_may_continue_once_the_pause_has_elapsed(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    clock.advance_ms(11_000)

    response = await in_transition.post("/stage/continue", token=in_transition.dds_token)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "ACTIVE"


async def test_the_instructor_may_also_continue(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    clock.advance_ms(11_000)

    response = await in_transition.post("/stage/continue", token=in_transition.instructor_token)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "ACTIVE"


# ---------------------------------------------------------------------------------------------
# 4. Two ДДС trainees bound to two services (I3 E5b, HLD 70 §70.4.5)
# ---------------------------------------------------------------------------------------------

SESSIONS = "/api/v1/sessions"
EXAMPLE_SLUG = "street-rubbish-fire"


@pytest.fixture
async def rubbish_version_id(
    unit_of_work: Any, demo_version_id: ScenarioVersionId
) -> ScenarioVersionId:
    """The committed schema-2 example (memo by default, `responders: DEFAULT`)."""
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(EXAMPLE_SLUG)
        assert stored is not None
        version = await uow.scenarios.find_version(stored.scenario_id, 1)
        assert version is not None
        await uow.commit()
    return version.scenario_version_id


def _bound(user_id: UserId, service: str | None) -> dict[str, Any]:
    member = participant(user_id, "DDS")
    member["assigned_service_id"] = service
    return member


async def _create(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    version_id: ScenarioVersionId,
    members: list[dict[str, Any]],
) -> httpx.Response:
    return await client.post(
        SESSIONS,
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(version_id),
            "session_mode": "MULTI_TRAINEE",
            "participants": members,
        },
    )


async def _legs(client: httpx.AsyncClient, token: str, session_id: str) -> dict[str, Any]:
    response = await client.get(f"{SESSIONS}/{session_id}/dds/legs", headers=auth(token))
    assert response.status_code == 200, response.text
    return {leg["service_type"]: leg for leg in response.json()}


async def _status(
    client: httpx.AsyncClient, token: str, session_id: str, leg: dict[str, Any], status: str
) -> httpx.Response:
    return await client.post(
        f"{SESSIONS}/{session_id}/dds/legs/{leg['assignment_id']}/status",
        headers=auth(token),
        json={"status": status},
    )


async def test_two_dds_trainees_bound_to_two_services_each_play_their_own_leg(
    client: httpx.AsyncClient,
    container: Container,
    clock: FakeClock,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
) -> None:
    created = await _create(
        client,
        tokens,
        rubbish_version_id,
        [_bound(users["trainee1"], "FIRE_RESCUE"), _bound(users["trainee2"], "TSODD")],
    )
    assert created.status_code == 201, created.text
    assert created.json()["state"] == "READY"
    session_id = created.json()["id"]
    dds_stage = next(stage for stage in created.json()["stages"] if stage["role_type"] == "DDS")
    assert dds_stage["participant_user_id"] == str(users["trainee1"]), "the primary: first bound"
    started = await client.post(
        f"{SESSIONS}/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text

    one, two = tokens["trainee1"], tokens["trainee2"]
    seen_by_one = await _legs(client, one, session_id)
    seen_by_two = await _legs(client, two, session_id)
    assert set(seen_by_one) == set(seen_by_two), "broadcast: both see every notified service"
    assert {s for s, leg in seen_by_one.items() if leg["is_mine"]} == {"FIRE_RESCUE"}
    assert {s for s, leg in seen_by_two.items() if leg["is_mine"]} == {"TSODD"}
    assert seen_by_one["FIRE_RESCUE"]["bound_user_id"] == str(users["trainee1"])
    assert seen_by_one["TSODD"]["bound_user_id"] == str(users["trainee2"])
    scripted = sorted(set(seen_by_one) - {"FIRE_RESCUE", "TSODD"})
    assert scripted, "the example notifies more services than the two bound ones"
    assert {seen_by_one[service]["responder"] for service in scripted} == {"SCRIPTED"}

    # Each trainee plays only their own leg.
    for token, other in ((one, seen_by_one["TSODD"]), (two, seen_by_one["FIRE_RESCUE"])):
        response = await _status(client, token, session_id, other, "ACCEPTED")
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "FORBIDDEN_FOR_SERVICE"

    # The non-primary ДДС trainee acts too (memo: any ДДС participant of the session).
    two_decides = await _status(client, two, session_id, seen_by_one["TSODD"], "ACCEPTED")
    assert two_decides.status_code == 200, two_decides.text
    for status in ("ACCEPTED", "RESPONSE_STARTED", "ARRIVED", "WORKING", "COMPLETED"):
        response = await _status(client, one, session_id, seen_by_one["FIRE_RESCUE"], status)
        assert response.status_code == 200, response.text
    for status in ("RESPONSE_STARTED", "ARRIVED", "WORKING", "COMPLETED"):
        response = await _status(client, two, session_id, seen_by_one["TSODD"], status)
        assert response.status_code == 200, response.text

    clock.advance_ms(600_000)
    await container.runner.tick_now(SessionId(UUID(session_id)))
    after = await _legs(client, one, session_id)
    assert {leg["response_status"] for leg in after.values()} == {"COMPLETED"}
    authors = {
        service: {
            entry["actor_user_id"] for entry in leg["history"] if entry["source"] == "TRAINEE"
        }
        for service, leg in after.items()
    }
    assert authors["FIRE_RESCUE"] == {str(users["trainee1"])}
    assert authors["TSODD"] == {str(users["trainee2"])}
    assert all(not authors[service] for service in scripted)

    closed = await client.post(
        f"{SESSIONS}/{session_id}/dds/close",
        headers=auth(two),
        json={"closure_reason": "RESOLVED"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "COMPLETED"

    report = await client.get(f"/api/v1/reports/{session_id}", headers=auth(tokens["instructor1"]))
    assert report.status_code == 200, report.text
    body = report.json()
    totals = {item["user_id"]: item for item in body["dds_participant_totals"]}
    assert set(totals) == {str(users["trainee1"]), str(users["trainee2"])}
    first, second = totals[str(users["trainee1"])], totals[str(users["trainee2"])]
    assert (first["assigned_service_id"], first["legs"]) == ("FIRE_RESCUE", 1)
    assert (first["status_entries"], first["accepted"], first["completed"]) == (5, 1, 1)
    assert (second["assigned_service_id"], second["legs"]) == ("TSODD", 1)
    assert (second["status_entries"], second["accepted"], second["completed"]) == (5, 1, 1)
    decisions = {item["service_type"]: item for item in body["dds_decisions"]}
    assert decisions["TSODD"]["bound_user_id"] == str(users["trainee2"])
    assert decisions["TSODD"]["responder"] == "TRAINEE"
    assert [entry["new_status"] for entry in decisions["TSODD"]["status_history"]] == [
        "RECEIVED",
        "ACCEPTED",
        "RESPONSE_STARTED",
        "ARRIVED",
        "WORKING",
        "COMPLETED",
    ]
    assert {decisions[service]["responder"] for service in scripted} == {"SCRIPTED"}


@pytest.mark.parametrize(
    ("services", "status", "code"),
    [
        (("FIRE_RESCUE", "FIRE_RESCUE"), 409, "INVALID_TRANSITION"),
        (("FIRE_RESCUE", None), 409, "INVALID_TRANSITION"),
        (("FIRE_RESCUE", "NO_SUCH_SERVICE"), 422, "SERVICE_UNKNOWN"),
    ],
    ids=["same-service", "one-unbound", "unknown-service"],
)
async def test_two_dds_trainees_need_two_distinct_known_services(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
    services: tuple[str | None, str | None],
    status: int,
    code: str,
) -> None:
    """`validate` requires distinct services (§70.4.5); an id outside the catalog is 422."""
    response = await _create(
        client,
        tokens,
        rubbish_version_id,
        [_bound(users["trainee1"], services[0]), _bound(users["trainee2"], services[1])],
    )
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


async def test_only_a_dds_participant_may_be_bound_to_a_service(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """The 112 operator of a two-stage session cannot hold a service binding."""
    operator = participant(users["trainee1"], "OPERATOR_112")
    operator["assigned_service_id"] = "FIRE_RESCUE"
    response = await client.post(
        SESSIONS,
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(demo_version_id),
            "session_mode": "MULTI_TRAINEE",
            "participants": [operator, participant(users["trainee2"], "DDS")],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "INVALID_TRANSITION"
