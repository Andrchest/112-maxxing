"""The voice agent's side of a service head's call (I3 E6c, HLD `80-telephony.md` §80.4, §80.3.6).

* `voice:join {call_kind: SERVICE_HEAD}` starts a pipeline (E6b ignored it), carrying the persona;
* the pipeline is the same `TurnPipeline` — a ДДС call's appender, the session's turn numbering —
  with `ServiceHeadResponder` behind ASR instead of the frozen caller chain, speaking through a
  `PersonaSpeechSink` in the persona's LOGICAL voice (the profile's `tts.voice_map` resolves it);
* `voice_agent.tts_cache`: the persona's fixed lines are synthesised once, served from memory and
  from disk, and anything else streams from the wrapped provider;
* the persona's voice is read from the reference pack (`BRIGADE_101` → `ru_male_adult_01`).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.application.dialogue.responder_templates import ResponderTemplates
from app.application.dialogue.service_head import ServiceHeadResponder
from app.application.ports.call_transport import AudioFrame
from app.application.ports.tts import TtsChunk, TtsVoiceSpec
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.asr_responder import AsrTurnResponder
from app.config.settings import Settings
from app.domain.common.ids import SessionId
from voice_agent.main import SUPPORTED_DDS_CALL_KINDS, VoiceAgent
from voice_agent.tts_cache import CachedTTSProvider, TtsLineCache, line_key
from voice_agent.wiring import (
    DdsCallEventAppender,
    PersonaSpeechSink,
    VoiceAgentDeps,
    build_pipeline,
    build_service_head_responder,
)

SESSION = SessionId(uuid.UUID("00000000-0000-4000-8000-0000000005e5"))
DDS_CALL = uuid.UUID("00000000-0000-4000-8000-00000000dd5c")
HEAD_CALL = uuid.UUID("00000000-0000-4000-8000-0000000000c1")


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


async def test_a_service_head_join_starts_a_pipeline_with_its_persona() -> None:
    assert "SERVICE_HEAD" in SUPPORTED_DDS_CALL_KINDS
    agent = VoiceAgent(deps(), redis=None)
    started: list[dict[str, Any]] = []

    async def fake_run_call(
        session_id: SessionId, call_id: uuid.UUID, room: str, **kwargs: Any
    ) -> None:
        started.append({"call_id": call_id, **kwargs})
        await asyncio.sleep(3600)

    agent._run_call = fake_run_call  # type: ignore[method-assign]
    try:
        payload = join(HEAD_CALL, "dds-x", call_kind="SERVICE_HEAD", persona_id="BRIGADE_101")
        await agent._on_join(payload)
        await agent._on_join(payload)  # §40.6's retry: a no-op
        await asyncio.sleep(0)
        assert agent.active_calls == ((SESSION, HEAD_CALL),)
        assert started == [
            {
                "call_id": HEAD_CALL,
                "dds_call": True,
                "call_kind": "SERVICE_HEAD",
                "persona_id": "BRIGADE_101",
            }
        ]
    finally:
        await agent._drain_calls()


def test_the_persona_voice_comes_from_the_reference_pack() -> None:
    agent = VoiceAgent(deps(), redis=None)
    assert agent._persona_voice("BRIGADE_101") == "ru_male_adult_01"
    assert agent._persona_voice("BRIGADE_104") == "ru_male_adult_02"
    assert agent._persona_voice("BRIGADE_103") == "ru_female_adult_01"
    assert agent._persona_voice(None) == agent._deps.settings.tts_voice_id


def test_a_service_head_pipeline_runs_the_responder_chain_in_the_persona_voice() -> None:
    built = deps()
    head = build_service_head_responder(built, voice_id="ru_male_adult_01")
    pipeline = build_pipeline(
        built,
        session_id=SESSION,
        call_id=DDS_CALL,
        transport=FakeCallTransport(clock=FakeClock(), inbound=[]),
        record=False,
        dds_call=True,
        first_turn_index=4,
        next_stage=head,
    )
    assert type(pipeline._appender) is DdsCallEventAppender
    assert pipeline._detector._next_turn_index == 4
    responder = pipeline._responder
    assert isinstance(responder, AsrTurnResponder)
    assert responder._next_stage is head
    assert isinstance(head, ServiceHeadResponder)
    assert head.mode == "template"  # `Settings.responder_dialogue`'s default
    sink = head._sink
    assert isinstance(sink, PersonaSpeechSink)


async def test_the_persona_sink_speaks_in_the_persona_voice_whatever_the_scenario() -> None:
    built = deps()
    head = build_service_head_responder(built, voice_id="ru_male_adult_02")
    sink = head._sink
    assert isinstance(sink, PersonaSpeechSink)
    voice = await sink._voice_for(SESSION)
    assert voice.voice_id == "ru_male_adult_02"


# ---------------------------------------------------------------------------------------------
# The line cache
# ---------------------------------------------------------------------------------------------


class CountingTTS:
    """A tiny `TTSProvider`: one 20 ms frame of silence per character, counting its calls."""

    provider_name = "counting"
    model_version = "1"
    output_sample_rate = 16000

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    async def warm_up(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def stream(
        self, text: str, voice: TtsVoiceSpec, *, request_id: str, max_chunk_ms: int = 20
    ) -> Any:
        self.requests.append((voice.voice_id, text))
        provider = self

        class _Stream:
            request_id = "x"

            def __init__(self) -> None:
                self.text = text

            async def cancel(self) -> None:
                return None

            def __aiter__(self) -> AsyncIterator[TtsChunk]:
                return self._chunks()

            async def _chunks(self) -> AsyncIterator[TtsChunk]:
                samples = provider.output_sample_rate * 20 // 1000
                for index, _char in enumerate(text):
                    yield TtsChunk(
                        frame=AudioFrame(
                            pcm=b"\x00\x00" * samples,
                            sample_rate=provider.output_sample_rate,
                            num_channels=1,
                            samples_per_channel=samples,
                            capture_offset_ms=0,
                        ),
                        text_offset_start=index,
                        text_offset_end=index + 1,
                        alignment_is_exact=True,
                        chunk_index=index,
                        audio_ms=20,
                    )

        return _Stream()


async def _drain(stream: Any) -> list[TtsChunk]:
    return [chunk async for chunk in stream]


async def test_fixed_lines_are_synthesised_once_and_served_from_the_cache(tmp_path: Path) -> None:
    tts = CountingTTS()
    cache = TtsLineCache(tmp_path)
    voice = TtsVoiceSpec(voice_id="ru_male_adult_01", speaking_rate=1.0)
    lines = ResponderTemplates().static_lines(None)
    assert await cache.warm(tts, voice, lines) == len(lines)
    warmed = len(tts.requests)
    assert warmed == len(lines)
    assert (tmp_path / "ru_male_adult_01" / f"{line_key('Слушаю.')}.wav").is_file()

    cached = CachedTTSProvider(tts, cache)
    hit = await _drain(cached.stream(" Слушаю. ", voice, request_id="r1"))
    assert hit and len(tts.requests) == warmed  # served from memory, no synthesis
    assert sum(chunk.audio_ms for chunk in hit) == len("Слушаю.") * 20
    miss = await _drain(cached.stream("Наряд 2415.", voice, request_id="r2"))
    assert miss and tts.requests[-1] == ("ru_male_adult_01", "Наряд 2415.")
    other_voice = TtsVoiceSpec(voice_id="ru_male_adult_02", speaking_rate=1.0)
    await _drain(cached.stream("Слушаю.", other_voice, request_id="r3"))
    assert tts.requests[-1] == ("ru_male_adult_02", "Слушаю.")  # the cache is per voice

    # A restart reads the files back instead of synthesising again.
    again = CountingTTS()
    assert await TtsLineCache(tmp_path).warm(again, voice, lines) == len(lines)
    assert again.requests == []


async def test_a_line_that_fails_to_synthesise_is_only_a_miss(tmp_path: Path) -> None:
    class Broken(CountingTTS):
        def stream(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("no GPU")

    cache = TtsLineCache(tmp_path)
    voice = TtsVoiceSpec(voice_id="ru_male_adult_01", speaking_rate=1.0)
    assert await cache.warm(Broken(), voice, ["Слушаю."]) == 0
    assert cache.get("ru_male_adult_01", "Слушаю.") is None


async def test_the_agent_warms_every_persona_voice(tmp_path: Path) -> None:
    from voice_agent.tts_cache import CACHE_DIR_NAME

    agent = VoiceAgent(deps(), redis=None)
    agent._line_cache = TtsLineCache(tmp_path / CACHE_DIR_NAME)
    tts = CountingTTS()
    agent._tts = tts  # type: ignore[assignment]
    cached = await agent.warm_line_cache()
    voices = {voice for voice, _text in tts.requests}
    assert voices == {"ru_male_adult_01", "ru_male_adult_02", "ru_female_adult_01"}
    assert cached == len(tts.requests)
    assert ("ru_male_adult_01", "Начальник караула, слушаю.") in tts.requests
