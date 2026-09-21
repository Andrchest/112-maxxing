"""The voice-agent process: wiring, the SIP stub, the join subscription and the heartbeat.

Everything here runs against fakes (ruling 1): no LiveKit, no Redis server, no GPU. The parts
that need a real server are in `test_livekit_contract.py` behind `requires_livekit`.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from app.application.testing.fakes import (
    FakeCallTransport,
    FakeClock,
    silence_frames,
    sine_burst_frames,
)
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.turn_pipeline import NullTurnResponder, TurnPipeline
from app.config.settings import Settings
from app.domain.common.ids import SessionId
from voice_agent.main import (
    ASR_SERVICE,
    STATE_NOT_READY,
    STATE_READY,
    VAD_SERVICE,
    VoiceAgent,
    synthetic_tone,
)
from voice_agent.transport.sip_transport import SIP_STUB_MESSAGE, SipCallTransport
from voice_agent.wiring import VoiceAgentDeps, build_pipeline, build_transport, build_vad

CALL_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")


class _CollectingUnitOfWork:
    """The two repositories the appender uses, over one list. No database, no transaction."""

    def __init__(self, committed: list[Any], clock: FakeClock) -> None:
        self._committed = committed
        self._clock = clock
        self._pending: list[Any] = []

    @property
    def events(self) -> Any:
        return self

    @property
    def audio_segments(self) -> Any:
        return self

    @property
    def transcript_segments(self) -> Any:
        return self

    @property
    def dialogue_turns(self) -> Any:
        return self

    @property
    def inference_metrics(self) -> Any:
        return self

    @property
    def sessions(self) -> Any:
        return self

    async def append(self, session_id: SessionId, events: Any) -> list[Any]:
        self._pending.extend(events)
        return list(events)

    async def add_all(self, segments: Any) -> None:
        return None

    async def add(self, row: Any) -> None:
        return None

    async def upsert(self, row: Any) -> Any:
        return row.id

    async def get(self, *args: Any, **kwargs: Any) -> None:
        """No session aggregate here: the stage resolver and the policy read both answer `None`.

        That is the honest answer for a process test with no database — the `dialogue_turns` row
        is skipped and partials stay off — and it keeps this test about the task graph.
        """
        return None

    async def __aenter__(self) -> _CollectingUnitOfWork:
        self._pending = []
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def commit(self) -> None:
        self._committed.extend(self._pending)

    async def rollback(self) -> None:
        self._pending = []


def _collecting_uow_factory(committed: list[Any], clock: FakeClock) -> Any:
    def factory() -> _CollectingUnitOfWork:
        return _CollectingUnitOfWork(committed, clock)

    return factory


def settings(**overrides: Any) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        "redis_url": "redis://localhost:56379/0",
        "jwt_secret": "test-only-secret",
        "livekit_url": "ws://localhost:7880",
        "livekit_api_key": "devkey",
        "livekit_api_secret": "devsecret1234567890",
        "llm_base_url": "http://localhost:8080/v1",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# -- the SIP stub ------------------------------------------------------------------------------


async def test_the_sip_transport_is_a_documented_refusal() -> None:
    """§2.1: the second implementation is a file, not a refactor — and it never pretends."""
    transport = SipCallTransport()
    assert SIP_STUB_MESSAGE == "SIP transport is a documented stub; see SPEC §15"
    with pytest.raises(NotImplementedError, match="documented stub"):
        await transport.connect(CALL_ID)
    for call in (transport.inbound_audio, transport.events):
        with pytest.raises(NotImplementedError, match="documented stub"):
            call()
    with pytest.raises(NotImplementedError, match="documented stub"):
        await transport.clear_outbound()
    with pytest.raises(NotImplementedError, match="documented stub"):
        await transport.disconnect()


# -- wiring ------------------------------------------------------------------------------------


def test_the_vad_window_follows_the_turn_config() -> None:
    """The provider and the config must agree frame for frame (§2.2, §4.1)."""
    config = VoiceTurnConfig()
    vad = build_vad(settings(), config)
    assert vad.frame_samples == config.frame_samples
    assert vad.required_sample_rate == config.sample_rate
    assert vad.provider_name == "energy"


def test_the_fake_transport_is_not_a_deployment_option() -> None:
    """D13: the fake is the gate's, and a deployment selects a real transport."""
    with pytest.raises(ValueError, match="SIM_CALL_TRANSPORT"):
        build_transport(settings(call_transport="fake"), VoiceTurnConfig())


def test_the_livekit_transport_needs_a_backend_minted_token() -> None:
    """D9: the agent never mints its own token; the backend's `createVoiceToken` does."""
    with pytest.raises(ValueError, match="token"):
        build_transport(settings(call_transport="livekit"), VoiceTurnConfig())


def test_the_sip_transport_can_be_selected_and_then_refuses() -> None:
    """Selecting it is legal; using it is not (SPEC §15: no PSTN for the demo)."""
    assert isinstance(
        build_transport(settings(call_transport="sip"), VoiceTurnConfig()), SipCallTransport
    )


def test_the_turn_config_comes_from_settings_not_from_the_agent() -> None:
    """SPEC §17: configuration, never a literal in the process."""
    deps = VoiceAgentDeps.build(
        settings(voice_endpoint_silence_ms=256, voice_pre_roll_ms=512),
        FakeClock(),
        lambda: None,  # type: ignore[arg-type,return-value]
    )
    assert deps.config.endpoint_silence_ms == 256
    assert deps.config.pre_roll_ms == 512


# -- the process -------------------------------------------------------------------------------


class FakeRedis:
    """Just enough Redis for the heartbeat and the join subscription."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}
        self.deleted: list[str] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        if ex is not None:
            self.expiries[key] = ex

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.deleted.append(key)


def make_agent(clock: FakeClock, redis: FakeRedis, **overrides: Any) -> VoiceAgent:
    deps = VoiceAgentDeps.build(settings(**overrides), clock, lambda: None)  # type: ignore[arg-type,return-value]
    return VoiceAgent(deps, redis)


async def test_the_heartbeat_key_is_the_documented_one_with_the_documented_ttl() -> None:
    """`60-inference-ops.md` §4.3: `voice:health:{service}`, `SET … EX`, heartbeat every 5 s."""
    clock = FakeClock()
    redis = FakeRedis()
    agent = make_agent(clock, redis)

    await agent.warm_up()
    await agent.publish_health()

    assert agent.health_key() == "voice:health:vad"
    assert set(redis.values) == {"voice:health:vad", "voice:health:asr"}
    assert redis.expiries["voice:health:vad"] == agent._deps.settings.voice_health_ttl_s == 15
    assert agent._deps.settings.voice_health_heartbeat_s == 5
    payload = json.loads(redis.values["voice:health:vad"])
    assert payload["state"] == STATE_READY
    assert payload["provider"] == "energy"
    asr_payload = json.loads(redis.values["voice:health:asr"])
    assert asr_payload["state"] == STATE_READY
    assert asr_payload["provider"] == "fake"
    assert asr_payload["model_version"] == "fake-1"


async def test_a_component_is_not_ready_until_it_has_been_warmed_up() -> None:
    """§4.1's `HealthStatus`: NOT_READY is the state of a process that has not warmed up yet."""
    agent = make_agent(FakeClock(), FakeRedis())
    assert agent.health_state(VAD_SERVICE) == STATE_NOT_READY
    assert agent.health_state(ASR_SERVICE) == STATE_NOT_READY

    await agent.warm_up()

    assert agent.health_state(VAD_SERVICE) == STATE_READY
    assert agent.health_state(ASR_SERVICE) == STATE_READY


async def test_a_failing_warm_up_leaves_the_component_not_ready_without_killing_the_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken ASR must not take the VAD — or the process — down with it (§4.1)."""
    import voice_agent.main as main_module

    def explode(_settings: Any) -> Any:
        raise RuntimeError("no weights on this machine")

    monkeypatch.setattr(main_module, "build_asr", explode)
    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis)

    await agent.warm_up()

    assert agent.health_state(VAD_SERVICE) == STATE_READY
    assert agent.health_state(ASR_SERVICE) == STATE_NOT_READY
    payload = json.loads(redis.values["voice:health:asr"])
    assert payload["state"] == STATE_NOT_READY
    assert "no weights on this machine" in payload["detail"]


async def test_the_warm_up_transcribes_a_second_of_audio_rather_than_silence() -> None:
    """§4.2 step 2: the ASR warm-up runs a real recognition, not an empty buffer."""
    agent = make_agent(FakeClock(), FakeRedis())
    await agent.warm_up()

    asr = agent._asr
    assert asr is not None
    assert [call.request_id for call in asr.calls] == ["warmup:asr"]  # type: ignore[attr-defined]
    expected_bytes = len(synthetic_tone(asr.required_sample_rate))
    assert asr.calls[0].audio_bytes == expected_bytes  # type: ignore[attr-defined]
    assert expected_bytes == asr.required_sample_rate * 2, "one second of mono s16le"
    assert set(synthetic_tone(asr.required_sample_rate)) != {0}, "the tone is not silence"


async def test_clearing_the_health_keys_is_part_of_a_graceful_shutdown() -> None:
    """A stopped agent must read NOT_READY at once, not after the TTL (the `ring` guard, §10.8)."""
    redis = FakeRedis()
    agent = make_agent(FakeClock(), redis)
    await agent.publish_health()

    await agent.clear_health()

    assert redis.values == {}
    assert sorted(redis.deleted) == ["voice:health:asr", "voice:health:vad"]


async def test_a_repeated_voice_join_does_not_start_a_second_pipeline() -> None:
    """§40.6: `voice:join` is re-published every `VOICE_JOIN_RETRY_MS` while RINGING."""
    clock = FakeClock()
    agent = make_agent(clock, FakeRedis())
    session_id = uuid.uuid4()
    payload = json.dumps({"session_id": str(session_id), "room": "call-1", "call_id": str(CALL_ID)})
    started: list[uuid.UUID] = []

    async def never_ending(
        _session: SessionId, _call: uuid.UUID, _room: str
    ) -> None:  # pragma: no cover - replaced below
        raise AssertionError

    async def fake_run_call(session_id: SessionId, call_id: uuid.UUID, room: str) -> None:
        started.append(call_id)
        await asyncio.sleep(3600)

    agent._run_call = fake_run_call  # type: ignore[method-assign]
    try:
        await agent._on_join(payload)
        await agent._on_join(payload)
        await asyncio.sleep(0)
        assert len(agent.active_sessions) == 1
        assert started == [CALL_ID]
    finally:
        await agent._drain_calls()


@pytest.mark.parametrize("raw", ["not json", "{}", '{"session_id": "nope"}'])
async def test_a_malformed_voice_join_is_ignored_not_fatal(raw: str) -> None:
    """A bad signal costs liveness, never correctness (§40.6)."""
    agent = make_agent(FakeClock(), FakeRedis())
    await agent._on_join(raw)
    assert agent.active_sessions == ()


async def test_the_whole_agent_path_runs_against_the_fake_transport() -> None:
    """Ruling 1: the E11 slice is built and gate-tested against fakes, end to end.

    This is the wiring proof the unit tests cannot give: a `TurnPipeline` built by `build_pipeline`
    exactly as the process builds it, driven by scripted audio through `FakeCallTransport`, with a
    Unit of Work that is a dictionary. Same `_ingest` / `_respond` / `_control` graph, no LiveKit,
    no PostgreSQL, no model.
    """
    config = VoiceTurnConfig()
    clock = FakeClock()
    committed: list[Any] = []
    frames = [
        *silence_frames(
            duration_ms=400, frame_samples=config.frame_samples, sample_rate=config.sample_rate
        ),
        *sine_burst_frames(
            duration_ms=900,
            frame_samples=config.frame_samples,
            sample_rate=config.sample_rate,
            start_offset_ms=400,
        ),
        *silence_frames(
            duration_ms=900,
            frame_samples=config.frame_samples,
            sample_rate=config.sample_rate,
            start_offset_ms=1300,
        ),
    ]
    transport = FakeCallTransport(
        clock=clock, inbound=frames, outbound_queue_ms=config.outbound_queue_ms
    )
    deps = VoiceAgentDeps.build(settings(), clock, _collecting_uow_factory(committed, clock))
    session_id = SessionId(uuid.uuid4())

    await transport.connect(CALL_ID)
    pipeline = build_pipeline(
        deps,
        session_id=session_id,
        call_id=CALL_ID,
        transport=transport,
        started_at=clock.now(),
        record=False,
    )
    assert isinstance(pipeline, TurnPipeline)

    await asyncio.wait_for(pipeline.run(), timeout=10)

    # E12 added the ASR stage to this exact path: the same three tasks, now with a real
    # `AsrTurnResponder` over `FakeASR` (`SIM_ASR_PROVIDER=fake`, D13). The session aggregate is
    # unreadable here, so the policy denies partials and the `dialogue_turns` row is skipped —
    # the `ASR_FINAL` is not, because the event log is the audit source (D5).
    assert [event.event_type.value for event in committed] == [
        "USER_SPEECH_STARTED",
        "USER_SPEECH_ENDED",
        "ASR_FINAL",
        "CALL_ENDED",
    ]
    assert transport.call_id == CALL_ID


def test_the_default_responder_is_the_null_one() -> None:
    """E11 ships no dialogue; a stub that invented one would be a silently unmet requirement."""
    responder = NullTurnResponder()
    assert responder.responded == []


def test_the_fake_transport_is_reachable_from_the_worker_package() -> None:
    """`voice_agent.transport.fake` re-exports the one fake, so dev mode needs no second one."""
    from voice_agent.transport.fake import FakeCallTransport as Reexported

    assert Reexported is FakeCallTransport
