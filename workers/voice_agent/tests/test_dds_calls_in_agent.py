"""The voice agent's side of the ДДС phone line (I3 E6b, HLD `80-telephony.md` §80.3.6, D23).

* `_calls` is keyed by `(session_id, call_id)`: the session's 112 call and a claimant call-back
  are two pipelines, a repeated `voice:join` of either is a no-op, and a ДДС kind this build does
  not run (`SERVICE_HEAD` E6c, `OPERATOR_112` E6d) is ignored;
* `call_kind: CLAIMANT` runs the frozen caller pipeline — the same `build_pipeline` — with three
  additive arguments: no `CALL_ENDED` (a ДДС call writes nothing of the 112 call's: neither that
  event nor `session:{id}:call_state`), the session's turn numbering continued, «ДИСПЕТЧЕР»;
* the pipeline's own `TRANSPORT_LOST` becomes SYSTEM's `hang_up` of the ДДС call;
* `voice:cancel:{session_id}` stops only the pipeline whose `call_id` it names.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
import voice_agent.wiring as wiring_module
from app.application.dialogue.prompt_builder import DISPATCHER_LABEL_RU, OPERATOR_LABEL_RU
from app.application.dialogue.responder import DialogueResponder
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.asr_responder import AsrTurnResponder
from app.application.voice.events import VoiceEventAppender, call_ended_event
from app.config.settings import Settings
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.dds.call import DdsCallEndReason
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from voice_agent.main import VoiceAgent
from voice_agent.wiring import DdsCallEventAppender, VoiceAgentDeps, build_pipeline

SESSION = SessionId(uuid.UUID("00000000-0000-4000-8000-0000000005e5"))
CALL_112 = uuid.UUID("00000000-0000-4000-8000-000000000112")
DDS_CALL = uuid.UUID("00000000-0000-4000-8000-00000000dd5c")


def settings(**overrides: Any) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        "redis_url": "redis://localhost:56379/0",
        "jwt_secret": "test-only-secret-padded-32-bytes!",
        "livekit_url": "ws://localhost:7880",
        "livekit_api_key": "devkey",
        "livekit_api_secret": "devsecret1234567890",
        "llm_base_url": "http://localhost:8080/v1",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def deps() -> VoiceAgentDeps:
    return VoiceAgentDeps.build(settings(), FakeClock(), lambda: None)  # type: ignore[arg-type,return-value]


def join(call_id: uuid.UUID, room: str, **extra: str) -> str:
    return json.dumps({"session_id": str(SESSION), "room": room, "call_id": str(call_id), **extra})


# ---------------------------------------------------------------------------------------------
# `_calls` per (session_id, call_id)
# ---------------------------------------------------------------------------------------------


async def test_the_112_call_and_a_claimant_call_back_are_two_pipelines() -> None:
    agent = VoiceAgent(deps(), redis=None)
    started: list[tuple[uuid.UUID, bool]] = []

    async def fake_run_call(
        session_id: SessionId, call_id: uuid.UUID, room: str, *, dds_call: bool = False
    ) -> None:
        started.append((call_id, dds_call))
        await asyncio.sleep(3600)

    agent._run_call = fake_run_call  # type: ignore[method-assign]
    try:
        await agent._on_join(join(CALL_112, f"session-{SESSION}"))
        await agent._on_join(join(DDS_CALL, f"dds-{SESSION}-{DDS_CALL}", call_kind="CLAIMANT"))
        # §40.6's retry re-publishes both; each is a no-op now.
        await agent._on_join(join(CALL_112, f"session-{SESSION}"))
        await agent._on_join(join(DDS_CALL, f"dds-{SESSION}-{DDS_CALL}", call_kind="CLAIMANT"))
        # `OPERATOR_112` needs E6d's responder chain and is not run by this build (the service
        # head, E6c, is: `test_service_head_in_agent.py`).
        await agent._on_join(join(uuid.uuid4(), "dds-y", call_kind="OPERATOR_112"))
        await asyncio.sleep(0)
        assert set(agent.active_calls) == {(SESSION, CALL_112), (SESSION, DDS_CALL)}
        assert agent.active_sessions == (SESSION,)
        assert sorted(started) == sorted([(CALL_112, False), (DDS_CALL, True)])
    finally:
        await agent._drain_calls()


# ---------------------------------------------------------------------------------------------
# The claimant pipeline: the frozen chain, three additive arguments
# ---------------------------------------------------------------------------------------------


def _generator_label(pipeline: Any) -> str:
    responder = pipeline._responder
    assert isinstance(responder, AsrTurnResponder)
    dialogue = responder._next_stage
    assert isinstance(dialogue, DialogueResponder)
    builder = dialogue._generator._builder
    label: str = builder._operator_label_ru
    return label


def test_a_claimant_pipeline_is_the_caller_pipeline_with_the_dds_arguments() -> None:
    built = deps()
    transport = FakeCallTransport(clock=FakeClock(), inbound=[])
    caller = build_pipeline(
        built, session_id=SESSION, call_id=CALL_112, transport=transport, record=False
    )
    claimant = build_pipeline(
        built,
        session_id=SESSION,
        call_id=DDS_CALL,
        transport=transport,
        record=False,
        dds_call=True,
        first_turn_index=9,
        operator_label_ru=DISPATCHER_LABEL_RU,
    )
    assert type(caller._appender) is VoiceEventAppender
    assert type(claimant._appender) is DdsCallEventAppender
    assert caller._detector._next_turn_index == 0
    assert claimant._detector._next_turn_index == 9
    assert _generator_label(caller) == OPERATOR_LABEL_RU
    assert _generator_label(claimant) == DISPATCHER_LABEL_RU
    assert type(claimant) is type(caller)


class _RecordingUow:
    """A Unit of Work that records what the voice appender commits (no database)."""

    appended: ClassVar[list[DomainEvent]] = []

    def __init__(self) -> None:
        self.events = self
        self.sessions = self
        self.audio_segments = self
        self.transcript_segments = self
        self.dialogue_turns = self

    async def __aenter__(self) -> _RecordingUow:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, _session_id: Any) -> None:
        return None

    async def append(self, _session_id: Any, events: list[DomainEvent]) -> list[DomainEvent]:
        _RecordingUow.appended.extend(events)
        return list(events)

    async def commit(self) -> None:
        return None


def _tts_started() -> DomainEvent:
    return DomainEvent(
        event_type=EventType.CALLER_TTS_STARTED,
        actor=ActorRef(actor_type=ActorType.SIMULATION),
        monotonic_offset_ms=10,
        payload={"call_id": str(DDS_CALL), "turn_index": 0, "at_offset_ms": 10},
    )


@pytest.mark.parametrize("reason", ["TRANSPORT_CLOSED", "CANCELLED", "HANGUP"])
async def test_a_dds_call_never_writes_call_ended(
    reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`CALL_ENDED` is the 112 call's (it drives `CallStateView`); a ДДС pipeline drops it."""
    ended: list[Any] = []

    class _NoSystemEnd:
        def __init__(self, *_: Any) -> None: ...

        async def __call__(self, *args: Any, **kwargs: Any) -> bool:
            ended.append(args)
            return True

    monkeypatch.setattr(wiring_module, "EndDdsCallBySystem", _NoSystemEnd)
    _RecordingUow.appended = []
    appender = DdsCallEventAppender(
        session_id=SESSION,
        uow_factory=_RecordingUow,  # type: ignore[arg-type]
        clock=FakeClock(start=datetime(2026, 1, 1, tzinfo=UTC)),
    )
    await appender.append(
        [
            _tts_started(),
            call_ended_event(
                call_id=DDS_CALL, offset_ms=20, at_offset_ms=20, duration_ms=10, reason=reason
            ),
        ]
    )
    assert [event.event_type for event in _RecordingUow.appended] == [EventType.CALLER_TTS_STARTED]
    assert ended == []


async def test_a_lost_transport_ends_the_dds_call_by_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pipeline's own `TRANSPORT_LOST` becomes `DDS_CALL_ENDED {reason: TRANSPORT_LOST}`."""
    ended: list[tuple[Any, ...]] = []

    class _SystemEnd:
        def __init__(self, *_: Any) -> None: ...

        async def __call__(self, *args: Any, **kwargs: Any) -> bool:
            ended.append(args)
            return True

    monkeypatch.setattr(wiring_module, "EndDdsCallBySystem", _SystemEnd)
    _RecordingUow.appended = []
    appender = DdsCallEventAppender(
        session_id=SESSION,
        uow_factory=_RecordingUow,  # type: ignore[arg-type]
        clock=FakeClock(),
    )
    await appender.append(
        [
            call_ended_event(
                call_id=DDS_CALL,
                offset_ms=20,
                at_offset_ms=20,
                duration_ms=10,
                reason=DdsCallEndReason.TRANSPORT_LOST.value,
            )
        ]
    )
    assert _RecordingUow.appended == []
    assert ended == [(SESSION, DDS_CALL)]


# ---------------------------------------------------------------------------------------------
# `voice:cancel:{session_id}`, per call
# ---------------------------------------------------------------------------------------------


class _PubSub:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = messages
        self.subscribed: list[str] = []

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def unsubscribe(self, _channel: str) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def listen(self) -> Any:
        for message in self._messages:
            yield message
        await asyncio.sleep(3600)


class _Redis:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.pubsub_instance = _PubSub(messages)

    def pubsub(self) -> _PubSub:
        return self.pubsub_instance


class _Pipeline:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    async def stop(self, reason: str) -> None:
        self.stopped.append(reason)


async def test_a_cancel_stops_only_the_call_it_names() -> None:
    def message(call_id: uuid.UUID, reason: str) -> dict[str, Any]:
        return {"type": "message", "data": json.dumps({"call_id": str(call_id), "reason": reason})}

    redis = _Redis([message(CALL_112, "HANGUP"), message(DDS_CALL, "ABORT")])
    agent = VoiceAgent(deps(), redis)
    pipeline = _Pipeline()
    await asyncio.wait_for(agent._watch_cancel(SESSION, DDS_CALL, pipeline), timeout=5)
    assert pipeline.stopped == ["ABORT"]
    assert redis.pubsub_instance.subscribed == [f"voice:cancel:{SESSION}"]
