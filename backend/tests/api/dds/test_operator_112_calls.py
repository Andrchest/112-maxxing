"""The ДДС calls 112 — answered by the AI 112 operator (I3 E6d, HLD `80-telephony.md` §80.3.4,
§80.10 owner Q1's default; REQ-5332; D23).

The tests the E6d row of HLD 90 owes that need the database, on fakes (`FakeCallTransportStatus`,
`InMemoryVoiceSignals`, `StubVoiceTokenService`, a scripted `FakeLLM`, `NullCallerSpeechSink`;
no GPU, no network):

* under `ON` the stage offers «Позвонить в 112» (`call_112`); `startDdsCall {kind: OPERATOR_112}`
  dials `112`, resolves the `OPERATOR_112` persona, records it on `DDS_CALL_STARTED` and on
  `voice:join`; `OFF` offers nothing and refuses the call;
* the AI answers — `answered_by: AI` on every I3 call (the 112 one, a claimant's, a service head's);
  the trainee cannot answer an OUTBOUND call (the `TRAINEE` hook is contract-only, E6g);
* over the real database, the operator's chain turns every REQ-5332 item the ДДС covers into a
  `DDS_CALL_ASSERTION` with its checklist `field_path`, matched against the session's snapshot, and
  asks for what was omitted;
* INV 3 — the operator's knowledge is the session's snapshot and nothing else: the loader never
  asks the script probe for it;
* the 112 trainee's screen and score never see the ДДС → 112 call (E6b's isolation rule).
"""

# The E6b suite's fixtures are imported and requested by name (pytest), which ruff reads as a
# redefinition: F811 is expected throughout this file.
# ruff: noqa: F811

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.api.container import Container
from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
from app.application.dialogue.responder_context import ResponderContextLoader
from app.application.dialogue.responder_templates import (
    CARD_REFERENCE_PATH,
    INCIDENT_CHANGE_PATH,
    LINE_112_ALL_STATED_RU,
    OPERATOR_112_CHECKLIST,
    SELF_IDENTIFICATION_PATH,
)
from app.application.dialogue.service_head import ResponderTurnOutcome, ServiceHeadResponder
from app.application.dialogue.speech_sink import NullCallerSpeechSink
from app.application.operator.views import project_call_state
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeClock, InMemoryVoiceSignals
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.dds.call import (
    CallEndpoint,
    CallSelectionReason,
    DdsCallDirection,
    DdsCallKind,
    start_call,
)
from app.domain.enums import ActorType
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.engine import score
from app.inference.llm.fake_llm import FakeLLM

from tests.api.dds.conftest import OperatorFlow
from tests.api.dds.test_dds_calls import (  # noqa: F401
    ANSWER_AFTER_MS,
    API,
    EXAMPLE_SLUG,
    _stored,
    agent_event,
    append,
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
    tts_started,
    voice_signals,
    voice_tokens,
)
from tests.api.dds.test_service_head_calls import (
    call_head,
    hang_up,
    legs,
    turn_context,
)
from tests.fixtures.scenarios import demo_document
from tests.unit.application.dialogue.conftest import transcribed_turn

pytestmark = pytest.mark.integration

PROMPTS = dict(OPERATOR_112_CHECKLIST)


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


async def call_112(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID
) -> httpx.Response:
    return await client.post(
        f"{API}/{session_id}/dds-calls", headers=dds(tokens), json={"kind": "OPERATOR_112"}
    )


async def connected_112_call(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    container: Container,
    clock: FakeClock,
    session_id: UUID,
) -> str:
    started = await call_112(client, tokens, session_id)
    assert started.status_code == 201, started.text
    call_id: str = started.json()["call"]["call_id"]
    clock.advance_ms(ANSWER_AFTER_MS)
    await tick(container, session_id)
    assert (await get_call(client, tokens, session_id, call_id))["state"] == "CONNECTED"
    return call_id


def statement() -> str:
    return json.dumps(
        {
            "speech_act": "STATEMENT",
            "requested_facts": [],
            "operator_assertions": [],
            "confirmation_targets": [],
            "semantic_confidence": 0.9,
        }
    )


class NoScripts:
    """A script probe that must never be asked: the 112 operator knows no script (INV 3)."""

    def __init__(self) -> None:
        self.asked = 0

    async def __call__(self, session_id: SessionId) -> Any:
        self.asked += 1
        raise AssertionError("the 112 operator's loader asked for the script")


def operator_chain(
    container: Container, clock: FakeClock, turns: int, scripts: NoScripts
) -> ServiceHeadResponder:
    """The voice agent's responder chain for a call to 112, over the real database."""
    llm = FakeLLM([statement() for _ in range(turns)])
    return ServiceHeadResponder(
        loader=ResponderContextLoader(container.unit_of_work, clock, scripts, container.reference),
        interpreter=DialogueInterpreter(llm, NullMetricsRecorder(), config=InterpreterConfig()),
        sink=NullCallerSpeechSink(),
        uow_factory=container.unit_of_work,
        llm=llm,
    )


async def operator_hears(
    container: Container,
    clock: FakeClock,
    session_id: UUID,
    call_id: str,
    lines: list[str],
) -> list[ResponderTurnOutcome]:
    scripts = NoScripts()
    chain = operator_chain(container, clock, len(lines), scripts)
    context = await turn_context(container, clock, session_id, call_id)
    outcomes = []
    for index, line in enumerate(lines):
        outcomes.append(await chain.run_turn(transcribed_turn(line, turn_index=index), context))
    assert scripts.asked == 0
    return outcomes


# ---------------------------------------------------------------------------------------------
# The call: offered under ON only, dials 112, the operator persona
# ---------------------------------------------------------------------------------------------


async def test_on_offers_the_call_to_112_and_off_does_not(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID, off_session: UUID
) -> None:
    for session_id, offered in ((on_session, True), (off_session, False)):
        snapshot = await client.get(f"{API}/{session_id}/snapshot", headers=dds(tokens))
        actions = {
            item["action_id"]: item["label_ru"] for item in snapshot.json()["available_actions"]
        }
        assert ("call_112" in actions) is offered
        if offered:
            assert actions["call_112"] == "Позвонить в 112"
    refused = await call_112(client, tokens, off_session)
    assert refused.status_code == 409 and refused.json()["code"] == "ACTION_NOT_AVAILABLE"
    assert await of_type(client, tokens, off_session, "DDS_CALL_STARTED") == []


async def test_the_call_dials_112_and_the_operator_persona_answers(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    started = await call_112(client, tokens, on_session)
    assert started.status_code == 201, started.text
    call = started.json()["call"]
    assert (call["kind"], call["direction"], call["state"], call["dialed"]) == (
        "OPERATOR_112",
        "OUTBOUND",
        "RINGING",
        "112",
    )
    assert (call["persona_id"], call["persona_title_ru"]) == ("OPERATOR_112", "Оператор 112")
    assert call["assignment_id"] is None and call["service_type"] is None
    assert started.json()["voice"] is not None  # the browser endpoint's room token
    assert voice_signals.join_extras[-1] == {
        "call_kind": "OPERATOR_112",
        "assignment_id": None,
        "persona_id": "OPERATOR_112",
        "endpoint": "BROWSER",
        "direction": "OUTBOUND",
    }
    [started_event] = await of_type(client, tokens, on_session, "DDS_CALL_STARTED")
    assert started_event["payload"]["persona_id"] == "OPERATOR_112"
    assert started_event["payload"]["dialed"] == "112"

    clock.advance_ms(ANSWER_AFTER_MS)
    await tick(container, on_session)
    [answered] = await of_type(client, tokens, on_session, "DDS_CALL_ANSWERED")
    assert answered["payload"]["answered_by"] == "AI"
    assert answered["actor_type"] == "SIMULATION"
    connected = await get_call(client, tokens, on_session, call["call_id"])
    assert (connected["state"], connected["answered_by"]) == ("CONNECTED", "AI")


async def test_a_call_to_112_takes_no_leg(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID
) -> None:
    leg = (await legs(client, tokens, on_session))["FIRE_RESCUE"]
    refused = await client.post(
        f"{API}/{on_session}/dds-calls",
        headers=dds(tokens),
        json={"kind": "OPERATOR_112", "assignment_id": leg["assignment_id"]},
    )
    assert refused.status_code == 422 and refused.json()["code"] == "VALIDATION_ERROR"


async def test_answered_by_is_ai_on_every_i3_call_and_the_trainee_cannot_answer_it(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
) -> None:
    """Owner Q1's default: the AI answers every OUTBOUND call — the 112 one included. The
    `answered_by: TRAINEE` hook of an `OPERATOR_112` call (E6g) has no behaviour in I3."""
    fire = (await legs(client, tokens, on_session))["FIRE_RESCUE"]
    for start in (
        lambda: call_112(client, tokens, on_session),
        lambda: start_claimant_call(client, tokens, on_session),
        lambda: call_head(client, tokens, on_session, fire["assignment_id"]),
    ):
        started = await start()
        assert started.status_code == 201, started.text
        call_id = started.json()["call"]["call_id"]
        own_answer = await client.post(
            f"{API}/{on_session}/dds-calls/{call_id}/answer", headers=dds(tokens)
        )
        assert own_answer.status_code == 409, own_answer.text
        clock.advance_ms(ANSWER_AFTER_MS)
        await tick(container, on_session)
        await hang_up(client, tokens, on_session, call_id)
    answered = await of_type(client, tokens, on_session, "DDS_CALL_ANSWERED")
    kinds = [
        item["payload"]["kind"]
        for item in await of_type(client, tokens, on_session, "DDS_CALL_STARTED")
    ]
    assert kinds == ["OPERATOR_112", "CLAIMANT", "SERVICE_HEAD"]
    assert [item["payload"]["answered_by"] for item in answered] == ["AI", "AI", "AI"]
    listed = await client.get(f"{API}/{on_session}/dds-calls", headers=dds(tokens))
    assert {item["answered_by"] for item in listed.json()} == {"AI"}


# ---------------------------------------------------------------------------------------------
# The operator's words: REQ-5332's checklist → DDS_CALL_ASSERTION
# ---------------------------------------------------------------------------------------------


async def test_every_checklist_item_becomes_an_assertion_matched_against_the_snapshot(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
) -> None:
    call_id = await connected_112_call(client, tokens, container, clock, on_session)
    outcomes = await operator_hears(
        container,
        clock,
        on_session,
        call_id,
        [
            "Алло, 112?",
            "Дежурный пожарно-спасательной службы Иванов",
            "Адрес: улица Щукинская, дом 2",
            "Работаем по вашей карточке номер 36814851",
            "Обстановка изменилась, огонь перекинулся на гаражи, нужна полиция",
        ],
    )
    assert [outcome.text for outcome in outcomes] == [
        f"Служба 112, оператор слушает. {PROMPTS[SELF_IDENTIFICATION_PATH]}",
        PROMPTS["address.*"],
        PROMPTS[CARD_REFERENCE_PATH],
        PROMPTS[INCIDENT_CHANGE_PATH],
        LINE_112_ALL_STATED_RU,
    ]
    knowledge = outcomes[0].knowledge
    assert knowledge.kind is DdsCallKind.OPERATOR_112
    assert {entry.id for entry in knowledge.recipients} >= {"FIRE_RESCUE"}

    assertions = await of_type(client, tokens, on_session, "DDS_CALL_ASSERTION")
    by_path = {item["payload"]["field_path"]: item["payload"] for item in assertions}
    assert by_path[SELF_IDENTIFICATION_PATH]["matches_snapshot"] is True
    assert by_path["address.street"]["matches_snapshot"] is True
    assert by_path["address.house"]["matches_snapshot"] is True
    assert by_path[CARD_REFERENCE_PATH]["value_ru"] == "36814851"
    assert by_path[INCIDENT_CHANGE_PATH]["matches_snapshot"] is False
    assert {item["payload"]["call_id"] for item in assertions} == {call_id}
    assert all(item["actor_type"] == "MODEL" for item in assertions)
    # The operator proposes nothing: it reports no status.
    assert await of_type(client, tokens, on_session, "DDS_CALL_STATUS_PROPOSED") == []
    # DDS_CALL_ASSERTION is the instructor's (§80.6.1): the ДДС trainee's reader never sees it.
    trainee_view = await client.get(
        f"{API}/{on_session}/events",
        headers=dds(tokens),
        params={"limit": 1000, "event_type": "DDS_CALL_ASSERTION"},
    )
    assert trainee_view.json()["items"] == []


async def test_the_operator_asks_for_the_self_identification_the_dds_omitted(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
) -> None:
    call_id = await connected_112_call(client, tokens, container, clock, on_session)
    outcomes = await operator_hears(
        container,
        clock,
        on_session,
        call_id,
        [
            "Улица Щукинская, дом 2, работаем по карточке, обстановка изменилась",
            "Нужна полиция",
        ],
    )
    ask = PROMPTS[SELF_IDENTIFICATION_PATH]
    assert [outcome.text for outcome in outcomes] == [
        f"Служба 112, оператор слушает. {ask}",
        ask,
    ]
    paths = {
        item["payload"]["field_path"]
        for item in await of_type(client, tokens, on_session, "DDS_CALL_ASSERTION")
    }
    assert SELF_IDENTIFICATION_PATH not in paths
    assert {CARD_REFERENCE_PATH, INCIDENT_CHANGE_PATH, "address.street"} <= paths


# ---------------------------------------------------------------------------------------------
# INV 3: the operator's knowledge is the session's snapshot and nothing else
# ---------------------------------------------------------------------------------------------


async def test_the_operator_knows_the_snapshot_and_nothing_else(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
) -> None:
    call_id = await connected_112_call(client, tokens, container, clock, on_session)
    scripts = NoScripts()
    loader = ResponderContextLoader(container.unit_of_work, clock, scripts, container.reference)
    knowledge = await loader.load(SessionId(on_session), UUID(call_id))
    assert scripts.asked == 0
    async with container.unit_of_work() as uow:
        session = await uow.sessions.get(SessionId(on_session))
        assert session is not None
        stage = next(s for s in session.stages if s.role_type.value == "DDS")
        [first, *_] = await uow.dds_assignments.list_for_stage(stage.role_stage_id)
        snapshot = await uow.handoffs.get(first.snapshot_id)
        await uow.commit()
    assert snapshot is not None
    assert dict(knowledge.snapshot_values) == dict(snapshot.card_values)
    assert tuple(entry.id for entry in knowledge.recipients) == tuple(
        str(service) for service in snapshot.recipient_services
    )
    assert all(item.field_path.startswith("address.") for item in knowledge.checklist)
    assert knowledge.checklist, "the example's snapshot has an address"
    assert (knowledge.steps_due, knowledge.steps_pending_count) == ((), 0)
    assert (knowledge.assignment_id, knowledge.service_type, knowledge.leg_status_now) == (
        None,
        None,
        None,
    )
    assert knowledge.persona is not None and knowledge.persona.id == "OPERATOR_112"


# ---------------------------------------------------------------------------------------------
# The 112 trainee never sees the ДДС → 112 call (E6b's isolation rule)
# ---------------------------------------------------------------------------------------------


async def test_the_112_trainee_never_sees_the_dds_call_to_112(dds_active: OperatorFlow) -> None:
    """The ДДС → 112 call is the ДДС's (and the instructor's): none of its events — the call's
    own, its assertions, its turns — reaches the OPERATOR_112 reader, and the operator's phone
    widget stays on the 112 call."""
    flow = dds_active
    session_id = UUID(str(flow.session_id))
    call_id = str(uuid.uuid4())
    _, started = start_call(
        call_id=UUID(call_id),
        session_id=SessionId(session_id),
        kind=DdsCallKind.OPERATOR_112,
        direction=DdsCallDirection.OUTBOUND,
        dialed="112",
        endpoint=CallEndpoint.BROWSER,
        actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=flow.dds_user_id),
        now_ms=400,
        selection_reason=CallSelectionReason.BROWSER_BUTTON,
        persona_id="OPERATOR_112",
    )
    assertion = agent_event(
        EventType.DDS_CALL_ASSERTION,
        {
            "call_id": call_id,
            "turn_id": str(uuid.uuid4()),
            "field_path": SELF_IDENTIFICATION_PATH,
            "value_ru": "Дежурный пожарной охраны Иванов",
            "matches_snapshot": True,
            "at_offset_ms": 450,
        },
    ).model_copy(update={"actor": ActorRef(actor_type=ActorType.MODEL)})
    await append(flow.container, session_id, [started, tts_started(call_id), assertion])

    operator = await flow.get("/events", token=flow.operator_token, params={"limit": 1000})
    assert operator.status_code == 200, operator.text
    seen = operator.json()["items"]
    assert not [item for item in seen if item["payload"].get("call_id") == call_id]
    assert not {"DDS_CALL_STARTED", "DDS_CALL_ASSERTION"} & {item["event_type"] for item in seen}
    ddsview = await flow.get("/events", token=flow.dds_token, params={"limit": 1000})
    dds_types = [
        item["event_type"]
        for item in ddsview.json()["items"]
        if item["payload"].get("call_id") == call_id
    ]
    assert "DDS_CALL_STARTED" in dds_types and "CALLER_TTS_STARTED" in dds_types
    assert "DDS_CALL_ASSERTION" not in dds_types  # the instructor's only
    async with flow.container.unit_of_work() as uow:
        log = await uow.events.read(SessionId(session_id))
        await uow.commit()
    with_call = project_call_state(log)
    without_call = project_call_state(
        [event for event in log if str(event.payload.get("call_id", "")) != call_id]
    )
    assert with_call == without_call


def test_a_dds_call_to_112_moves_no_112_score() -> None:
    """The 112 trainee's score reads the 112 call's events only: a ДДС → 112 call with every
    checklist item covered changes no result of the demo's rules (and rescoring is equal, INV 9)."""
    version = ScenarioVersion.model_validate(demo_document())
    session_id = SessionId(uuid.uuid4())
    call_id = uuid.uuid4()
    _, started = start_call(
        call_id=call_id,
        session_id=session_id,
        kind=DdsCallKind.OPERATOR_112,
        direction=DdsCallDirection.OUTBOUND,
        dialed="112",
        endpoint=CallEndpoint.BROWSER,
        actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=uuid.uuid4()),
        now_ms=10,
        selection_reason=CallSelectionReason.BROWSER_BUTTON,
        persona_id="OPERATOR_112",
    )
    items = [
        agent_event(
            EventType.DDS_CALL_ASSERTION,
            {
                "call_id": str(call_id),
                "turn_id": str(uuid.uuid4()),
                "field_path": path,
                "value_ru": "…",
                "matches_snapshot": True,
                "at_offset_ms": 20,
            },
        )
        for path, _prompt in OPERATOR_112_CHECKLIST
    ]
    completed = agent_event(
        EventType.SESSION_COMPLETED,
        {"at_offset_ms": 30, "final_session_state": "COMPLETED", "total_events": 0},
    )
    with_call = [
        _stored(index + 1, event, session_id)
        for index, event in enumerate([started, *items, completed])
    ]
    without_call = [_stored(1, completed, session_id)]
    report = score(version, with_call)
    assert report == score(version, with_call)

    def numbers(results: Any) -> list[tuple[Any, ...]]:
        # Evidence names the log's own bounding event, so only the numbers are compared.
        return [
            (r.rule_id, r.points_awarded, r.max_points, r.passed, r.critical_failure)
            for r in results
        ]

    assert numbers(report.results) == numbers(score(version, without_call).results)
    assert report.total_points == score(version, without_call).total_points
