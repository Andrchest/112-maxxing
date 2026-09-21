"""INV 14 (TTS) — a TTS failure never erases simulation data and never ends the session.

> A model failure degrades the turn, never the session. The turn ends quietly with `MODEL_ERROR`,
> the configured fallback gets one go at the whole utterance, and if that fails too the turn ends
> **silent but complete**: the session stays ACTIVE, every event already appended stays, the
> record of what the caller was going to say survives, and the next turn works.

The ASR variant is `test_inv_14_asr_failure_keeps_session.py` and the LLM variant is
`test_inv_14_llm_failure_keeps_session.py` (E13). This is the third stage of the same chain, and
the thing it adds beyond the other two is the **fallback provider**: §6/D9's "configured
fallback" is one retry of the whole utterance on a second `TTSProvider`, announced by
`MODEL_FALLBACK_USED`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

import pytest
from app.application.dialogue.speech_sink import PlannedCallerUtterance
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.ports.tts import TtsUnavailableError
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.tts_speech_sink import TtsSpeechSink
from app.application.voice.turn_pipeline import TurnContext
from app.domain.caller.emotion import EmotionLabel, EmotionState
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.domain.facts.revealed import fold_revealed
from app.inference.tts.fake_tts import FakeTTS

from tests.unit.application.voice.conftest import (
    InMemoryVoiceUnitOfWork,
    VoiceStore,
    uow_factory,
)

CALL_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")
TEXT_RU = "Алло, я вас слушаю."
FACTS = ("incident.address",)
EMOTION = EmotionState(emotion=EmotionLabel.PANICKED, stress_level=0.6)


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


def a_planned(index: int = 0) -> PlannedCallerUtterance:
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


def a_sink(
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
    metrics: NullMetricsRecorder,
    *,
    provider: FakeTTS,
    fallback: FakeTTS | None = None,
) -> TtsSpeechSink:
    return TtsSpeechSink(
        provider=provider,
        fallback_provider=fallback,
        metrics=metrics,
        clock=clock,
        config=config,
        uow_factory=factory,
    )


def types_of(store: VoiceStore) -> list[EventType]:
    return [event.event_type for event in store.events]


@pytest.mark.parametrize(
    ("provider", "expected_status"),
    [
        (FakeTTS(fail_on_chunk=0), "ERROR"),
        (FakeTTS(fail_on_chunk=3), "ERROR"),
    ],
    ids=["fails at the first chunk", "fails mid-utterance"],
)
async def test_a_tts_failure_ends_the_turn_quietly_with_a_model_error(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
    provider: FakeTTS,
    expected_status: str,
) -> None:
    """`MODEL_ERROR{stage: "TTS"}`, a metric that says which, and no exception out of `speak`."""
    metrics = NullMetricsRecorder()
    sink = a_sink(factory, clock, config, metrics, provider=provider)

    await sink.speak(a_planned(), a_context(session_id, factory, clock, config))

    assert EventType.MODEL_ERROR in types_of(store)
    error = next(
        event.payload for event in store.events if event.event_type is EventType.MODEL_ERROR
    )
    assert error["component"] == "TTS"
    assert error["stage"] == "TTS"
    assert error["recoverable"] is True
    assert [metric.status for metric in metrics.metrics] == [expected_status]


async def test_a_failure_reveals_nothing(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """The trainee heard nothing, so the fold must still count the facts as unrevealed (D10)."""
    sink = a_sink(factory, clock, config, NullMetricsRecorder(), provider=FakeTTS(fail_on_chunk=0))

    await sink.speak(a_planned(), a_context(session_id, factory, clock, config))

    assert EventType.FACTS_DELIVERED not in types_of(store)
    assert EventType.CALLER_TTS_ENDED not in types_of(store)
    assert fold_revealed(store.events) == frozenset()


async def test_the_fallback_provider_gets_one_go_at_the_whole_utterance(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """§6/D9's "configured fallback", announced by `MODEL_FALLBACK_USED` (§10.13)."""
    fallback = FakeTTS(provider_name="piper", model_version="ru_RU-irina-medium")
    sink = a_sink(
        factory,
        clock,
        config,
        NullMetricsRecorder(),
        provider=FakeTTS(fail_on_chunk=0),
        fallback=fallback,
    )

    await sink.speak(a_planned(), a_context(session_id, factory, clock, config))

    assert types_of(store) == [
        EventType.MODEL_ERROR,
        EventType.MODEL_FALLBACK_USED,
        EventType.CALLER_TTS_STARTED,
        EventType.CALLER_TTS_ENDED,
        EventType.FACTS_DELIVERED,
    ]
    used = store.events[1].payload
    assert used["component"] == "TTS"
    assert used["attempt"] == 1
    assert used["fallback_kind"] == "TTS_FALLBACK_PROVIDER"
    # The *whole* utterance, not the remainder of the failed one (SPEC §25's "actual text").
    assert [request[0] for request in fallback.requests] == [TEXT_RU]
    assert fold_revealed(store.events) == frozenset(FACTS)


async def test_two_failures_leave_the_turn_silent_but_complete(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """The invariant's hard case: no audio, no facts — and no lost data either."""
    sink = a_sink(
        factory,
        clock,
        config,
        NullMetricsRecorder(),
        provider=FakeTTS(fail_on_chunk=0),
        fallback=FakeTTS(provider_name="piper", fail_on_chunk=0),
    )

    await sink.speak(a_planned(), a_context(session_id, factory, clock, config))

    assert types_of(store) == [
        EventType.MODEL_ERROR,
        EventType.MODEL_FALLBACK_USED,
        EventType.MODEL_ERROR,
    ]
    # §6.4/§9.1's permitted reading: the transcript keeps what was *planned* — losing it would be
    # exactly the data loss SPEC §42 item 14 forbids — and the turn row says nothing was heard.
    assert len(store.transcripts) == 1
    assert store.transcripts[0].speaker == "CALLER"
    assert store.transcripts[0].text == TEXT_RU
    assert store.caller_outcomes[0].delivered_text == ""
    assert store.caller_outcomes[0].interrupted is False
    assert fold_revealed(store.events) == frozenset()


async def test_the_next_turn_is_spoken_normally_after_a_failure(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """ "The session stays ACTIVE and the next turn works" — the whole point of the invariant."""
    provider = FakeTTS(fail_on_chunk=0)
    sink = a_sink(factory, clock, config, NullMetricsRecorder(), provider=provider)
    context = a_context(session_id, factory, clock, config)

    await sink.speak(a_planned(0), context)
    provider.fail_on_chunk = None
    await sink.speak(a_planned(1), context)

    kinds = types_of(store)
    assert kinds[0] is EventType.MODEL_ERROR
    assert kinds[-3:] == [
        EventType.CALLER_TTS_STARTED,
        EventType.CALLER_TTS_ENDED,
        EventType.FACTS_DELIVERED,
    ]
    assert fold_revealed(store.events) == frozenset(FACTS)


async def test_a_failing_warm_up_does_not_raise_out_of_the_turn(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """A provider that cannot even warm up is still only a degraded turn, not a crash."""
    provider = FakeTTS(fail_on_warm_up=TtsUnavailableError("no weights"))
    provider.fail_on_chunk = 0
    sink = a_sink(factory, clock, config, NullMetricsRecorder(), provider=provider)

    await asyncio.wait_for(
        sink.speak(a_planned(), a_context(session_id, factory, clock, config)), timeout=10
    )


async def test_a_provider_that_stalls_is_a_timeout_turn_not_a_hung_call(
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    store: VoiceStore,
    clock: FakeClock,
    config: VoiceTurnConfig,
) -> None:
    """`tts_first_chunk_timeout_ms` guards §8 row 8: no first audio, no call left hanging."""
    metrics = NullMetricsRecorder()
    sink = TtsSpeechSink(
        provider=FakeTTS(chunk_delay_ms=200),
        metrics=metrics,
        clock=clock,
        config=config,
        uow_factory=factory,
        first_chunk_timeout_ms=20,
        timeout_ms=2000,
    )

    await asyncio.wait_for(
        sink.speak(a_planned(), a_context(session_id, factory, clock, config)), timeout=10
    )

    assert types_of(store) == [EventType.MODEL_ERROR]
    assert store.events[0].payload["error_code"] == "TIMEOUT"
    assert [metric.status for metric in metrics.metrics] == ["TIMEOUT"]
    assert fold_revealed(store.events) == frozenset()
