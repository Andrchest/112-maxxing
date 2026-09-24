"""The ДДС calls a service head — the AI voice by category (I3 E6c, HLD `80-telephony.md` §80.3.3,
§80.4, §80.6; D24).

The tests the E6c row of HLD 90 owes that need the database, on fakes (`FakeCallTransportStatus`,
`InMemoryVoiceSignals`, `StubVoiceTokenService`, a scripted `FakeLLM`, `NullCallerSpeechSink`;
no GPU, no network):

* `POST …/dds-calls {kind: SERVICE_HEAD, assignment_id}` resolves the persona by catalog category
  (`101` → `BRIGADE_101`, a code-less city service → `CITY_DEFAULT`), dials the service's number,
  records `persona_id` on `DDS_CALL_STARTED`, and `voice:join` carries it; the leg shows
  `live_call_id`;
* the head's first call asks the checklist and matches the trainee's statements by code
  (`DDS_CALL_ASSERTION`); a later call proposes exactly the due steps
  (`DDS_CALL_STATUS_PROPOSED`) — identical whether the runner ticked every 100 ms or every
  900 ms (INV 7) — and never a not-yet-due one (INV 2);
* proposal → the trainee's confirmation (`setDdsServiceStatus {proposed_by_call_id}`) → the leg's
  history; an unknown proposal is `422 PROPOSAL_UNKNOWN`;
* a `report: CALL_IN` step rings the ДДС (an INBOUND `DdsCall`, once), «Ответить» connects it, an
  unanswered one rings out (`NO_ANSWER`);
* (manager's addendum A) `closeDdsIncident` and `abortSession` end every live ДДС call
  (`DDS_CALL_ENDED {reason: ABORT}`) and publish `voice:cancel` so the voice agent drops it;
* `GET /reference/personas`.
"""

# The E6b suite's fixtures are imported and requested by name (pytest), which ruff reads as a
# redefinition: F811 is expected throughout this file.
# ruff: noqa: F811

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import yaml
from app.api.container import Container
from app.application.dds.stage_automation import inbound_call_id
from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
from app.application.dialogue.responder_context import ResponderContextLoader
from app.application.dialogue.service_head import ResponderTurnOutcome, ServiceHeadResponder
from app.application.dialogue.speech_sink import NullCallerSpeechSink
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.scenarios.import_scenario_version import ImportScenarioVersionCommand
from app.application.simulation.responder_scripts import ScenarioResponderScripts
from app.application.testing.fakes import FakeClock, InMemoryVoiceSignals
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.turn_pipeline import TurnContext
from app.domain.common.ids import AssignmentId, ScenarioVersionId, SessionId, UserId
from app.inference.llm.fake_llm import FakeLLM

from tests.api.conftest import auth
from tests.api.dds.test_dds_calls import (  # noqa: F401
    ANSWER_AFTER_MS,
    API,
    EXAMPLE_SLUG,
    container,
    dds,
    get_call,
    instructor_events,
    of_type,
    off_session,
    on_session,
    rubbish_version_id,
    start_claimant_call,
    started_session,
    tick,
    transport,
    voice_signals,
    voice_tokens,
)
from tests.unit.application.dialogue.conftest import transcribed_turn

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[4]
EXAMPLE = REPO / "scenarios" / "examples" / EXAMPLE_SLUG / "v1.yaml"


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


async def legs(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID
) -> dict[str, dict[str, Any]]:
    response = await client.get(f"{API}/{session_id}/dds/legs", headers=dds(tokens))
    assert response.status_code == 200, response.text
    return {leg["service_type"]: leg for leg in response.json()}


async def call_head(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID, assignment_id: str
) -> httpx.Response:
    return await client.post(
        f"{API}/{session_id}/dds-calls",
        headers=dds(tokens),
        json={"kind": "SERVICE_HEAD", "assignment_id": assignment_id},
    )


async def hang_up(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID, call_id: str
) -> None:
    response = await client.post(
        f"{API}/{session_id}/dds-calls/{call_id}/hang-up", headers=dds(tokens)
    )
    assert response.status_code == 200, response.text


def head_responder(
    container: Container, clock: FakeClock, script: list[Any]
) -> ServiceHeadResponder:
    """The voice agent's service-head chain over the real database, with a scripted fake model."""
    llm = FakeLLM(script)
    return ServiceHeadResponder(
        loader=ResponderContextLoader(
            container.unit_of_work,
            clock,
            ScenarioResponderScripts(container.unit_of_work),
            container.reference,
        ),
        interpreter=DialogueInterpreter(llm, NullMetricsRecorder(), config=InterpreterConfig()),
        sink=NullCallerSpeechSink(),
        uow_factory=container.unit_of_work,
        llm=llm,
    )


async def turn_context(
    container: Container, clock: FakeClock, session_id: UUID, call_id: str
) -> TurnContext:
    async with container.unit_of_work() as uow:
        session = await uow.sessions.get(SessionId(session_id))
        await uow.commit()
    assert session is not None
    return TurnContext(
        session_id=SessionId(session_id),
        call_id=UUID(call_id),
        config=VoiceTurnConfig(),
        transport=None,  # type: ignore[arg-type]  # the null sink never plays
        appender=VoiceEventAppender(
            session_id=SessionId(session_id),
            uow_factory=container.unit_of_work,
            clock=clock,
            started_at=session.started_at,
        ),
        recorder=None,
    )


def interpretation(speech_act: str = "QUESTION", requested: tuple[str, ...] = ()) -> str:
    return json.dumps(
        {
            "speech_act": speech_act,
            "requested_facts": [{"fact_id": slot, "explicit": True} for slot in requested],
            "operator_assertions": [],
            "confirmation_targets": [],
            "semantic_confidence": 0.9,
        }
    )


async def head_says(
    container: Container,
    clock: FakeClock,
    session_id: UUID,
    call_id: str,
    text: str,
    script: list[Any],
    *,
    turn_index: int = 0,
) -> ResponderTurnOutcome:
    head = head_responder(container, clock, script)
    context = await turn_context(container, clock, session_id, call_id)
    return await head.run_turn(transcribed_turn(text, turn_index=turn_index), context)


async def connected_head_call(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    container: Container,
    clock: FakeClock,
    session_id: UUID,
    service: str = "FIRE_RESCUE",
) -> str:
    leg = (await legs(client, tokens, session_id))[service]
    started = await call_head(client, tokens, session_id, leg["assignment_id"])
    assert started.status_code == 201, started.text
    call_id: str = started.json()["call"]["call_id"]
    clock.advance_ms(ANSWER_AFTER_MS)
    await tick(container, session_id)
    assert (await get_call(client, tokens, session_id, call_id))["state"] == "CONNECTED"
    return call_id


# ---------------------------------------------------------------------------------------------
# The call: persona by category, number, voice:join, live_call_id
# ---------------------------------------------------------------------------------------------


async def test_on_offers_the_service_head_and_off_does_not(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID, off_session: UUID
) -> None:
    for session_id, offered in ((on_session, True), (off_session, False)):
        snapshot = await client.get(f"{API}/{session_id}/snapshot", headers=dds(tokens))
        actions = {
            item["action_id"]: item["label_ru"] for item in snapshot.json()["available_actions"]
        }
        assert ("call_service_head" in actions) is offered
    off_leg = (await legs(client, tokens, off_session))["FIRE_RESCUE"]
    refused = await call_head(client, tokens, off_session, off_leg["assignment_id"])
    assert refused.status_code == 409 and refused.json()["code"] == "ACTION_NOT_AVAILABLE"


async def test_the_101_call_resolves_its_persona_by_code(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    on_session: UUID,
    container: Container,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    leg = (await legs(client, tokens, on_session))["FIRE_RESCUE"]
    assert leg["live_call_id"] is None
    started = await call_head(client, tokens, on_session, leg["assignment_id"])
    assert started.status_code == 201, started.text
    call = started.json()["call"]
    assert (call["kind"], call["direction"], call["state"]) == (
        "SERVICE_HEAD",
        "OUTBOUND",
        "RINGING",
    )
    assert (call["persona_id"], call["persona_title_ru"], call["dialed"]) == (
        "BRIGADE_101",
        "Начальник караула ПСЧ",
        "101",
    )
    assert call["assignment_id"] == leg["assignment_id"]
    assert call["service_type"] == "FIRE_RESCUE"
    assert voice_signals.join_extras[-1] == {
        "call_kind": "SERVICE_HEAD",
        "assignment_id": leg["assignment_id"],
        "persona_id": "BRIGADE_101",
        "endpoint": "BROWSER",
        "direction": "OUTBOUND",
    }
    [started_event] = await of_type(client, tokens, on_session, "DDS_CALL_STARTED")
    assert started_event["payload"]["persona_id"] == "BRIGADE_101"
    assert started_event["payload"]["actor_user_id"] == str(users["trainee2"])
    # The leg shows its live call (addendum C), and the list gives the persona's title.
    assert (await legs(client, tokens, on_session))["FIRE_RESCUE"]["live_call_id"] == call[
        "call_id"
    ]
    listed = await client.get(f"{API}/{on_session}/dds-calls", headers=dds(tokens))
    assert listed.json()[0]["persona_title_ru"] == "Начальник караула ПСЧ"


async def test_a_code_less_city_service_gets_the_city_persona(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID
) -> None:
    leg = (await legs(client, tokens, on_session))["TSODD"]
    started = await call_head(client, tokens, on_session, leg["assignment_id"])
    assert started.status_code == 201, started.text
    call = started.json()["call"]
    assert call["persona_id"] == "CITY_DEFAULT"
    assert call["dialed"].startswith("7") and len(call["dialed"]) == 4  # §80.3.5's `7xxx`


async def test_a_service_head_call_needs_a_leg_of_this_card(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID
) -> None:
    missing = await client.post(
        f"{API}/{on_session}/dds-calls", headers=dds(tokens), json={"kind": "SERVICE_HEAD"}
    )
    assert missing.status_code == 422 and missing.json()["code"] == "VALIDATION_ERROR"
    unknown = await call_head(client, tokens, on_session, str(uuid.uuid4()))
    assert unknown.status_code == 404


# ---------------------------------------------------------------------------------------------
# The head's words: the first call, a later call (INV 2), INV 7
# ---------------------------------------------------------------------------------------------


async def test_the_first_call_asks_the_checklist_and_matches_statements_by_code(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
) -> None:
    call_id = await connected_head_call(client, tokens, container, clock, on_session)
    first = await head_says(
        container, clock, on_session, call_id, "Алло, пожарная?", [interpretation("GREETING")]
    )
    assert first.text.startswith("Начальник караула, слушаю. Диктуйте: адрес")
    assert first.knowledge.first_call is True

    street = next(
        item for item in first.knowledge.checklist if item.field_path.startswith("address.street")
    )
    await head_says(
        container,
        clock,
        on_session,
        call_id,
        f"Горит мусор, улица {street.value}",
        [interpretation("STATEMENT")],
        turn_index=1,
    )
    assertions = await of_type(client, tokens, on_session, "DDS_CALL_ASSERTION")
    matched = {item["payload"]["field_path"]: item["payload"] for item in assertions}
    assert matched[street.field_path]["matches_snapshot"] is True
    assert matched[street.field_path]["call_id"] == call_id
    assert all(item["actor_type"] == "MODEL" for item in assertions)
    # DDS_CALL_ASSERTION is the instructor's (§80.6.1): the ДДС trainee's reader never sees it.
    trainee_view = await client.get(
        f"{API}/{on_session}/events",
        headers=dds(tokens),
        params={"limit": 1000, "event_type": "DDS_CALL_ASSERTION"},
    )
    assert trainee_view.json()["items"] == []


async def test_a_later_call_proposes_exactly_the_due_steps_and_never_a_pending_one(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
) -> None:
    first_call = await connected_head_call(client, tokens, container, clock, on_session)
    await head_says(container, clock, on_session, first_call, "Алло?", [interpretation("GREETING")])
    await hang_up(client, tokens, on_session, first_call)

    clock.advance_ms(
        70_000
    )  # DEFAULT: ACCEPTED +15 s, RESPONSE_STARTED +60 s due; ARRIVED +180 s not
    await tick(container, on_session)
    later = await connected_head_call(client, tokens, container, clock, on_session)
    outcome = await head_says(
        container, clock, on_session, later, "Что у вас?", [interpretation(requested=("status",))]
    )
    assert outcome.knowledge.first_call is False
    assert outcome.text == ("Начальник караула, слушаю. Докладываю. Вызов приняли. Выехали.")
    proposals = [
        item["payload"]
        for item in await of_type(client, tokens, on_session, "DDS_CALL_STATUS_PROPOSED")
    ]
    [leg] = [
        item
        for item in (await legs(client, tokens, on_session)).values()
        if item["service_type"] == "FIRE_RESCUE"
    ]
    received = int(outcome.knowledge.received_at_offset_ms)
    assert [
        (item["status"], item["script_after_ms"], item["due_offset_ms"]) for item in proposals
    ] == [
        ("ACCEPTED", 15_000, received + 15_000),
        ("RESPONSE_STARTED", 60_000, received + 60_000),
    ]
    assert all(
        item["call_id"] == later and item["assignment_id"] == leg["assignment_id"]
        for item in proposals
    )
    # INV 2: the pending step is never spoken and never proposed.
    assert "Прибыли" not in outcome.text
    assert "ARRIVED" not in {item["status"] for item in proposals}
    # Under ON the trainee's own leg is heard, not applied (§80.3.3): the leg did not move.
    assert leg["response_status"] == "ADDED"


async def _proposals_after(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    version_id: ScenarioVersionId,
    container: Container,
    clock: FakeClock,
    step_ms: int,
    total_ms: int,
) -> list[tuple[str, int, int]]:
    session_id = await started_session(
        client, tokens, users, version_id, {"dds_brigade_call": "ON"}
    )
    call_id = await connected_head_call(client, tokens, container, clock, session_id)
    for _ in range(total_ms // step_ms):
        clock.advance_ms(step_ms)
        await tick(container, session_id)
    await head_says(
        container,
        clock,
        session_id,
        call_id,
        "Доложите обстановку",
        [interpretation(requested=("status",))],
    )
    events = await of_type(client, tokens, session_id, "DDS_CALL_STATUS_PROPOSED")
    await client.post(
        f"{API}/{session_id}/abort", headers=auth(tokens["instructor1"]), json={"reason": "test"}
    )
    return [
        (
            item["payload"]["status"],
            item["payload"]["script_after_ms"],
            item["payload"]["due_offset_ms"],
        )
        for item in events
    ]


async def test_proposals_are_the_same_at_any_tick_rate(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
    container: Container,
    clock: FakeClock,
) -> None:
    """INV 7: the head reads due offsets, never the tick's — 100 ms ticks and 900 ms ticks over the
    same 16.2 s propose the same steps with the same due offsets."""
    fast = await _proposals_after(
        client, tokens, users, rubbish_version_id, container, clock, 100, 16_200
    )
    slow = await _proposals_after(
        client, tokens, users, rubbish_version_id, container, clock, 900, 16_200
    )
    assert fast == slow
    assert [status for status, _after, _due in fast] == ["ACCEPTED"]


# ---------------------------------------------------------------------------------------------
# Proposal → the trainee's confirmation → the leg's history
# ---------------------------------------------------------------------------------------------


async def test_the_trainee_confirms_a_heard_status_and_it_reaches_the_history(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
) -> None:
    clock.advance_ms(20_000)
    await tick(container, on_session)
    call_id = await connected_head_call(client, tokens, container, clock, on_session)
    await head_says(
        container, clock, on_session, call_id, "Что у вас?", [interpretation(requested=("status",))]
    )
    leg = (await legs(client, tokens, on_session))["FIRE_RESCUE"]
    other = (await legs(client, tokens, on_session))["TSODD"]
    status_url = f"{API}/{on_session}/dds/legs/{leg['assignment_id']}/status"

    unknown = await client.post(
        status_url,
        headers=dds(tokens),
        json={"status": "ACCEPTED", "proposed_by_call_id": str(uuid.uuid4())},
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "PROPOSAL_UNKNOWN"
    # A proposal of another leg is unknown for this one.
    foreign = await client.post(
        f"{API}/{on_session}/dds/legs/{other['assignment_id']}/status",
        headers=dds(tokens),
        json={"status": "ACCEPTED", "proposed_by_call_id": call_id},
    )
    assert foreign.status_code == 422 and foreign.json()["code"] == "PROPOSAL_UNKNOWN"

    confirmed = await client.post(
        status_url,
        headers=dds(tokens),
        json={"status": "ACCEPTED", "proposed_by_call_id": call_id},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["response_status"] == "ACCEPTED"
    assert [entry["new_status"] for entry in confirmed.json()["history"]][-1] == "ACCEPTED"
    status_set = [
        item["payload"]
        for item in await of_type(client, tokens, on_session, "DDS_SERVICE_STATUS_SET")
        if item["payload"]["new_status"] == "ACCEPTED"
    ]
    assert status_set[-1]["proposed_by_call_id"] == call_id
    assert status_set[-1]["source"] == "TRAINEE"


# ---------------------------------------------------------------------------------------------
# A `report: CALL_IN` step rings the ДДС
# ---------------------------------------------------------------------------------------------


@pytest.fixture
async def call_in_version_id(container: Container) -> ScenarioVersionId:
    """The example with FIRE_RESCUE's script in the object form: persona BRIGADE_101 and an
    `ACCEPTED` step the brigade calls in (+15 s) — a scenario of its own, imported once."""
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    document["id"] = "7c1f8f55-0f5e-4d73-9c35-3a1f7d0e6b01"
    document["scenario_id"] = "7c1f8f55-0f5e-4d73-9c35-3a1f7d0e6b02"
    document["title"] = "Горит мусор на улице — бригада звонит сама"
    document["variants"]["default"]["dds_brigade_call"] = "ON"
    document["expected_response"]["responders"] = {
        "FIRE_RESCUE": {
            "persona": "BRIGADE_101",
            "steps": [
                {"after_ms": 0, "status": "RECEIVED"},
                {"after_ms": 15_000, "status": "ACCEPTED", "report": "CALL_IN"},
                {"after_ms": 60_000, "status": "RESPONSE_STARTED", "order_number": "2415"},
                {"after_ms": 180_000, "status": "ARRIVED"},
                {"after_ms": 200_000, "status": "WORKING"},
                {"after_ms": 600_000, "status": "COMPLETED"},
            ],
        }
    }
    async with container.unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug("call-in-example")
        version = (
            None if stored is None else await uow.scenarios.find_version(stored.scenario_id, 1)
        )
        await uow.commit()
    if version is not None:
        return version.scenario_version_id
    detail = await container.import_scenario_version()(
        ImportScenarioVersionCommand(
            format="yaml",
            content=yaml.safe_dump(document, allow_unicode=True),
            source_path="scenarios/examples/call-in-example/v1.yaml",
        )
    )
    return ScenarioVersionId(detail.scenario_version_id)


async def test_a_call_in_step_rings_the_dds_once_and_answer_connects_it(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    call_in_version_id: ScenarioVersionId,
    container: Container,
    clock: FakeClock,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    session_id = await started_session(client, tokens, users, call_in_version_id)
    await tick(container, session_id)
    assert await of_type(client, tokens, session_id, "DDS_CALL_STARTED") == []

    clock.advance_ms(15_500)
    await tick(container, session_id)
    await tick(container, session_id)  # idempotent: the step rings once
    [started] = await of_type(client, tokens, session_id, "DDS_CALL_STARTED")
    payload = started["payload"]
    leg = (await legs(client, tokens, session_id))["FIRE_RESCUE"]
    assert (payload["direction"], payload["selection_reason"], started["actor_type"]) == (
        "INBOUND",
        "INBOUND_SCRIPT",
        "SIMULATION",
    )
    assert payload["persona_id"] == "BRIGADE_101"
    assert payload["actor_user_id"] == str(users["trainee2"])
    assert payload["call_id"] == str(inbound_call_id(SessionId(session_id), _leg_stub(leg), 1))
    call_id = payload["call_id"]
    ringing = await get_call(client, tokens, session_id, call_id)
    assert ringing["state"] == "RINGING"
    assert [item["action_id"] for item in ringing["available_actions"]] == ["answer", "hang_up"]
    assert voice_signals.join_extras[-1]["direction"] == "INBOUND"

    answered = await client.post(
        f"{API}/{session_id}/dds-calls/{call_id}/answer", headers=dds(tokens)
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["call"]["state"] == "CONNECTED"
    assert answered.json()["call"]["answered_by"] == "TRAINEE"
    assert answered.json()["voice"]["room_name"] == ringing["room_name"]
    again = await client.post(f"{API}/{session_id}/dds-calls/{call_id}/answer", headers=dds(tokens))
    assert again.status_code == 409 and again.json()["code"] == "INVALID_TRANSITION"

    outcome = await head_says(
        container, clock, session_id, call_id, "ДДС, слушаю", [interpretation("GREETING")]
    )
    assert "Докладываю. Вызов приняли." in outcome.text
    await hang_up(client, tokens, session_id, call_id)
    await tick(container, session_id)
    assert len(await of_type(client, tokens, session_id, "DDS_CALL_STARTED")) == 1


def _leg_stub(leg: dict[str, Any]) -> Any:
    class Leg:
        assignment_id = AssignmentId(UUID(leg["assignment_id"]))

    return Leg()


async def test_an_outbound_call_cannot_be_answered_by_the_trainee(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID
) -> None:
    started = await start_claimant_call(client, tokens, on_session)
    call_id = started.json()["call"]["call_id"]
    refused = await client.post(
        f"{API}/{on_session}/dds-calls/{call_id}/answer", headers=dds(tokens)
    )
    assert refused.status_code == 409 and refused.json()["code"] == "INVALID_TRANSITION"


async def test_an_unanswered_call_in_rings_out(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    call_in_version_id: ScenarioVersionId,
    container: Container,
    clock: FakeClock,
) -> None:
    session_id = await started_session(client, tokens, users, call_in_version_id)
    clock.advance_ms(15_500)
    await tick(container, session_id)
    await tick(container, session_id)
    clock.advance_ms(31_000)
    await tick(container, session_id)
    [ended] = await of_type(client, tokens, session_id, "DDS_CALL_ENDED")
    assert ended["payload"]["reason"] == "NO_ANSWER"


# ---------------------------------------------------------------------------------------------
# Addendum A: closing the incident and aborting the session end every live call
# ---------------------------------------------------------------------------------------------


async def test_close_incident_ends_every_live_dds_call(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    started = await start_claimant_call(client, tokens, on_session)
    call_id = started.json()["call"]["call_id"]
    for leg in (await legs(client, tokens, on_session)).values():
        declined = await client.post(
            f"{API}/{on_session}/dds/legs/{leg['assignment_id']}/status",
            headers=dds(tokens),
            json={"status": "NOT_ACCEPTED", "comment_ru": "Не наша компетенция"},
        )
        assert declined.status_code == 200, declined.text
    closed = await client.post(
        f"{API}/{on_session}/dds/close", headers=dds(tokens), json={"closure_reason": "RESOLVED"}
    )
    assert closed.status_code == 200, closed.text

    [ended] = await of_type(client, tokens, on_session, "DDS_CALL_ENDED")
    assert (ended["payload"]["call_id"], ended["payload"]["reason"], ended["actor_type"]) == (
        call_id,
        "ABORT",
        "SYSTEM",
    )
    types = [item["event_type"] for item in await instructor_events(client, tokens, on_session)]
    assert types.index("DDS_CALL_ENDED") < types.index("DDS_INCIDENT_CLOSED")
    assert voice_signals.cancels[-1][1:3] == (UUID(call_id), "ABORT")
    listed = await client.get(f"{API}/{on_session}/dds-calls", headers=dds(tokens))
    assert listed.json()[0]["state"] == "ENDED"


async def test_abort_session_ends_every_live_dds_call(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    started = await start_claimant_call(client, tokens, on_session)
    call_id = started.json()["call"]["call_id"]
    aborted = await client.post(
        f"{API}/{on_session}/abort",
        headers=auth(tokens["instructor1"]),
        json={"reason": "учебная остановка"},
    )
    assert aborted.status_code == 200, aborted.text
    [ended] = await of_type(client, tokens, on_session, "DDS_CALL_ENDED")
    assert (ended["payload"]["call_id"], ended["payload"]["reason"]) == (call_id, "ABORT")
    types = [item["event_type"] for item in await instructor_events(client, tokens, on_session)]
    assert types.index("DDS_CALL_ENDED") < types.index("SESSION_ABORTED")
    assert voice_signals.cancels[-1][1:3] == (UUID(call_id), "ABORT")


async def test_a_session_without_a_live_call_publishes_no_dds_cancel(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    off_session: UUID,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    aborted = await client.post(
        f"{API}/{off_session}/abort", headers=auth(tokens["instructor1"]), json={"reason": "стоп"}
    )
    assert aborted.status_code == 200, aborted.text
    assert voice_signals.cancels == []
    assert await of_type(client, tokens, off_session, "DDS_CALL_ENDED") == []


# ---------------------------------------------------------------------------------------------
# GET /reference/personas
# ---------------------------------------------------------------------------------------------


async def test_the_personas_of_a_pack_are_served_in_file_order(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/reference/personas", headers=dds(tokens), params={"pack": "v046_24-r1"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["persona_id"] for item in body][:4] == [
        "BRIGADE_101",
        "BRIGADE_102",
        "BRIGADE_103",
        "BRIGADE_104",
    ]
    assert body[0] == {
        "persona_id": "BRIGADE_101",
        "applies": {"code": "101", "kind": None},
        "title_ru": "Начальник караула ПСЧ",
        "gender": "MALE",
        "voice_id": "ru_male_adult_01",
    }
    legacy = await client.get(
        "/api/v1/reference/personas", headers=dds(tokens), params={"pack": "legacy-r1"}
    )
    assert legacy.status_code == 200 and legacy.json() == []
    unknown = await client.get(
        "/api/v1/reference/personas", headers=dds(tokens), params={"pack": "no-such-pack"}
    )
    assert unknown.status_code == 404
