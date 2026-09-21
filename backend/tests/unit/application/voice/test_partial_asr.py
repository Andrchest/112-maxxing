"""Partial ASR — §4.5 and SPEC §17 ("the response begins only from the finalized turn").

The emitter is driven directly where the property is about the emitter, and through a whole
`TurnPipeline` where the property is about the *pipeline* (that partials are gated, that they are
cancelled at `USER_SPEECH_ENDED`, and that the documented event order holds).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence

import pytest
from app.application.ports.asr import AsrResult
from app.application.ports.call_transport import AudioFrame
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.asr_responder import AsrTurnResponder
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.partial_asr import PartialAsrEmitter, partial_request_id
from app.application.voice.turn_detector import TurnDetector
from app.application.voice.turn_pipeline import TranscribedTurn, TurnContext, TurnPipeline
from app.domain.common.ids import RoleStageId, SessionId
from app.domain.events.types import EventType
from app.inference.asr import FakeASR

from tests.unit.application.voice.conftest import (
    InMemoryVoiceUnitOfWork,
    VoiceStore,
    concat,
    make_vad,
    quiet,
    speech,
    uow_factory,
)

CALL_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
STAGE_ID = RoleStageId(uuid.UUID("44444444-4444-4444-8444-444444444444"))
TEXT_RU = "Пожар на улице Ленина пять"


class NonStreamingFakeASR(FakeASR):
    """`FakeASR` with `supports_streaming` forced off — the GigaAM baseline of §4.5."""

    @property
    def supports_streaming(self) -> bool:
        return False


class ConstantASR(NonStreamingFakeASR):
    """Always returns the same final, so a test's assertions do not depend on script length.

    The partial ticks and the final share one script cursor in `FakeASR`; a test that is about
    the *pipeline* should not have to count how many partials happened to fire first.
    """

    def __init__(self, text: str) -> None:
        super().__init__([])
        self._text = text

    async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> AsrResult:
        await super().transcribe(audio, sample_rate, request_id=request_id)
        return AsrResult(
            text=self._text,
            is_final=True,
            start_ms=0,
            end_ms=0,
            confidence=0.9,
            provider=self.provider_name,
            model_version=self.model_version,
        )


@pytest.fixture
def session_id() -> SessionId:
    return SessionId(uuid.uuid4())


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store() -> VoiceStore:
    return VoiceStore()


@pytest.fixture
def factory(store: VoiceStore, clock: FakeClock) -> Callable[[], InMemoryVoiceUnitOfWork]:
    return uow_factory(store, clock)


async def a_stage(session_id: SessionId) -> RoleStageId | None:
    return STAGE_ID


def make_emitter(
    asr: FakeASR,
    config: VoiceTurnConfig,
    appended: list[object],
    *,
    enabled: bool = True,
) -> PartialAsrEmitter:
    async def append(events: Sequence[object]) -> None:
        appended.extend(events)

    return PartialAsrEmitter(
        asr=asr,
        append=append,  # type: ignore[arg-type]
        call_id=CALL_ID,
        config=config,
        offset_ms=lambda: 0,
        enabled=enabled,
    )


def a_frame(config: VoiceTurnConfig) -> AudioFrame:
    return AudioFrame(
        pcm=b"\x10\x27" * config.frame_samples,
        sample_rate=config.sample_rate,
        num_channels=1,
        samples_per_channel=config.frame_samples,
        capture_offset_ms=0,
    )


# ---------------------------------------------------------------------------------------------
# The emitter itself
# ---------------------------------------------------------------------------------------------


async def test_a_disabled_emitter_never_calls_the_provider(config: VoiceTurnConfig) -> None:
    """The gate is folded into one boolean; off means no task, no call, no event."""
    asr = NonStreamingFakeASR([TEXT_RU])
    appended: list[object] = []
    emitter = make_emitter(asr, config, appended, enabled=False)

    emitter.start_turn(turn_id=uuid.uuid4(), turn_index=0, start_ms=0)
    for _ in range(50):
        await emitter.on_frame(a_frame(config), accumulated=b"\x00" * 64_000, accumulated_ms=2000)
    await emitter.end_turn()

    assert asr.calls == []
    assert appended == []


async def test_pseudo_streaming_uses_the_documented_request_ids(config: VoiceTurnConfig) -> None:
    """§4.5: `{turn_id}:p0`, `{turn_id}:p1`, … one per `partial_interval_ms` of speech."""
    asr = NonStreamingFakeASR(["один", "один два"])
    appended: list[object] = []
    emitter = make_emitter(asr, config, appended)
    turn_id = uuid.uuid4()

    emitter.start_turn(turn_id=turn_id, turn_index=0, start_ms=100)
    for tick in range(1, 4):
        accumulated_ms = tick * config.partial_interval_ms
        await emitter.on_frame(
            a_frame(config), accumulated=b"\x00" * 1000, accumulated_ms=accumulated_ms
        )
        # Let the partial task run to completion before the next tick.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    await emitter.end_turn()

    assert emitter.request_ids[:2] == [
        partial_request_id(turn_id, 0),
        partial_request_id(turn_id, 1),
    ]
    assert [call.request_id for call in asr.calls][:2] == emitter.request_ids[:2]


async def test_a_tick_is_skipped_rather_than_queued_while_one_is_in_flight(
    config: VoiceTurnConfig,
) -> None:
    """§4.5: at most one partial in flight; a stale hypothesis is not worth the GPU."""

    class Hanging(NonStreamingFakeASR):
        def __init__(self) -> None:
            super().__init__([])
            self.started = 0

        async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> AsrResult:
            self.started += 1
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    asr = Hanging()
    appended: list[object] = []
    emitter = make_emitter(asr, config, appended)

    emitter.start_turn(turn_id=uuid.uuid4(), turn_index=0, start_ms=0)
    for tick in range(1, 6):
        await emitter.on_frame(
            a_frame(config),
            accumulated=b"\x00" * 1000,
            accumulated_ms=tick * config.partial_interval_ms,
        )
        await asyncio.sleep(0)

    assert emitter.in_flight is True
    assert asr.started == 1
    assert len(emitter.request_ids) == 1

    await emitter.end_turn()
    assert emitter.in_flight is False


async def test_an_empty_hypothesis_costs_no_event(config: VoiceTurnConfig) -> None:
    """An empty partial tells the trainee nothing and would still consume a `seq_no`."""
    asr = NonStreamingFakeASR(["   "])
    appended: list[object] = []
    emitter = make_emitter(asr, config, appended)

    emitter.start_turn(turn_id=uuid.uuid4(), turn_index=0, start_ms=0)
    await emitter.on_frame(
        a_frame(config), accumulated=b"\x00" * 1000, accumulated_ms=config.partial_interval_ms
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await emitter.end_turn()

    assert appended == []


async def test_a_failing_partial_is_swallowed(config: VoiceTurnConfig) -> None:
    """A partial failing is not a turn failing."""
    asr = NonStreamingFakeASR([RuntimeError("no")])
    appended: list[object] = []
    emitter = make_emitter(asr, config, appended)

    emitter.start_turn(turn_id=uuid.uuid4(), turn_index=0, start_ms=0)
    await emitter.on_frame(
        a_frame(config), accumulated=b"\x00" * 1000, accumulated_ms=config.partial_interval_ms
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await emitter.end_turn()

    assert appended == []


async def test_a_streaming_provider_is_forwarded_and_its_final_is_dropped(
    config: VoiceTurnConfig,
) -> None:
    """§4.5: the native stream's partials become events; its final does not (one `ASR_FINAL`)."""
    asr = FakeASR([TEXT_RU])
    appended: list[object] = []
    emitter = make_emitter(asr, config, appended)

    emitter.start_turn(turn_id=uuid.uuid4(), turn_index=0, start_ms=0)
    for _ in range(4):
        await emitter.on_frame(a_frame(config), accumulated=b"", accumulated_ms=0)
    await emitter.end_turn()

    assert appended, "the native stream produced no partial"
    assert all(getattr(event, "event_type", None) is EventType.ASR_PARTIAL for event in appended)
    assert [event.payload["text"] for event in appended] == [
        "Пожар",
        "Пожар на",
        "Пожар на улице",
        "Пожар на улице Ленина",
    ]


# ---------------------------------------------------------------------------------------------
# Through the pipeline
# ---------------------------------------------------------------------------------------------


def make_pipeline(
    config: VoiceTurnConfig,
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
    asr: FakeASR,
    frames: Sequence[AudioFrame],
    *,
    show_partials: bool = True,
    next_stage: object = None,
) -> TurnPipeline:
    async def policy(_: SessionId) -> bool:
        return show_partials

    appender = VoiceEventAppender(
        session_id=session_id, uow_factory=factory, clock=clock, started_at=clock.now()
    )
    responder = AsrTurnResponder(
        asr=asr,
        metrics=_NoMetrics(),
        clock=clock,
        config=config,
        stage_resolver=a_stage,  # type: ignore[arg-type]
        timeout_ms=4000,
        next_stage=next_stage,  # type: ignore[arg-type]
    )
    return TurnPipeline(
        session_id=session_id,
        call_id=CALL_ID,
        transport=FakeCallTransport(clock=clock, inbound=list(frames)),
        vad=make_vad(config),
        detector=TurnDetector(config),
        appender=appender,
        clock=clock,
        config=config,
        responder=responder,
        asr=asr,
        show_asr_partials=policy,
    )


class _NoMetrics:
    async def record(self, metric: object) -> None:
        return None

    async def record_turn_latency(
        self, session_id: uuid.UUID, turn_id: uuid.UUID, speech_end_to_first_audio_ms: int
    ) -> None:
        return None


def one_turn_of_audio(config: VoiceTurnConfig) -> list[AudioFrame]:
    """Enough speech for several partial ticks, then the endpoint silence."""
    return concat(
        quiet(config, 128, 0),
        speech(config, 2048, 0),
        quiet(config, config.endpoint_silence_ms + 128, 0),
    )


async def test_the_documented_event_order_holds_end_to_end(
    config: VoiceTurnConfig,
    session_id: SessionId,
    store: VoiceStore,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
) -> None:
    """§3.7: USER_SPEECH_STARTED, ASR_PARTIAL×n, USER_SPEECH_ENDED, ASR_FINAL, in `seq_no` order."""
    asr = NonStreamingFakeASR(["п", "пож", "пожар", TEXT_RU])
    pipeline = make_pipeline(config, session_id, factory, clock, asr, one_turn_of_audio(config))

    await pipeline.run()

    types = [event.event_type for event in store.events]
    assert types[0] is EventType.USER_SPEECH_STARTED
    assert EventType.ASR_PARTIAL in types, "no partial was produced"
    ended = types.index(EventType.USER_SPEECH_ENDED)
    final = types.index(EventType.ASR_FINAL)
    assert final > ended, "the final overtook the speech-end boundary"
    assert all(
        index < ended for index, kind in enumerate(types) if kind is EventType.ASR_PARTIAL
    ), "a partial outlived its turn"
    assert [event.seq_no for event in store.events] == sorted(
        event.seq_no for event in store.events
    )


async def test_partials_are_off_when_the_config_says_so(
    session_id: SessionId,
    store: VoiceStore,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
) -> None:
    """`partial_asr_enabled=False` — gate one of §4.5."""
    config = VoiceTurnConfig(partial_asr_enabled=False)
    asr = NonStreamingFakeASR([TEXT_RU])
    pipeline = make_pipeline(config, session_id, factory, clock, asr, one_turn_of_audio(config))

    await pipeline.run()

    assert pipeline.partials is not None
    assert pipeline.partials.enabled is False
    assert EventType.ASR_PARTIAL not in [event.event_type for event in store.events]


async def test_partials_are_off_when_the_session_policy_says_so(
    config: VoiceTurnConfig,
    session_id: SessionId,
    store: VoiceStore,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
) -> None:
    """`SessionPolicy.show_asr_partials=False` (ASSESSMENT) — gate two of §4.5, D6."""
    asr = NonStreamingFakeASR([TEXT_RU])
    pipeline = make_pipeline(
        config, session_id, factory, clock, asr, one_turn_of_audio(config), show_partials=False
    )

    await pipeline.run()

    assert pipeline.partials is not None
    assert pipeline.partials.enabled is False
    assert EventType.ASR_PARTIAL not in [event.event_type for event in store.events]


async def test_a_partial_never_reaches_the_next_stage(
    config: VoiceTurnConfig,
    session_id: SessionId,
    factory: Callable[[], InMemoryVoiceUnitOfWork],
    clock: FakeClock,
) -> None:
    """SPEC §17: only the finalized turn drives a response, and only once."""
    handed: list[TranscribedTurn] = []

    class Recording:
        async def respond_transcribed(
            self, transcribed: TranscribedTurn, context: TurnContext
        ) -> None:
            handed.append(transcribed)

    asr = ConstantASR(TEXT_RU)
    pipeline = make_pipeline(
        config,
        session_id,
        factory,
        clock,
        asr,
        one_turn_of_audio(config),
        next_stage=Recording(),
    )

    await pipeline.run()

    assert len(handed) == 1, "the next stage saw something other than exactly the final turn"
    # Several partials fired for that one turn, and none of them reached the next stage.
    assert sum(1 for call in asr.calls if ":p" in call.request_id) >= 1
