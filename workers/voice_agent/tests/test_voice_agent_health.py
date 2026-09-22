"""The voice-agent process's health publication: FATAL, the latch, the re-warm (E18-C).

`test_voice_agent_process.py` covers the happy warm-up and the heartbeat key; this module covers
what HLD 60 §4.1/§4.3/§4.4 add on top — the un-expiring `voice:health:fatal` mirror, the
`voice:health` pub/sub announcement the backend turns into `INFERENCE_HEALTH_CHANGED`, the periodic
re-warm, and the rule that FATAL is never retried.

Everything runs against a fake Redis and fake providers: no server, no socket, no model (D13).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.application.testing.fakes import FakeClock
from app.config.profile import ProfileRefused
from app.config.settings import Settings
from voice_agent.health import STATE_FATAL, STATE_NOT_READY, STATE_READY, STATE_WARMING
from voice_agent.main import (
    ASR_SERVICE,
    HEALTH_CHANNEL,
    HEALTH_FATAL_KEY,
    LLM_SERVICE,
    TTS_SERVICE,
    VAD_SERVICE,
    VoiceAgent,
)
from voice_agent.wiring import VoiceAgentDeps


def settings(**overrides: Any) -> Settings:
    """The gate's selection (D13): fake VAD/ASR/LLM/TTS, so nothing here loads a model.

    Deliberately a local copy of `test_voice_agent_process.settings` rather than an import of it:
    `workers/voice_agent/tests` is not a package, so a cross-module import here would depend on
    pytest's sys.path insertion order rather than on anything this suite controls.
    """
    base: dict[str, Any] = {
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


class FakeRedis:
    """Just enough Redis for the heartbeat, the FATAL latch and the transition announcements."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}
        self.deleted: list[str] = []
        self.published: list[tuple[str, str]] = []
        #: Keys written with no `ex=` — `voice:health:fatal` must be one of them.
        self.unexpiring: list[str] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if ex is None:
            self.unexpiring.append(key)
        else:
            self.expiries[key] = ex
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.deleted.append(key)

    async def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))


def make_agent(clock: FakeClock, redis: FakeRedis, **kwargs: Any) -> VoiceAgent:
    overrides = {k: v for k, v in kwargs.items() if k not in _AGENT_KWARGS}
    agent_kwargs = {k: v for k, v in kwargs.items() if k in _AGENT_KWARGS}
    deps = VoiceAgentDeps.build(settings(**overrides), clock, lambda: None)  # type: ignore[arg-type,return-value]
    return VoiceAgent(deps, redis, **agent_kwargs)


_AGENT_KWARGS = {"failure_threshold", "rewarm_interval_s", "preflight_http", "transport_factory"}


def _transitions(redis: FakeRedis) -> list[dict[str, Any]]:
    return [
        json.loads(message) for channel, message in redis.published if channel == HEALTH_CHANNEL
    ]


# -- §4.3: every transition is announced -------------------------------------------------------


async def test_every_warm_up_transition_is_announced_on_the_pubsub_channel() -> None:
    """§4.3: "Every transition is also published on the pub/sub channel `voice:health`"."""
    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis)
    await agent.warm_up()

    announced = _transitions(redis)
    assert {t["service"] for t in announced} == {VAD_SERVICE, ASR_SERVICE, LLM_SERVICE, TTS_SERVICE}
    # Each service goes NOT_READY -> WARMING -> READY, and both steps are announced.
    vad = [t for t in announced if t["service"] == VAD_SERVICE]
    assert [(t["from"], t["to"]) for t in vad] == [
        (STATE_NOT_READY, STATE_WARMING),
        (STATE_WARMING, STATE_READY),
    ]
    assert all(set(t) == {"service", "from", "to", "detail", "at"} for t in announced)


async def test_a_clean_warm_up_clears_a_stale_fatal_latch() -> None:
    """§4.3: the latch is cleared by `clearInferenceFatal` "or by a clean warm-up after a manual
    restart" — otherwise a fixed machine would refuse every session for ever."""
    redis = FakeRedis()
    await redis.set(HEALTH_FATAL_KEY, json.dumps({"service": "tts"}))
    agent = make_agent(FakeClock(), redis)
    await agent.warm_up()
    assert agent.states.all_ready is True
    assert HEALTH_FATAL_KEY not in redis.values


# -- §4.4: FATAL, latched and terminal ---------------------------------------------------------


async def _make_fatal(agent: VoiceAgent, service: str = TTS_SERVICE) -> None:
    from app.inference.errors import InferenceOutOfMemoryError

    async def _boom() -> None:
        raise InferenceOutOfMemoryError("CUDA out of memory")

    stage = {"vad": "VAD", "asr": "ASR", "llm": "LLM", "tts": "TTS"}[service]
    with pytest.raises(InferenceOutOfMemoryError):
        await agent.guard.run(stage, _boom)


async def test_an_oom_latches_voice_health_fatal_without_an_expiry() -> None:
    """§4.4 + §4.3: FATAL is mirrored to `voice:health:fatal`, **no expiry**, naming the service."""
    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis)
    await agent.warm_up()
    await _make_fatal(agent)

    assert agent.health_state(TTS_SERVICE) == STATE_FATAL
    assert HEALTH_FATAL_KEY in redis.values
    assert HEALTH_FATAL_KEY in redis.unexpiring
    assert HEALTH_FATAL_KEY not in redis.expiries
    latch = json.loads(redis.values[HEALTH_FATAL_KEY])
    # The backend (`app.infrastructure.health.voice_health`) reads `service` to decide which
    # component the latch covers.
    assert latch["service"] == TTS_SERVICE
    assert latch["state"] == STATE_FATAL
    # The per-service heartbeat key agrees with the latch.
    assert json.loads(redis.values[f"voice:health:{TTS_SERVICE}"])["state"] == STATE_FATAL
    assert _transitions(redis)[-1]["to"] == STATE_FATAL


async def test_a_graceful_shutdown_clears_the_heartbeats_but_never_the_fatal_latch() -> None:
    """A fatal condition that vanished on restart is exactly what the latch exists to prevent."""
    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis)
    await agent.warm_up()
    # The clean warm-up above legitimately cleared a (non-existent) stale latch; from here on the
    # latch is real, and shutdown must not touch it.
    redis.deleted.clear()
    await _make_fatal(agent)
    await agent.clear_health()
    assert HEALTH_FATAL_KEY in redis.values
    assert HEALTH_FATAL_KEY not in redis.deleted
    assert sorted(redis.deleted) == [f"voice:health:{s}" for s in ("asr", "llm", "tts", "vad")]


async def test_fatal_is_never_re_warmed() -> None:
    """§4.1 row 8: "only a process restart leaves FATAL" — the re-warm loop must skip it."""
    redis = FakeRedis()
    clock = FakeClock()
    agent = make_agent(clock, redis, rewarm_interval_s=1)
    await agent.warm_up()
    await _make_fatal(agent, TTS_SERVICE)
    before = len(_transitions(redis))

    clock.advance_ms(60_000)
    await agent._rewarm()

    assert agent.health_state(TTS_SERVICE) == STATE_FATAL
    assert len(_transitions(redis)) == before  # nothing happened at all


async def test_a_not_ready_service_is_re_warmed_after_the_interval() -> None:
    """§4.1 row 7: NOT_READY → WARMING on the periodic re-warm, and only once it is due."""
    redis = FakeRedis()
    clock = FakeClock()
    agent = make_agent(clock, redis, rewarm_interval_s=30)
    await agent.warm_up()
    # Demote `asr` the way three consecutive runtime failures would.
    transition = agent.states[ASR_SERVICE].warm_failed(
        recoverable=True, detail="worker down", now_s=clock.monotonic_ms() / 1000
    )
    assert transition is not None

    clock.advance_ms(29_000)
    await agent._rewarm()
    assert agent.health_state(ASR_SERVICE) == STATE_NOT_READY

    clock.advance_ms(2_000)
    await agent._rewarm()
    assert agent.health_state(ASR_SERVICE) == STATE_READY
    assert [t["to"] for t in _transitions(redis)][-2:] == [STATE_WARMING, STATE_READY]


async def test_an_unrecoverable_warm_up_failure_goes_fatal_not_not_ready() -> None:
    """§4.1 row 4: a missing model file is not something a re-warm every 30 s can fix."""
    from app.inference.errors import ModelNotAvailableError

    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis)

    async def _missing() -> tuple[str, str | None]:
        raise ModelNotAvailableError("models/gigaam-v3-e2e_ctc is missing; run `make models-asr`")

    await agent._warm_component(ASR_SERVICE, _missing)
    assert agent.health_state(ASR_SERVICE) == STATE_FATAL
    assert HEALTH_FATAL_KEY in redis.values
    assert json.loads(redis.values[HEALTH_FATAL_KEY])["service"] == ASR_SERVICE


async def test_a_recoverable_warm_up_failure_keeps_heartbeating_not_ready() -> None:
    """A failed warm-up is not a failed process (the existing rule), now with a re-warm clock."""
    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis)

    async def _timeout() -> tuple[str, str | None]:
        raise TimeoutError("llama-server did not answer /models in time")

    await agent._warm_component(LLM_SERVICE, _timeout)
    assert agent.health_state(LLM_SERVICE) == STATE_NOT_READY
    assert HEALTH_FATAL_KEY not in redis.values
    payload = json.loads(redis.values[f"voice:health:{LLM_SERVICE}"])
    assert payload["state"] == STATE_NOT_READY
    assert "TimeoutError" in payload["detail"]


# -- the preflight probes read the *loaded* providers -------------------------------------------


async def test_the_preflight_probes_answer_from_the_warmed_providers() -> None:
    """§5 checks 5-6: they transcribe and synthesise with what this process already holds."""
    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis)
    await agent.warm_up()

    asr = await agent._probe_asr()
    assert set(asr) == {"text", "latency_ms", "provider", "model_version"}
    assert asr["latency_ms"] >= 0

    tts = await agent._probe_tts()
    assert tts["output_audio_ms"] > 0
    assert tts["provider"]


async def test_the_preflight_probes_refuse_before_a_warm_up_rather_than_loading() -> None:
    """A preflight must never be the thing that puts a model on the card it is checking."""
    agent = make_agent(FakeClock(), FakeRedis())
    for probe in (agent._probe_asr, agent._probe_tts):
        with pytest.raises(RuntimeError, match="never warmed"):
            await probe()


async def test_the_agent_binds_no_socket_unless_the_process_asks_for_one() -> None:
    """Every test in this package builds an agent; none of them may open a listening port."""
    assert make_agent(FakeClock(), FakeRedis())._preflight is None
    assert make_agent(FakeClock(), FakeRedis(), preflight_http=True)._preflight is not None


# -- start-up: a refused profile exits non-zero, before any I/O ---------------------------------


async def test_a_refused_profile_stops_the_process_before_redis_is_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1: `ProfileRefused` is fatal at voice-agent start-up, and no env var disables it.

    Asserted where it matters: the refusal must land *before* `Redis.from_url` and
    `create_async_engine`, so a process that will not run never advertises itself as warming up.
    """
    import redis.asyncio as redis_asyncio
    import sqlalchemy.ext.asyncio as sqlalchemy_asyncio
    from voice_agent import main as main_module

    touched: list[str] = []
    monkeypatch.setattr(
        redis_asyncio.Redis,
        "from_url",
        classmethod(lambda cls, *a, **k: touched.append("redis")),
    )
    monkeypatch.setattr(
        sqlalchemy_asyncio,
        "create_async_engine",
        lambda *a, **k: touched.append("engine"),
    )

    refused = settings(model_profile="NO_SUCH_PROFILE")
    with pytest.raises(ProfileRefused, match="NO_SUCH_PROFILE"):
        await main_module.run(refused)
    assert touched == []


async def test_the_real_entry_point_is_the_profile_aware_one() -> None:
    """`VoiceAgentDeps.build_for_startup` (E18-A) is what `run()` calls — `build` would skip
    `validate_vram_margin` and the whole profile overlay."""
    import inspect

    from voice_agent import main as main_module

    source = inspect.getsource(main_module.run)
    assert "VoiceAgentDeps.build_for_startup(" in source
    assert "VoiceAgentDeps.build(" not in source


def test_the_health_wire_vocabulary_matches_the_backend_reader() -> None:
    """One spelling, two processes: the writer's constants are the reader's (R4)."""
    from app.infrastructure.health.voice_health import (
        VOICE_HEALTH_CHANNEL,
        VOICE_HEALTH_FATAL_KEY,
    )

    assert HEALTH_CHANNEL == VOICE_HEALTH_CHANNEL
    assert HEALTH_FATAL_KEY == VOICE_HEALTH_FATAL_KEY


def test_the_settings_for_this_suite_are_the_gate_s_fakes() -> None:
    """Guards the whole module: if `settings()` ever selected a real provider these tests would
    try to load a model."""
    resolved: Settings = settings()
    assert (resolved.asr_provider, resolved.llm_provider, resolved.tts_provider) == (
        "fake",
        "fake",
        "fake",
    )


# -- E20-G/G5: the CONFIGURED TTS FALLBACK is warmed beside the primary -------------------------
#
# E20-C's §46 walk: the fallback provider was never warmed, so INV 14's "retry the whole utterance
# once on the fallback" could only ever fail — `RuntimeError: PiperTTS.warm_up() must be called
# before stream()`, surfacing to the trainee's timeline as a misleading
# `MODEL_ERROR{"error_code": "TIMEOUT"}` and to the trainee as a silent caller.


class _RecordingFallback:
    """A `TTSProvider` that only records whether it was warmed (D13 — no model anywhere)."""

    provider_name = "recording-fallback"
    model_version = "v0"
    output_sample_rate = 24000

    def __init__(self, *, fail: bool = False) -> None:
        self.warm_ups = 0
        self._fail = fail

    async def warm_up(self) -> None:
        self.warm_ups += 1
        if self._fail:
            raise RuntimeError("piper voice file missing")

    def stream(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - never reached here
        raise AssertionError("the fallback is not asked to speak in this test")

    async def close(self) -> None:
        return None


def _patch_fallback(monkeypatch: pytest.MonkeyPatch, fallback: _RecordingFallback | None) -> None:
    import voice_agent.main as main_module

    monkeypatch.setattr(main_module, "build_tts_fallback", lambda _settings: fallback)


async def test_warm_up_also_warms_the_configured_tts_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = _RecordingFallback()
    _patch_fallback(monkeypatch, fallback)
    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis)

    await agent.warm_up()

    assert fallback.warm_ups == 1
    assert agent.health_state(TTS_SERVICE) == STATE_READY
    assert agent._tts_fallback is fallback


async def test_a_fallback_warm_up_failure_is_one_warning_and_never_fatal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A primary that works is still a working caller: the process must stay READY."""
    fallback = _RecordingFallback(fail=True)
    _patch_fallback(monkeypatch, fallback)
    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis, rewarm_interval_s=1)

    with caplog.at_level("WARNING", logger="voice_agent.main"):
        await agent.warm_up()
        # A re-warm must not repeat the warning: once per process, not once per cycle.
        await agent._warm_component(TTS_SERVICE, agent._warm_tts)

    assert agent.health_state(TTS_SERVICE) == STATE_READY
    assert agent._tts_fallback is None
    warnings = [r for r in caplog.records if "fallback" in r.getMessage()]
    assert len(warnings) == 1
    assert fallback.warm_ups == 2  # it was retried, it just stayed unavailable

    frame = json.loads(redis.values[f"voice:health:{TTS_SERVICE}"])
    assert frame["state"] == STATE_READY
    assert "fallback unavailable" in frame["detail"]


async def test_no_configured_fallback_is_not_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`SIM_TTS_FALLBACK_PROVIDER=none` is the gate's own selection, not a degraded state."""
    _patch_fallback(monkeypatch, None)
    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis)

    with caplog.at_level("WARNING", logger="voice_agent.main"):
        await agent.warm_up()

    assert agent.health_state(TTS_SERVICE) == STATE_READY
    assert agent._tts_fallback is None
    assert [r for r in caplog.records if "fallback" in r.getMessage()] == []
    assert json.loads(redis.values[f"voice:health:{TTS_SERVICE}"])["detail"] is None
