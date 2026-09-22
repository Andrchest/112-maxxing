"""SPEC §39 #2 — "TTS failure: log failure and use configured fallback." (`docs/SPEC.md:1032-1033`).

The mechanism (HLD `60-inference-ops.md` §6, D9) already exists end-to-end in
`TtsSpeechSink.speak()` (E14): a failing provider logs `MODEL_ERROR{stage:"TTS"}`, the configured
`fallback_provider` gets one retry of the *whole* utterance announced by `MODEL_FALLBACK_USED`,
and — the case SPEC §39 does not spell out but `60-inference-ops.md` does — a fallback that also
fails still ends the turn silently rather than raising. `test_inv_14_tts_failure_keeps_session.py`
already proves this mechanism in depth; this module drives the same public seam (`TtsSpeechSink`)
once, end-to-end, for exactly SPEC §39's own wording, and closes on "never silently reset":
nothing an earlier turn wrote is dropped or rewritten by a later one, whichever way it went.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from app.application.dialogue.speech_sink import PlannedCallerUtterance
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.tts_speech_sink import TtsSpeechSink
from app.application.voice.turn_pipeline import TurnContext
from app.domain.caller.emotion import EmotionLabel, EmotionState
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.inference.tts.fake_tts import FakeTTS

from tests.resilience.conftest import assert_prefix_preserved
from tests.unit.application.voice.conftest import InMemoryVoiceUnitOfWork, VoiceStore, uow_factory

CALL_ID = uuid.UUID("39292929-3929-4929-8929-392929292929")
TEXT_RU = "Алло, диспетчер слушает."
FACTS = ("incident.address",)
EMOTION = EmotionState(emotion=EmotionLabel.PANICKED, stress_level=0.5)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store() -> VoiceStore:
    return VoiceStore()


@pytest.fixture
def factory(store: VoiceStore, clock: FakeClock) -> Callable[[], InMemoryVoiceUnitOfWork]:
    return uow_factory(store, clock)


@pytest.fixture
def config() -> VoiceTurnConfig:
    return VoiceTurnConfig()


@pytest.fixture
def session_id() -> SessionId:
    return SessionId(uuid.uuid4())


def a_planned(index: int) -> PlannedCallerUtterance:
    return PlannedCallerUtterance(
        turn_id=uuid.uuid4(),
        turn_index=index,
        text=TEXT_RU,
        fact_ids=FACTS,
        emotion=EMOTION,
        source="LLM",
    )


def a_context(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> TurnContext:
    return TurnContext(
        session_id=session_id,
        call_id=CALL_ID,
        config=config,
        transport=FakeCallTransport(clock=clock),
        appender=VoiceEventAppender(
            session_id=session_id, uow_factory=factory, clock=clock, started_at=clock.now()
        ),
        recorder=None,
    )


async def test_a_tts_failure_logs_and_uses_the_configured_fallback_and_never_resets(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    metrics = NullMetricsRecorder()
    fallback = FakeTTS(provider_name="piper", model_version="ru_RU-irina-medium")
    sink = TtsSpeechSink(
        provider=FakeTTS(fail_on_chunk=0),
        fallback_provider=fallback,
        metrics=metrics,
        clock=clock,
        config=config,
        uow_factory=factory,
    )
    context = a_context(session_id, factory, clock, config)
    before = list(store.events)

    # -- turn 0: the primary provider fails; SPEC §39 says "log failure and use the fallback" ----
    await sink.speak(a_planned(0), context)

    turn_0_types = [event.event_type for event in store.events]
    assert turn_0_types == [
        EventType.MODEL_ERROR,
        EventType.MODEL_FALLBACK_USED,
        EventType.CALLER_TTS_STARTED,
        EventType.CALLER_TTS_ENDED,
        EventType.FACTS_DELIVERED,
    ], "the failure must be logged (MODEL_ERROR) and the configured fallback must speak the turn"
    assert store.events[1].payload["fallback_kind"] == "TTS_FALLBACK_PROVIDER"
    assert [request[0] for request in fallback.requests] == [TEXT_RU]

    # -- never silently reset: the failure changed nothing that came before it -------------------
    assert_prefix_preserved(before, store.events)

    # -- the next turn is unaffected: a healthy provider speaks normally, and turn 0 is untouched -
    healthy = FakeTTS(provider_name="qwen3_tts")
    sink_2 = TtsSpeechSink(
        provider=healthy, metrics=metrics, clock=clock, config=config, uow_factory=factory
    )
    turn_0_snapshot = list(store.events)
    await sink_2.speak(a_planned(1), context)

    assert_prefix_preserved(turn_0_snapshot, store.events)
    new_types = [event.event_type for event in store.events[len(turn_0_snapshot) :]]
    assert new_types == [
        EventType.CALLER_TTS_STARTED,
        EventType.CALLER_TTS_ENDED,
        EventType.FACTS_DELIVERED,
    ], "the next turn must work normally after a prior TTS failure"


async def test_a_fallback_that_also_fails_ends_the_turn_silent_but_complete_never_reset(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """§6/D9: the second failure ends the turn silently — it must not raise, and it still logs."""
    sink = TtsSpeechSink(
        provider=FakeTTS(fail_on_chunk=0),
        fallback_provider=FakeTTS(provider_name="piper", fail_on_chunk=0),
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        uow_factory=factory,
    )
    before = list(store.events)

    await sink.speak(a_planned(0), a_context(session_id, factory, clock, config))

    assert [event.event_type for event in store.events] == [
        EventType.MODEL_ERROR,
        EventType.MODEL_FALLBACK_USED,
        EventType.MODEL_ERROR,
    ]
    assert_prefix_preserved(before, store.events)
    # No facts were heard, but the planned utterance is not lost (SPEC §42 item 14).
    assert store.transcripts[0].text == TEXT_RU
    assert store.caller_outcomes[0].delivered_text == ""
