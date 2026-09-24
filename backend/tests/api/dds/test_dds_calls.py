"""The ДДС phone line — `dds_brigade_call: ON` (I3 E6b, HLD `80-telephony.md` §80.3, §80.5, §80.6).

The tests the E6b row of HLD 90 owes, on fakes (`FakeCallTransportStatus`, `InMemoryVoiceSignals`,
`StubVoiceTokenService`, the fake ASR / LLM / TTS of the frozen chain; no GPU, no network):

* the claimant call over HTTP: `startDdsCall {kind: CLAIMANT}` → `RINGING` → the AI claimant
  answers `answer_after_ms` later → `hangUpDdsCall` — each transition one event, `voice:join`
  carrying the additive keys of §80.3.6, `voice:cancel` naming the call;
* `ring` waits for the transport; the claimant is `busy` while the session's 112 call is live;
  `409 DDS_LINE_BUSY`; R41 at session creation; `OFF` offers no call and appends no `DDS_CALL_*`;
* INV 13 — `GET …/dds-calls` + `createVoiceToken {call_id}` restore a live call;
* call-scoped visibility — a ДДС call's turn events never reach the OPERATOR_112 reader, and do
  reach the ДДС one (REST twin of the socket, including a resumed cursor);
* scoring — a ДДС call's `FACTS_DELIVERED` never moves the 112 `FACT_OBTAINED` score, and rescoring
  a log with a ДДС call is equal (INV 9);
* INV 8 — `DDS_CALL_TRANSITIONS` is the whole machine; INV 3 — no call use case holds a
  world-truth, caller-belief or operator-card repository;
* the frozen caller chain per `call_id` — INV 1, INV 12, INV 14 on a claimant call-back.

The claimant session is the committed schema-2 example `street-rubbish-fire` (memo mode,
`responders: DEFAULT`), created with `variants: {dds_brigade_call: ON}` — its `supported` lists
`ON` since E6b (R41 allows it).
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, get_type_hints
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from app.api.container import Container
from app.application.dds.dds_call_flow import AdvanceDdsCalls
from app.application.dds.dds_call_views import GetDdsCall, ListDdsCalls
from app.application.dds.end_dds_call import EndDdsCallBySystem, HangUpDdsCall
from app.application.dds.start_dds_call import StartDdsCall
from app.application.dialogue.dialogue_context import DialogueContextLoader
from app.application.dialogue.fallbacks import FallbackTemplates
from app.application.dialogue.generator import CallerResponseGenerator, GeneratorConfig
from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
from app.application.dialogue.prompt_builder import (
    DISPATCHER_LABEL_RU,
    CallerPromptBuilder,
    CallerPromptConfig,
)
from app.application.dialogue.responder import DialogueResponder
from app.application.dialogue.speech_sink import NullCallerSpeechSink
from app.application.dialogue.validator import ResponseValidator, ValidatorConfig
from app.application.ports.llm import LlmUnavailableError
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import (
    FakeCallTransportStatus,
    FakeClock,
    FakeInferenceReadiness,
    FakePasswordHasher,
    InMemoryEventPublisher,
    InMemoryIdempotencyStore,
    InMemoryVoiceSignals,
    StubVoiceTokenService,
)
from app.application.voice.asr_responder import AsrTurnResponder
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.turn_detector import TurnDetector
from app.application.voice.turn_pipeline import TurnContext
from app.config.settings import Settings
from app.db.session import create_session_factory
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import RoleStageId, ScenarioVersionId, SessionId, UserId
from app.domain.common.state_machine import GuardRuntime
from app.domain.dds.call import (
    DDS_CALL_TRANSITIONS,
    CallEndpoint,
    CallSelectionReason,
    DdsCallDirection,
    DdsCallKind,
    DdsCallState,
    fire_call_trigger,
    start_call,
)
from app.domain.enums import ActorType, SessionState
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.facts.revealed import fold_revealed
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.engine import score
from app.inference.asr.fake_asr import FakeASR
from app.inference.llm.fake_llm import FakeLLM
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork, unit_of_work_factory
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth, participant
from tests.api.dds.conftest import OperatorFlow
from tests.fixtures.scenarios import demo_document
from tests.unit.application.dialogue.conftest import (
    DialogueStore,
    make_store,
    make_uow_factory,
    transcribed_turn,
)
from tests.unit.application.voice.conftest import VoiceStore, make_vad
from tests.unit.application.voice.conftest import uow_factory as voice_uow_factory
from tests.unit.application.voice.test_barge_in import (
    SpeakingResponder,
    two_turns,
)

pytestmark = pytest.mark.integration

API = "/api/v1/sessions"
EXAMPLE_SLUG = "street-rubbish-fire"
CLAIMANT_DIGITS = "79161234567"
"""The example prefab's `caller.phone` ("+79161234567"), digits only (REQ-5917)."""
ANSWER_AFTER_MS = 4000


# ---------------------------------------------------------------------------------------------
# Fixtures: the DDS suite's movable-clock container, plus the three call fakes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def transport() -> FakeCallTransportStatus:
    return FakeCallTransportStatus(ready=True)


@pytest.fixture
def voice_signals() -> InMemoryVoiceSignals:
    return InMemoryVoiceSignals()


@pytest.fixture
def voice_tokens() -> StubVoiceTokenService:
    return StubVoiceTokenService()


@pytest.fixture
def container(
    api_settings: Settings,
    migrated_engine: AsyncEngine,
    redis_client: Redis,
    publisher: InMemoryEventPublisher,
    hasher: FakePasswordHasher,
    inference: FakeInferenceReadiness,
    idempotency: InMemoryIdempotencyStore,
    clock: FakeClock,
    transport: FakeCallTransportStatus,
    voice_signals: InMemoryVoiceSignals,
    voice_tokens: StubVoiceTokenService,
) -> Container:
    """`tests.api.dds.conftest.container` (the movable clock) with the call fakes injected."""
    session_factory = create_session_factory(migrated_engine)
    return Container(
        api_settings,
        engine=migrated_engine,
        session_factory=session_factory,
        redis=redis_client,
        publisher=publisher,
        clock=clock,
        unit_of_work=unit_of_work_factory(session_factory, clock, publisher),
        hasher=hasher,
        inference=inference,
        idempotency=idempotency,
        call_transport_status=transport,
        voice_signals=voice_signals,
        voice_tokens=voice_tokens,
        owns_engine=False,
        owns_redis=False,
    )


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


async def create_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    version_id: ScenarioVersionId,
    variants: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        API,
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(version_id),
            "session_mode": "SINGLE_ROLE",
            "participants": [participant(users["trainee2"], "DDS")],
            **({"variants": variants} if variants is not None else {}),
        },
    )


async def started_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    version_id: ScenarioVersionId,
    variants: dict[str, str] | None = None,
) -> UUID:
    created = await create_session(client, tokens, users, version_id, variants)
    assert created.status_code == 201, created.text
    session_id = UUID(created.json()["id"])
    started = await client.post(f"{API}/{session_id}/start", headers=auth(tokens["instructor1"]))
    assert started.status_code == 200, started.text
    return session_id


@pytest.fixture
async def on_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
) -> UUID:
    """The example in memo mode with the ДДС phone (`dds_brigade_call: ON`), played by trainee2."""
    return await started_session(
        client, tokens, users, rubbish_version_id, {"dds_brigade_call": "ON"}
    )


@pytest.fixture
async def off_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
) -> UUID:
    """The same example with the scenario's default — brigade call `OFF` (C7)."""
    return await started_session(client, tokens, users, rubbish_version_id)


def dds(tokens: dict[str, str]) -> dict[str, str]:
    return auth(tokens["trainee2"])


async def start_claimant_call(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID
) -> httpx.Response:
    return await client.post(
        f"{API}/{session_id}/dds-calls", headers=dds(tokens), json={"kind": "CLAIMANT"}
    )


async def instructor_events(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID
) -> list[dict[str, Any]]:
    response = await client.get(
        f"{API}/{session_id}/events",
        headers=auth(tokens["instructor1"]),
        params={"limit": 1000},
    )
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def of_type(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID, event_type: str
) -> list[dict[str, Any]]:
    return [
        item
        for item in await instructor_events(client, tokens, session_id)
        if item["event_type"] == event_type
    ]


async def tick(container: Container, session_id: UUID) -> None:
    await container.runner.tick_now(SessionId(session_id))


async def append(container: Container, session_id: UUID, events: list[DomainEvent]) -> None:
    """Append events through the event store, as the voice agent does (D9)."""
    async with container.unit_of_work() as uow:
        await uow.events.append(SessionId(session_id), events)
        await uow.commit()


def agent_event(event_type: EventType, payload: dict[str, Any]) -> DomainEvent:
    return DomainEvent(
        event_type=event_type,
        actor=ActorRef(actor_type=ActorType.SIMULATION),
        monotonic_offset_ms=500,
        payload=payload,
    )


def tts_started(call_id: str, turn_index: int = 0) -> DomainEvent:
    return agent_event(
        EventType.CALLER_TTS_STARTED,
        {
            "call_id": call_id,
            "turn_index": turn_index,
            "text_sent_to_tts": "Да, это я звонила.",
            "tts_provider": "fake",
            "tts_model": "fake",
            "voice_id": "ru_female_adult_01",
            "at_offset_ms": 500,
        },
    )


# ---------------------------------------------------------------------------------------------
# OFF: no phone at all
# ---------------------------------------------------------------------------------------------


async def test_an_off_session_offers_no_call_action_and_appends_no_dds_call_event(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    off_session: UUID,
    container: Container,
) -> None:
    snapshot = await client.get(f"{API}/{off_session}/snapshot", headers=dds(tokens))
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["session"]["variants"]["dds_brigade_call"] == "OFF"
    actions = {action["action_id"] for action in snapshot.json()["available_actions"]}
    assert "call_claimant" not in actions

    refused = await start_claimant_call(client, tokens, off_session)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ACTION_NOT_AVAILABLE"

    await tick(container, off_session)
    types = {item["event_type"] for item in await instructor_events(client, tokens, off_session)}
    assert not {t for t in types if t.startswith("DDS_CALL_")}
    listed = await client.get(f"{API}/{off_session}/dds-calls", headers=dds(tokens))
    assert listed.status_code == 200 and listed.json() == []


# ---------------------------------------------------------------------------------------------
# ON: the claimant call, end to end over HTTP
# ---------------------------------------------------------------------------------------------


async def test_on_offers_call_claimant_on_the_stage(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID
) -> None:
    snapshot = await client.get(f"{API}/{on_session}/snapshot", headers=dds(tokens))
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["session"]["variants"]["dds_brigade_call"] == "ON"
    actions = {
        action["action_id"]: action["label_ru"] for action in snapshot.json()["available_actions"]
    }
    assert actions["call_claimant"] == "Позвонить заявителю"
    # E6c landed the service head («Позвонить старшему»), E6d the call to 112
    # (`test_operator_112_calls.py`).
    assert actions["call_service_head"] == "Позвонить старшему"
    assert actions["call_112"] == "Позвонить в 112"


async def test_the_claimant_call_rings_is_answered_and_is_hung_up(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
    voice_signals: InMemoryVoiceSignals,
    voice_tokens: StubVoiceTokenService,
) -> None:
    started = await start_claimant_call(client, tokens, on_session)
    assert started.status_code == 201, started.text
    call = started.json()["call"]
    call_id = call["call_id"]
    assert call["state"] == "RINGING"
    assert (call["kind"], call["direction"], call["endpoint"]) == (
        "CLAIMANT",
        "OUTBOUND",
        "BROWSER",
    )
    assert call["dialed"] == CLAIMANT_DIGITS
    assert call["persona_title_ru"] == "Заявитель"
    assert call["room_name"] == f"dds-{on_session}-{call_id}"
    assert call["actor_user_id"] == str(users["trainee2"])
    assert [action["action_id"] for action in call["available_actions"]] == ["hang_up"]
    # The browser endpoint's room-scoped token, for this call's room only (D9).
    assert started.json()["voice"]["room_name"] == call["room_name"]
    assert voice_tokens.calls[-1] == (call["room_name"], str(users["trainee2"]))
    # `voice:join` after the commit, with §80.3.6's additive keys.
    assert voice_signals.joins[-1] == (SessionId(on_session), call["room_name"], UUID(call_id))
    assert voice_signals.join_extras[-1] == {
        "call_kind": "CLAIMANT",
        "assignment_id": None,
        "persona_id": None,
        "endpoint": "BROWSER",
        "direction": "OUTBOUND",  # additive, I3 E6c
    }

    # The AI claimant answers `answer_after_ms` after the call started, on a tick (SIMULATION).
    await tick(container, on_session)
    assert (await get_call(client, tokens, on_session, call_id))["state"] == "RINGING"
    clock.advance_ms(ANSWER_AFTER_MS)
    await tick(container, on_session)
    connected = await get_call(client, tokens, on_session, call_id)
    assert connected["state"] == "CONNECTED"
    assert connected["answered_by"] == "AI"

    clock.advance_ms(7_000)
    hung_up = await client.post(
        f"{API}/{on_session}/dds-calls/{call_id}/hang-up", headers=dds(tokens)
    )
    assert hung_up.status_code == 200, hung_up.text
    ended = hung_up.json()
    assert (ended["state"], ended["end_reason"]) == ("ENDED", "HANGUP")
    assert ended["available_actions"] == []
    assert voice_signals.cancels[-1][:3] == (SessionId(on_session), UUID(call_id), "HANGUP")

    # Every accepted transition appended exactly one event (`ring` none), in order.
    call_events = [
        item
        for item in await instructor_events(client, tokens, on_session)
        if item["event_type"].startswith("DDS_CALL_")
    ]
    assert [item["event_type"] for item in call_events] == [
        "DDS_CALL_STARTED",
        "DDS_CALL_ANSWERED",
        "DDS_CALL_ENDED",
    ]
    started_payload, answered_payload, ended_payload = (item["payload"] for item in call_events)
    assert started_payload["kind"] == "CLAIMANT"
    assert started_payload["selection_reason"] == "BROWSER_BUTTON"
    assert started_payload["room"] == call["room_name"]
    assert answered_payload["answered_by"] == "AI"
    assert ended_payload["reason"] == "HANGUP"
    assert ended_payload["duration_ms"] == 7_000
    assert [item["actor_type"] for item in call_events] == ["TRAINEE", "SIMULATION", "TRAINEE"]

    again = await client.post(
        f"{API}/{on_session}/dds-calls/{call_id}/hang-up", headers=dds(tokens)
    )
    assert again.status_code == 409 and again.json()["code"] == "INVALID_TRANSITION"
    # The 112 call's widget state is untouched: no `CALL_*` event was ever written.
    types = {item["event_type"] for item in await instructor_events(client, tokens, on_session)}
    assert not {"CALL_RINGING", "CALL_ANSWERED", "CALL_ENDED"} & types


async def get_call(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID, call_id: str
) -> dict[str, Any]:
    response = await client.get(f"{API}/{session_id}/dds-calls/{call_id}", headers=dds(tokens))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_ring_waits_for_the_transport(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    transport: FakeCallTransportStatus,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    """`guard_dds_call_transport_ready`: no media plane, no ring — the call waits in `DIALING`."""
    transport.ready = False
    started = await start_claimant_call(client, tokens, on_session)
    assert started.status_code == 201, started.text
    call_id = started.json()["call"]["call_id"]
    assert started.json()["call"]["state"] == "DIALING"
    assert voice_signals.joins == []
    await tick(container, on_session)
    assert (await get_call(client, tokens, on_session, call_id))["state"] == "DIALING"

    transport.ready = True
    await tick(container, on_session)
    assert (await get_call(client, tokens, on_session, call_id))["state"] == "RINGING"
    assert [join[2] for join in voice_signals.joins] == [UUID(call_id)]


async def test_one_line_per_workstation(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID
) -> None:
    first = await start_claimant_call(client, tokens, on_session)
    assert first.status_code == 201, first.text
    second = await start_claimant_call(client, tokens, on_session)
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "DDS_LINE_BUSY"
    listed = await client.get(f"{API}/{on_session}/dds-calls", headers=dds(tokens))
    assert len(listed.json()) == 1


async def test_the_claimant_is_busy_while_the_112_call_is_live(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    """§80.3.2 `busy`: the claimant cannot be on two calls — the call comes back `ENDED/BUSY`."""
    await append(
        container,
        on_session,
        [
            agent_event(
                EventType.CALL_RINGING,
                {
                    "call_id": str(uuid.uuid4()),
                    "room_name": f"session-{on_session}",
                    "caller_display_ru": "Входящий вызов 112",
                    "at_offset_ms": 100,
                },
            )
        ],
    )
    started = await start_claimant_call(client, tokens, on_session)
    assert started.status_code == 201, started.text
    call = started.json()["call"]
    assert (call["state"], call["end_reason"]) == ("ENDED", "BUSY")
    assert started.json()["voice"] is None
    assert voice_signals.joins == []
    ended = await of_type(client, tokens, on_session, "DDS_CALL_ENDED")
    assert [item["payload"]["reason"] for item in ended] == ["BUSY"]
    assert ended[0]["payload"]["duration_ms"] == 0
    # A busy line is free again at once.
    assert (await start_claimant_call(client, tokens, on_session)).status_code == 201


async def test_on_with_the_resource_picker_is_409_variant_not_supported(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
) -> None:
    """R41's session half: the ДДС phone exists in memo mode only."""
    response = await create_session(
        client,
        tokens,
        users,
        rubbish_version_id,
        {"dds_brigade_call": "ON", "dds_mode": "RESOURCE_PICKER"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "VARIANT_NOT_SUPPORTED"


async def test_list_and_voice_token_restore_a_live_call(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    on_session: UUID,
) -> None:
    """INV 13: after a refresh the widget finds the live call and re-joins its room."""
    call = (await start_claimant_call(client, tokens, on_session)).json()["call"]
    listed = await client.get(f"{API}/{on_session}/dds-calls", headers=dds(tokens))
    assert listed.status_code == 200, listed.text
    assert [item["call_id"] for item in listed.json()] == [call["call_id"]]
    assert listed.json()[0]["state"] == "RINGING"

    token = await client.post(
        f"{API}/{on_session}/voice-token", headers=dds(tokens), json={"call_id": call["call_id"]}
    )
    assert token.status_code == 200, token.text
    assert token.json()["room_name"] == call["room_name"]
    # The instructor reads the call but holds no line: no action, no token.
    as_instructor = await client.get(
        f"{API}/{on_session}/dds-calls", headers=auth(tokens["instructor1"])
    )
    assert as_instructor.json()[0]["available_actions"] == []
    foreign = await client.post(
        f"{API}/{on_session}/voice-token",
        headers=auth(tokens["instructor1"]),
        json={"call_id": call["call_id"]},
    )
    assert foreign.status_code == 403, foreign.text

    await client.post(
        f"{API}/{on_session}/dds-calls/{call['call_id']}/hang-up", headers=dds(tokens)
    )
    gone = await client.post(
        f"{API}/{on_session}/voice-token", headers=dds(tokens), json={"call_id": call["call_id"]}
    )
    assert gone.status_code == 409, gone.text
    unknown = await client.get(f"{API}/{on_session}/dds-calls/{uuid.uuid4()}", headers=dds(tokens))
    assert unknown.status_code == 404, unknown.text


async def test_the_read_model_is_rebuildable_from_the_log(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
) -> None:
    """INV 13: `dds_calls` is a cache of the `DDS_CALL_*` events (`fold_dds_calls`)."""
    from app.domain.dds.call import fold_dds_calls

    call_id = (await start_claimant_call(client, tokens, on_session)).json()["call"]["call_id"]
    clock.advance_ms(ANSWER_AFTER_MS)
    await tick(container, on_session)
    await client.post(f"{API}/{on_session}/dds-calls/{call_id}/hang-up", headers=dds(tokens))
    async with container.unit_of_work() as uow:
        stored = await uow.dds_calls.list_for_session(SessionId(on_session))
        log = await uow.events.read(SessionId(on_session))
        await uow.commit()
    assert fold_dds_calls(SessionId(on_session), log) == stored


# ---------------------------------------------------------------------------------------------
# Call-scoped visibility (HLD 80 §80.6.2, HLD 40 §40.4)
# ---------------------------------------------------------------------------------------------


async def test_a_dds_calls_turn_never_reaches_the_operator_reader(dds_active: OperatorFlow) -> None:
    """A ДДС call's `CALLER_TTS_STARTED` goes to DDS and never to OPERATOR_112; the 112 call's
    goes to OPERATOR_112 only — from the start of the log and from a resumed cursor alike."""
    flow = dds_active
    session_id = UUID(str(flow.session_id))
    dds_call = str(uuid.uuid4())
    _, started = start_call(
        call_id=UUID(dds_call),
        session_id=SessionId(session_id),
        kind=DdsCallKind.CLAIMANT,
        direction=DdsCallDirection.OUTBOUND,
        dialed=CLAIMANT_DIGITS,
        endpoint=CallEndpoint.BROWSER,
        actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=flow.dds_user_id),
        now_ms=400,
        selection_reason=CallSelectionReason.BROWSER_BUTTON,
    )
    await append(flow.container, session_id, [started])
    cursor = (await flow.get("/events", token=flow.instructor_token)).json()["last_seq_no"]
    other_call = str(uuid.uuid4())
    await append(flow.container, session_id, [tts_started(dds_call), tts_started(other_call)])

    def call_ids(items: list[dict[str, Any]]) -> list[str]:
        return [
            item["payload"]["call_id"]
            for item in items
            if item["event_type"] == "CALLER_TTS_STARTED"
        ]

    for params in ({"limit": 1000}, {"limit": 1000, "after_seq_no": cursor}):
        operator = await flow.get("/events", token=flow.operator_token, params=params)
        assert operator.status_code == 200, operator.text
        assert dds_call not in call_ids(operator.json()["items"])
        assert other_call in call_ids(operator.json()["items"])
        ddsview = await flow.get("/events", token=flow.dds_token, params=params)
        assert ddsview.status_code == 200, ddsview.text
        assert call_ids(ddsview.json()["items"]) == [dds_call]
        # Same trainee whitelist as OPERATOR_112 gets (§40.4 row 12).
        [item] = [i for i in ddsview.json()["items"] if i["event_type"] == "CALLER_TTS_STARTED"]
        assert set(item["payload"]) == {"call_id", "turn_index", "at_offset_ms"}
    operator = await flow.get("/events", token=flow.operator_token, params={"limit": 1000})
    assert "DDS_CALL_STARTED" not in {item["event_type"] for item in operator.json()["items"]}


# ---------------------------------------------------------------------------------------------
# Scoring: a call-back never moves a 112 score; rescore equality (INV 9)
# ---------------------------------------------------------------------------------------------


def _stored(seq_no: int, event: DomainEvent, session_id: SessionId) -> SessionEvent:
    return SessionEvent(
        id=uuid.uuid4(),
        session_id=session_id,
        seq_no=seq_no,
        event_type=event.event_type,
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        monotonic_offset_ms=event.monotonic_offset_ms,
        actor_type=event.actor.actor_type,
        actor_id=event.actor.actor_id,
        correlation_id=None,
        payload=event.payload,
    )


def test_a_dds_calls_facts_delivered_moves_no_112_fact_obtained_score() -> None:
    version = ScenarioVersion.model_validate(demo_document())
    session_id = SessionId(uuid.uuid4())
    rule = next(
        rule for rule in version.scoring_rules if rule.evaluator_type.value == "FACT_OBTAINED"
    )
    fact_id = rule.config["fact_id"]
    dds_call = uuid.uuid4()
    _, started = start_call(
        call_id=dds_call,
        session_id=session_id,
        kind=DdsCallKind.CLAIMANT,
        direction=DdsCallDirection.OUTBOUND,
        dialed=CLAIMANT_DIGITS,
        endpoint=CallEndpoint.BROWSER,
        actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=UserId(uuid.uuid4())),
        now_ms=10,
        selection_reason=CallSelectionReason.BROWSER_BUTTON,
    )
    delivered = agent_event(
        EventType.FACTS_DELIVERED,
        {
            "call_id": str(dds_call),
            "turn_index": 0,
            "turn_id": str(uuid.uuid4()),
            "fact_ids": [fact_id],
            "at_offset_ms": 20,
        },
    )
    completed = agent_event(
        EventType.SESSION_COMPLETED,
        {"at_offset_ms": 30, "final_session_state": "COMPLETED", "total_events": 3},
    )
    with_call = [
        _stored(1, started, session_id),
        _stored(2, delivered, session_id),
        _stored(3, completed, session_id),
    ]
    report = score(version, with_call)
    result = next(item for item in report.results if item.rule_id == rule.rule_id)
    assert result.passed is False, "a ДДС call-back delivery counted towards the 112 score"
    assert report == score(version, with_call), "INV 9: rescoring the same log differs"
    assert report.total_points == score(version, [_stored(1, completed, session_id)]).total_points

    from app.domain.scoring.context import build_context

    ctx = build_context(version, with_call)
    assert ctx.deliveries_of(fact_id) == ()
    assert [d.call_id for d in ctx.deliveries_of(fact_id, on_call="DDS_CLAIMANT")] == [
        str(dds_call)
    ]


async def test_rescoring_a_session_with_a_dds_call_is_equal(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
) -> None:
    """INV 9 over a real log: the ДДС call's events change no number, twice over."""
    call_id = (await start_claimant_call(client, tokens, on_session)).json()["call"]["call_id"]
    clock.advance_ms(ANSWER_AFTER_MS)
    await tick(container, on_session)
    await client.post(f"{API}/{on_session}/dds-calls/{call_id}/hang-up", headers=dds(tokens))
    async with container.unit_of_work() as uow:
        session = await uow.sessions.get(SessionId(on_session))
        assert session is not None
        document = await uow.scenarios.get_version_document(session.scenario_version_id)
        log = await uow.events.read(SessionId(on_session))
        await uow.commit()
    version = ScenarioVersion.model_validate(dict(document))
    # Scoring runs over a closed log (ruling R2): the session's own completion is stood in for.
    closed = [
        *log,
        _stored(
            log[-1].seq_no + 1,
            agent_event(
                EventType.SESSION_COMPLETED,
                {"at_offset_ms": 99_000, "final_session_state": "COMPLETED", "total_events": 0},
            ),
            SessionId(on_session),
        ),
    ]
    without_calls = [e for e in closed if not e.event_type.value.startswith("DDS_CALL_")]
    assert score(version, closed) == score(version, closed)
    assert score(version, closed).results == score(version, without_calls).results


# ---------------------------------------------------------------------------------------------
# INV 8 and INV 3
# ---------------------------------------------------------------------------------------------

_TRIGGERS = ("ring", "answer", "no_answer", "busy", "hang_up", "start", "close")


def _a_call(state: DdsCallState, direction: DdsCallDirection = DdsCallDirection.OUTBOUND) -> Any:
    call, _ = start_call(
        call_id=uuid.uuid4(),
        session_id=SessionId(uuid.uuid4()),
        kind=DdsCallKind.CLAIMANT,
        direction=direction,
        dialed=CLAIMANT_DIGITS,
        endpoint=CallEndpoint.BROWSER,
        actor=(
            ActorRef(actor_type=ActorType.TRAINEE, actor_id=UserId(uuid.uuid4()))
            if direction is DdsCallDirection.OUTBOUND
            else ActorRef(actor_type=ActorType.SIMULATION)
        ),
        now_ms=0,
        selection_reason=CallSelectionReason.BROWSER_BUTTON,
    )
    return call.model_copy(update={"state": state})


@pytest.mark.parametrize("state", list(DdsCallState))
@pytest.mark.parametrize("trigger", _TRIGGERS)
@pytest.mark.parametrize("actor", [ActorType.TRAINEE, ActorType.SIMULATION, ActorType.SYSTEM])
def test_inv_08_every_non_listed_call_transition_fails(
    state: DdsCallState, trigger: str, actor: ActorType
) -> None:
    """INV 8: a `(state, trigger, actor)` the table does not allow raises and moves nothing."""
    call = _a_call(state)
    row = DDS_CALL_TRANSITIONS.get((state, trigger))
    allowed = row is not None and actor in row.allowed_actors
    if trigger == "answer":  # OUTBOUND: only the AI callee answers (the direction guard)
        allowed = allowed and actor is ActorType.SIMULATION
    ref = ActorRef(
        actor_type=actor, actor_id=UserId(uuid.uuid4()) if actor is ActorType.TRAINEE else None
    )
    runtime = GuardRuntime(transport_ready=True)
    if not allowed:
        with pytest.raises(InvalidTransitionError):
            fire_call_trigger(call, trigger, actor=ref, now_ms=5, runtime=runtime)
        return
    moved, _ = fire_call_trigger(call, trigger, actor=ref, now_ms=5, runtime=runtime)
    assert row is not None and moved.state is row.target


def test_inv_08_ring_needs_the_transport_and_an_inbound_call_is_the_trainee_s_to_answer() -> None:
    sim = ActorRef(actor_type=ActorType.SIMULATION)
    with pytest.raises(InvalidTransitionError):
        fire_call_trigger(_a_call(DdsCallState.DIALING), "ring", actor=sim, now_ms=1)
    inbound = _a_call(DdsCallState.RINGING, DdsCallDirection.INBOUND)
    with pytest.raises(InvalidTransitionError):
        fire_call_trigger(inbound, "answer", actor=sim, now_ms=1)
    trainee = ActorRef(actor_type=ActorType.TRAINEE, actor_id=UserId(uuid.uuid4()))
    moved, event = fire_call_trigger(inbound, "answer", actor=trainee, now_ms=1)
    assert moved.state is DdsCallState.CONNECTED and event is not None
    assert event.payload["answered_by"] == "TRAINEE"


@pytest.mark.parametrize(
    "use_case",
    [StartDdsCall, HangUpDdsCall, ListDdsCalls, GetDdsCall, AdvanceDdsCalls, EndDdsCallBySystem],
)
def test_inv_03_no_call_use_case_can_reach_a_hidden_layer(use_case: type) -> None:
    """INV 3: no ДДС call use case is constructed with a WorldTruth, CallerBelief or live-card
    repository — the claimant's frozen chain runs in the voice agent, never in the backend."""
    hints = get_type_hints(use_case.__init__)
    names = " ".join(
        f"{name}:{getattr(hint, '__name__', str(hint))}"
        for name, hint in hints.items()
        if name != "return"
    )
    for forbidden in ("WorldTruth", "CallerBelief", "OperatorCard", "world_truth", "caller_belief"):
        assert forbidden not in names, f"{use_case.__name__} names {forbidden}: {names}"
    assert inspect.signature(use_case.__init__).parameters


# ---------------------------------------------------------------------------------------------
# The frozen caller chain, per `call_id` — INV 1, INV 12, INV 14 on a claimant call-back
# ---------------------------------------------------------------------------------------------

DDS_CALL_ID = uuid.UUID("00000000-0000-4000-8000-00000000dd5c")
ASK_FLOOR = {
    "speech_act": "QUESTION",
    "requested_facts": [{"fact_id": "address.floor", "explicit": True}],
    "operator_assertions": [],
    "confirmation_targets": [],
    "semantic_confidence": 0.95,
}


def _claimant_chain(
    store: DialogueStore, clock: FakeClock, script: list[Any]
) -> tuple[AsrTurnResponder, NullCallerSpeechSink, FakeLLM]:
    """The production chain with the one E6b change: the speaker label «ДИСПЕТЧЕР»."""
    factory = make_uow_factory(store, clock)
    llm = FakeLLM(script)
    metrics = NullMetricsRecorder()
    sink = NullCallerSpeechSink()
    dialogue = DialogueResponder(
        loader=DialogueContextLoader(factory, clock, window_turns=6),  # type: ignore[arg-type]
        interpreter=DialogueInterpreter(llm, metrics, config=InterpreterConfig()),
        generator=CallerResponseGenerator(
            llm,
            metrics,
            CallerPromptBuilder(CallerPromptConfig(), operator_label_ru=DISPATCHER_LABEL_RU),
            ResponseValidator(ValidatorConfig(small_count_allowlist=frozenset())),
            config=GeneratorConfig(),
        ),
        fallbacks=FallbackTemplates(),
        sink=sink,
        uow_factory=factory,  # type: ignore[arg-type]
    )

    async def stage_resolver(session_id: SessionId) -> RoleStageId | None:
        return store.session.stages[0].role_stage_id

    responder = AsrTurnResponder(
        asr=FakeASR(["Какой этаж?"]),
        metrics=metrics,
        clock=clock,
        config=VoiceTurnConfig(),
        stage_resolver=stage_resolver,
        timeout_ms=4000,
        next_stage=dialogue,
    )
    return responder, sink, llm


def _claimant_context(store: DialogueStore, clock: FakeClock) -> TurnContext:
    from app.application.voice.events import VoiceEventAppender

    factory = make_uow_factory(store, clock)
    return TurnContext(
        session_id=store.session.id,
        call_id=DDS_CALL_ID,
        config=VoiceTurnConfig(),
        transport=None,  # type: ignore[arg-type]
        appender=VoiceEventAppender(
            session_id=store.session.id,
            uow_factory=factory,  # type: ignore[arg-type]
            clock=clock,
            started_at=store.session.started_at,
        ),
        recorder=None,
    )


async def _one_claimant_turn(store: DialogueStore, clock: FakeClock, script: list[Any]) -> Any:
    responder, sink, llm = _claimant_chain(store, clock, script)
    turn = transcribed_turn("Какой этаж?", turn_index=0).turn
    context = _claimant_context(store, clock)
    scoped = TurnContext(
        session_id=context.session_id,
        call_id=context.call_id,
        config=context.config,
        transport=context.transport,
        appender=context.appender,
        recorder=None,
        audio_segment_ids={turn.turn_id: uuid.uuid4()},
    )
    await responder.respond(turn, scoped)
    return sink, llm


async def test_inv_01_the_claimant_call_back_prompt_holds_caller_values_only() -> None:
    """INV 1 on a ДДС call: the gate releases the caller's floor «5» (an `INCORRECT_BELIEF`),
    never world truth's «4», and the prompt names the ДДС as «ДИСПЕТЧЕР»; every event is the ДДС
    call's."""
    store = make_store()
    clock = FakeClock(start=datetime(2026, 1, 1, tzinfo=UTC))
    sink, llm = await _one_claimant_turn(store, clock, [ASK_FLOOR, {"utterance": "Пятый этаж."}])
    prompts = [message.content for call in llm.calls for message in call.messages]
    generator_prompt = next(prompt for prompt in prompts if "ГОВОРИТ:" in prompt)
    assert "ДИСПЕТЧЕР ГОВОРИТ:" in generator_prompt
    assert "ОПЕРАТОР ГОВОРИТ:" not in generator_prompt
    allowed = generator_prompt.split("ALLOWED_FACTS:", 1)[1].split("ALREADY_REVEALED:", 1)[0]
    assert "5" in allowed and "4" not in allowed
    call_ids = {
        str(event.payload["call_id"]) for event in store.events if "call_id" in event.payload
    }
    assert call_ids == {str(DDS_CALL_ID)}
    assert sink.spoken


async def test_inv_14_a_model_failure_on_the_call_back_keeps_the_session() -> None:
    """INV 14 per `call_id`: a generator failure answers the fallback and moves nothing."""
    store = make_store()
    clock = FakeClock(start=datetime(2026, 1, 1, tzinfo=UTC))
    sink, _ = await _one_claimant_turn(store, clock, [ASK_FLOOR, LlmUnavailableError("down")])
    assert store.session.state is SessionState.ACTIVE
    assert [p["component"] for p in store.payloads("MODEL_FALLBACK_USED")] == ["GENERATOR"]
    assert all(
        str(event.payload["call_id"]) == str(DDS_CALL_ID)
        for event in store.events
        if "call_id" in event.payload
    )
    assert sink.spoken and sink.spoken[0].source == "FALLBACK"


async def test_inv_12_a_barge_in_on_the_call_back_reveals_nothing() -> None:
    """INV 12 per `call_id`: the interrupted utterance of a ДДС call reveals no fact, and the
    call's turn numbering continues the session's (`first_turn_index`)."""
    from app.application.testing.fakes import FakeCallTransport
    from app.application.voice.events import VoiceEventAppender
    from app.application.voice.tts_speech_sink import TtsSpeechSink
    from app.application.voice.turn_pipeline import TurnPipeline
    from app.inference.tts.fake_tts import FakeTTS

    config = VoiceTurnConfig()
    clock = FakeClock()
    store = VoiceStore()
    session_id = SessionId(uuid.uuid4())
    transport = FakeCallTransport(
        clock=clock, inbound=two_turns(config), outbound_queue_ms=config.outbound_queue_ms
    )
    factory = voice_uow_factory(store, clock)
    sink = TtsSpeechSink(
        provider=FakeTTS(),
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        uow_factory=factory,
    )
    facts = ("incident.address", "incident.floor")
    pipeline = TurnPipeline(
        session_id=session_id,
        call_id=DDS_CALL_ID,
        transport=transport,
        vad=make_vad(config),
        detector=TurnDetector(config, first_turn_index=7),
        appender=VoiceEventAppender(
            session_id=session_id, uow_factory=factory, clock=clock, started_at=clock.now()
        ),
        clock=clock,
        config=config,
        responder=SpeakingResponder(sink, fact_ids=facts),
    )
    await asyncio.wait_for(pipeline.run(), timeout=10)

    interrupted = next(
        event
        for event in store.events
        if event.event_type is EventType.CALLER_UTTERANCE_INTERRUPTED
    )
    assert str(interrupted.payload["call_id"]) == str(DDS_CALL_ID)
    assert not [
        event
        for event in store.events
        if event.event_type is EventType.FACTS_DELIVERED
        and event.payload["turn_id"] == interrupted.payload["turn_id"]
    ]
    upto = store.events.index(interrupted)
    assert fold_revealed(store.events[: upto + 1]) == frozenset()
    turn_indices = {
        event.payload["turn_index"]
        for event in store.events
        if event.event_type is EventType.USER_SPEECH_STARTED
    }
    assert min(turn_indices) == 7


# ---------------------------------------------------------------------------------------------
# The raw row, for a column no endpoint exposes
# ---------------------------------------------------------------------------------------------


async def test_the_dds_calls_row_carries_its_started_event(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    call_id = (await start_claimant_call(client, tokens, on_session)).json()["call"]["call_id"]
    started = await of_type(client, tokens, on_session, "DDS_CALL_STARTED")
    async with unit_of_work() as uow:
        row = (
            await uow.session.execute(
                sa.text(
                    "SELECT c.state, c.selection_reason, e.event_type FROM dds_calls c "
                    "JOIN session_events e ON e.id = c.started_event_id WHERE c.id = :id"
                ),
                {"id": call_id},
            )
        ).one()
        await uow.commit()
    assert tuple(row) == ("RINGING", "BROWSER_BUTTON", "DDS_CALL_STARTED")
    assert started[0]["payload"]["call_id"] == call_id


def test_a_dds_calls_voice_never_lights_the_112_widget() -> None:
    """HLD 80 §80.3.6: the claimant speaking on a ДДС call is not the 112 caller speaking."""
    from app.application.operator.views import project_call_state

    session_id = SessionId(uuid.uuid4())
    the_112_call = str(uuid.uuid4())
    ringing = agent_event(
        EventType.CALL_RINGING,
        {
            "call_id": the_112_call,
            "room_name": "session-x",
            "caller_display_ru": "Входящий вызов 112",
            "at_offset_ms": 1,
        },
    )
    dds_voice = tts_started(str(uuid.uuid4()))
    state = project_call_state([_stored(1, ringing, session_id), _stored(2, dds_voice, session_id)])
    assert state.caller_speaking is False
    own_voice = tts_started(the_112_call)
    state = project_call_state([_stored(1, ringing, session_id), _stored(2, own_voice, session_id)])
    assert state.caller_speaking is True
