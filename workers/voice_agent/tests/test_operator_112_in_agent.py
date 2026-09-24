"""The voice agent's side of a ДДС call to 112 (I3 E6d, HLD `80-telephony.md` §80.3.4, §80.3.6).

* `voice:join {call_kind: OPERATOR_112}` starts a pipeline (E6b and E6c ignored it), carrying the
  persona the backend resolved (`OPERATOR_112`);
* the call runs the same responder chain as a service head — `ServiceHeadResponder` behind ASR,
  a ДДС call's appender, the session's turn numbering — speaking through a `PersonaSpeechSink` in
  the operator persona's LOGICAL voice (`ru_female_adult_01`);
* the operator's fixed lines — its greeting and REQ-5332's prompts — are what the agent
  pre-synthesises for that voice.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import voice_agent.main as agent_main
from app.application.dialogue.responder_templates import (
    OPERATOR_112_CHECKLIST,
    ResponderTemplates,
)
from app.application.dialogue.service_head import ServiceHeadResponder
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.config.settings import Settings
from app.domain.common.ids import SessionId
from app.infrastructure.reference.file_catalog import FileReferenceCatalog
from voice_agent.main import RESPONDER_CALL_KINDS, SUPPORTED_DDS_CALL_KINDS, VoiceAgent
from voice_agent.wiring import PersonaSpeechSink, VoiceAgentDeps

SESSION = SessionId(uuid.UUID("00000000-0000-4000-8000-0000000005e5"))
CALL_112 = uuid.UUID("00000000-0000-4000-8000-000000000112")


def deps() -> VoiceAgentDeps:
    """The E6b suite's gate settings (`test_dds_calls_in_agent.py`): fakes, no network."""
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        redis_url="redis://localhost:56379/0",
        jwt_secret="test-only-secret-padded-32-bytes!",
        livekit_url="ws://localhost:7880",
        livekit_api_key="devkey",
        livekit_api_secret="devsecret1234567890",
        llm_base_url="http://localhost:8080/v1",
    )
    return VoiceAgentDeps.build(settings, FakeClock(), lambda: None)  # type: ignore[arg-type,return-value]


def join(call_id: uuid.UUID, room: str, **extra: str) -> str:
    return json.dumps({"session_id": str(SESSION), "room": room, "call_id": str(call_id), **extra})


async def test_a_112_join_starts_a_pipeline_with_the_operator_persona() -> None:
    assert "OPERATOR_112" in SUPPORTED_DDS_CALL_KINDS
    assert "OPERATOR_112" in RESPONDER_CALL_KINDS
    agent = VoiceAgent(deps(), redis=None)
    started: list[dict[str, Any]] = []

    async def fake_run_call(
        session_id: SessionId, call_id: uuid.UUID, room: str, **kwargs: Any
    ) -> None:
        started.append({"call_id": call_id, **kwargs})
        await asyncio.sleep(3600)

    agent._run_call = fake_run_call  # type: ignore[method-assign]
    try:
        payload = join(CALL_112, "dds-112", call_kind="OPERATOR_112", persona_id="OPERATOR_112")
        await agent._on_join(payload)
        await agent._on_join(payload)  # §40.6's retry: a no-op
        await asyncio.sleep(0)
        assert agent.active_calls == ((SESSION, CALL_112),)
        assert started == [
            {
                "call_id": CALL_112,
                "dds_call": True,
                "call_kind": "OPERATOR_112",
                "persona_id": "OPERATOR_112",
            }
        ]
    finally:
        await agent._drain_calls()


def test_the_operator_voice_comes_from_the_reference_pack() -> None:
    agent = VoiceAgent(deps(), redis=None)
    assert agent._persona_voice("OPERATOR_112") == "ru_female_adult_01"


async def test_a_112_call_runs_the_responder_chain_in_the_operator_voice(
    monkeypatch: Any,
) -> None:
    """`_run_call` for `OPERATOR_112` hands `build_pipeline` the responder chain as its next
    stage — never the frozen caller chain — with a ДДС call's options."""
    built = deps()
    captured: dict[str, Any] = {}

    class _Pipeline:
        async def run(self) -> None:
            return None

        async def stop(self, reason: str) -> None:
            return None

    def fake_build_pipeline(*args: Any, **kwargs: Any) -> _Pipeline:
        captured.update(kwargs)
        return _Pipeline()

    async def no_started_at(session_id: SessionId) -> None:
        return None

    async def first_turn(session_id: SessionId) -> int:
        return 7

    async def no_watch(*args: Any) -> None:
        return None

    monkeypatch.setattr(agent_main, "build_pipeline", fake_build_pipeline)
    agent = VoiceAgent(
        built,
        redis=None,
        transport_factory=lambda *args: FakeCallTransport(clock=FakeClock(), inbound=[]),
    )
    agent._session_started_at = no_started_at  # type: ignore[method-assign]
    agent._next_turn_index = first_turn  # type: ignore[method-assign]
    agent._watch_cancel = no_watch  # type: ignore[method-assign]
    await agent._run_call(
        SESSION,
        CALL_112,
        "dds-112",
        dds_call=True,
        call_kind="OPERATOR_112",
        persona_id="OPERATOR_112",
    )
    assert captured["dds_call"] is True
    assert captured["first_turn_index"] == 7
    head = captured["next_stage"]
    assert isinstance(head, ServiceHeadResponder)
    sink = head._sink
    assert isinstance(sink, PersonaSpeechSink)
    assert (await sink._voice_for(SESSION)).voice_id == "ru_female_adult_01"


def test_the_operator_fixed_lines_are_its_greeting_and_the_checklist_prompts() -> None:
    personas = FileReferenceCatalog().catalog().personas("v046_24-r1")
    assert personas is not None
    operator = personas.get("OPERATOR_112")
    assert operator is not None
    lines = ResponderTemplates().static_lines(operator)
    assert lines[0] == operator.greeting_ru
    for _path, prompt in OPERATOR_112_CHECKLIST:
        assert prompt in lines
    # A service head's status words are not the operator's.
    assert "Докладываю." not in lines
