"""`VoiceAgent._warm_caller_lines` — the caller's §7.8 fallback lines, per voice, at warm-up
(I8 V4).

`test_service_head_in_agent.py::test_the_agent_warms_every_persona_voice` already proves the gate
settings (`SIM_TTS_PROVIDER=fake`, empty `tts_voice_map`) never trigger this path — that test's
own exact-set assertion on `tts.requests` would break the moment it did. This file exercises the
path directly, with the settings a Qwen profile actually carries.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.application.ports.call_transport import AudioFrame
from app.application.ports.tts import TtsChunk, TtsVoiceSpec
from app.application.testing.fakes import FakeClock
from app.config.settings import Settings
from voice_agent.main import VoiceAgent
from voice_agent.tts_cache import CACHE_DIR_NAME, TtsLineCache
from voice_agent.wiring import VoiceAgentDeps

VOICE_MAP = {"ru_female_adult_01": "serena", "ru_male_adult_01": "eric"}


class CountingTTS:
    """A fast, unseeded `TTSProvider`: every clip's rate passes I8 A1 §2.2's band by construction
    (60 ms/char), so the QC hook always succeeds on the first attempt — this file is about which
    lines get warmed, not about the retry loop (`test_tts_cache.py` owns that)."""

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
        rate = self.output_sample_rate
        audio_ms = max(1, int(60.0 * len(text)))
        samples = max(1, rate * audio_ms // 1000)
        pcm = b"\x00\x00" * samples

        class _Stream:
            def __aiter__(self) -> AsyncIterator[TtsChunk]:
                return self._chunks()

            async def _chunks(self) -> AsyncIterator[TtsChunk]:
                yield TtsChunk(
                    frame=AudioFrame(
                        pcm=pcm,
                        sample_rate=rate,
                        num_channels=1,
                        samples_per_channel=samples,
                        capture_offset_ms=0,
                    ),
                    text_offset_start=0,
                    text_offset_end=len(text),
                    alignment_is_exact=True,
                    chunk_index=0,
                    audio_ms=audio_ms,
                )

        return _Stream()


def deps(
    *,
    tts_provider: str = "fake",
    tts_voice_map: dict[str, str] | None = None,
    tts_warm_caller_lines: bool | None = None,
    tts_warm_caller_lines_budget_s: int = 600,
) -> VoiceAgentDeps:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        redis_url="redis://localhost:56379/0",
        jwt_secret="test-only-secret-padded-32-bytes!",
        livekit_url="ws://localhost:7880",
        livekit_api_key="devkey",
        livekit_api_secret="devsecret1234567890",
        llm_base_url="http://localhost:8080/v1",
        tts_provider=tts_provider,
        tts_voice_map=tts_voice_map or {},
        tts_warm_caller_lines=tts_warm_caller_lines,
        tts_warm_caller_lines_budget_s=tts_warm_caller_lines_budget_s,
    )
    return VoiceAgentDeps.build(settings, FakeClock(), lambda: None)  # type: ignore[arg-type,return-value]


def _agent(tmp_path: Path, tts: CountingTTS, **deps_kwargs: Any) -> VoiceAgent:
    agent = VoiceAgent(deps(**deps_kwargs), redis=None)
    agent._line_cache = TtsLineCache(tmp_path / CACHE_DIR_NAME)
    agent._tts = tts  # type: ignore[assignment]
    return agent


# -- enablement -------------------------------------------------------------------------------


def test_disabled_by_default_for_the_fake_provider(tmp_path: Path) -> None:
    tts = CountingTTS()
    agent = _agent(tmp_path, tts, tts_provider="fake", tts_voice_map=VOICE_MAP)
    assert agent._warm_caller_lines_enabled(agent._deps.settings) is False


def test_enabled_by_default_for_qwen3_tts(tmp_path: Path) -> None:
    tts = CountingTTS()
    agent = _agent(tmp_path, tts, tts_provider="qwen3_tts", tts_voice_map=VOICE_MAP)
    assert agent._warm_caller_lines_enabled(agent._deps.settings) is True


def test_an_explicit_setting_always_wins(tmp_path: Path) -> None:
    tts = CountingTTS()
    off = _agent(tmp_path, tts, tts_provider="qwen3_tts", tts_warm_caller_lines=False)
    assert off._warm_caller_lines_enabled(off._deps.settings) is False
    on = _agent(tmp_path, tts, tts_provider="fake", tts_warm_caller_lines=True)
    assert on._warm_caller_lines_enabled(on._deps.settings) is True


# -- warming itself -----------------------------------------------------------------------------


async def test_it_warms_every_voice_map_voice_with_gender_matched_lines(tmp_path: Path) -> None:
    tts = CountingTTS()
    agent = _agent(tmp_path, tts, tts_provider="qwen3_tts", tts_voice_map=VOICE_MAP)

    cached = await agent._warm_caller_lines()

    voices = {voice for voice, _text in tts.requests}
    assert voices == set(VOICE_MAP)
    assert cached == len(tts.requests)
    # Row 1's gendered verb, matched to each voice's logical gender:
    assert ("ru_female_adult_01", "Простите, я не расслышала, повторите, пожалуйста.") in (
        tts.requests
    )
    assert ("ru_male_adult_01", "Простите, я не расслышал, повторите, пожалуйста.") in tts.requests
    # Row 2 (ALLOWED_FACTS) is not a fixed line and is never pre-synthesised:
    assert not any("{labels_and_values}" in text for _voice, text in tts.requests)


async def test_it_does_nothing_when_disabled(tmp_path: Path) -> None:
    tts = CountingTTS()
    agent = _agent(tmp_path, tts, tts_provider="fake", tts_voice_map=VOICE_MAP)
    assert await agent._warm_caller_lines() == 0
    assert tts.requests == []


async def test_it_does_nothing_with_an_empty_voice_map(tmp_path: Path) -> None:
    tts = CountingTTS()
    agent = _agent(tmp_path, tts, tts_provider="qwen3_tts", tts_voice_map={})
    assert await agent._warm_caller_lines() == 0
    assert tts.requests == []


async def test_a_spent_budget_stops_warm_up_and_leaves_the_rest_a_miss(tmp_path: Path) -> None:
    tts = CountingTTS()
    agent = _agent(
        tmp_path,
        tts,
        tts_provider="qwen3_tts",
        tts_voice_map=VOICE_MAP,
        tts_warm_caller_lines_budget_s=0,
    )
    # The budget is already spent the instant warm-up starts (0 s), so nothing is even attempted.
    cached = await agent._warm_caller_lines()
    assert cached == 0
    assert tts.requests == []


async def test_warm_line_cache_calls_the_caller_line_pass_too(tmp_path: Path) -> None:
    """The end-to-end hook from `warm_line_cache()` (persona lines, then caller lines)."""
    tts = CountingTTS()
    agent = _agent(tmp_path, tts, tts_provider="qwen3_tts", tts_voice_map=VOICE_MAP)
    cached = await agent.warm_line_cache()
    voices = {voice for voice, _text in tts.requests}
    # Persona voices (from the reference pack, none of which overlap VOICE_MAP's ids here) plus
    # the two caller voices `_warm_caller_lines` adds.
    assert VOICE_MAP.keys() <= voices
    assert cached == len(tts.requests)
