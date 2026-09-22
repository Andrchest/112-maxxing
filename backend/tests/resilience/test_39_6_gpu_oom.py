"""SPEC §39 #6 — "GPU OOM: surface a fatal inference health error and preserve session state."

(`docs/SPEC.md:1044-1045`.) The mechanism is HLD 60 §4.4, whose own first line is the whole
requirement restated: **an OOM changes health, never simulation state.**

Driven through the two public seams an OOM actually crosses:

* `voice_agent.health.InferenceHealthGuard` — the `guard_inference(stage)` of §4.4. It is what
  turns `InferenceOutOfMemoryError` into FATAL, publishes the transition and latches
  `voice:health:fatal`; and it is what must *not* do anything else;
* `AsrTurnResponder` / `TtsSpeechSink` — the stages whose turn must still finish, with
  `MODEL_ERROR{error_kind:"OOM", recoverable:false}` and nothing rolled back.

`backend/tests/resilience/` runs under the ordinary gate, which has no torch and no GPU (D13): the
`empty_cache` hook is injected, so "it is called once and no model is reloaded" is a real assertion
here rather than something only a GPU box could check.

Every test closes on §39's last line, "Never silently reset the simulation", via
`conftest.assert_prefix_preserved`: the event log only ever grows, and never in place.
"""

from __future__ import annotations

import uuid

import pytest
from app.application.dialogue.speech_sink import PlannedCallerUtterance
from app.application.ports.inference_guard import (
    STAGE_ASR,
    STAGE_LLM,
    STAGE_TTS,
    STAGE_VAD,
    NoOpInferenceGuard,
    is_out_of_memory,
)
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.asr_responder import AsrTurnResponder
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.tts_speech_sink import TtsSpeechSink
from app.application.voice.turn_detector import DetectedTurn, TurnEndReason
from app.application.voice.turn_pipeline import (
    TranscribedTurn,
    TranscribedTurnResponder,
    TurnContext,
)
from app.domain.caller.emotion import EmotionLabel, EmotionState
from app.domain.common.ids import RoleStageId, SessionId
from app.domain.events.types import EventType
from app.inference.asr import FakeASR
from app.inference.errors import InferenceOutOfMemoryError
from app.inference.tts.fake_tts import FakeTTS
from voice_agent.health import (
    STATE_FATAL,
    STATE_READY,
    HealthTransition,
    InferenceHealth,
    InferenceHealthGuard,
)

from tests.resilience.conftest import assert_prefix_preserved
from tests.unit.application.voice.conftest import VoiceStore, uow_factory

CALL_ID = uuid.UUID("39696969-3969-4969-8969-396969696969")
STAGE_ID = RoleStageId(uuid.UUID("39696969-3969-4969-8969-396969696970"))
OOM_MESSAGE = "CUDA out of memory. Tried to allocate 1.20 GiB"


@pytest.fixture
def config() -> VoiceTurnConfig:
    """The HLD's defaults (see the sibling §39 #5 module on why this is not a shared fixture)."""
    return VoiceTurnConfig()


class _Registry:
    """The voice-agent's health publisher, as a list — the process's own is `VoiceAgent`'s."""

    def __init__(self, **kwargs: object) -> None:
        self.health = InferenceHealth(**kwargs)  # type: ignore[arg-type]
        self.published: list[HealthTransition] = []
        self.cache_emptied = 0
        self.reloads = 0

    async def publish(self, transition: HealthTransition) -> None:
        self.published.append(transition)

    def empty_cache(self) -> bool:
        self.cache_emptied += 1
        return True

    def guard(self) -> InferenceHealthGuard:
        return InferenceHealthGuard(
            self.health, self.publish, monotonic_s=lambda: 0.0, empty_cache=self.empty_cache
        )

    def warm_everything(self) -> None:
        for service in self.health.services:
            self.health[service].warm_started()
            self.health[service].warm_succeeded()


class _OomAsr(FakeASR):
    """A `FakeASR` whose `transcribe` raises the allocation failure a real provider raises."""

    async def transcribe(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        raise InferenceOutOfMemoryError(OOM_MESSAGE)


class _RecordingNextStage(TranscribedTurnResponder):
    def __init__(self) -> None:
        self.handed: list[TranscribedTurn] = []

    async def respond_transcribed(self, transcribed: TranscribedTurn, context: TurnContext) -> None:
        self.handed.append(transcribed)


async def _a_stage(session_id: SessionId) -> RoleStageId | None:
    return STAGE_ID


def _a_turn(config: VoiceTurnConfig, *, index: int = 0) -> DetectedTurn:
    return DetectedTurn(
        turn_id=uuid.uuid4(),
        turn_index=index,
        audio=b"\x10\x27" * (config.sample_rate // 2),
        start_ms=1000 * (index + 1),
        end_ms=1000 * (index + 1) + 500,
        end_reason=TurnEndReason.ENDPOINT_SILENCE,
        discarded_short=False,
        is_barge_in=False,
        pre_roll_ms=config.pre_roll_ms,
    )


def _a_planned(*, index: int = 0) -> PlannedCallerUtterance:
    return PlannedCallerUtterance(
        turn_id=uuid.uuid4(),
        turn_index=index,
        text="Алло, я вас слушаю.",
        fact_ids=("incident.address",),
        emotion=EmotionState(emotion=EmotionLabel.PANICKED, stress_level=0.6),
        source="LLM",
    )


def _context(config: VoiceTurnConfig, store: VoiceStore, clock: FakeClock) -> TurnContext:
    session_id = SessionId(uuid.uuid4())
    return TurnContext(
        session_id=session_id,
        call_id=CALL_ID,
        config=config,
        transport=FakeCallTransport(clock=clock, outbound_queue_ms=config.outbound_queue_ms),
        appender=VoiceEventAppender(
            session_id=session_id,
            uow_factory=uow_factory(store, clock),
            clock=clock,
            started_at=clock.now(),
        ),
        recorder=None,
    )


def _snapshot(store: VoiceStore) -> list[tuple[int, str, str]]:
    return [
        (event.seq_no, event.event_type.value, repr(sorted(event.payload.items())))
        for event in store.events
    ]


def _model_errors(store: VoiceStore) -> list[dict]:
    return [dict(e.payload) for e in store.events if e.event_type is EventType.MODEL_ERROR]


# -- the health half: FATAL, published, latched, terminal ---------------------------------------


@pytest.mark.parametrize("stage", [STAGE_VAD, STAGE_ASR, STAGE_LLM, STAGE_TTS])
async def test_an_oom_in_any_stage_surfaces_a_fatal_inference_health_error(stage: str) -> None:
    """SPEC §39 #6, first half: "surface a fatal inference health error"."""
    registry = _Registry()
    registry.warm_everything()
    guard = registry.guard()

    async def _oom() -> None:
        raise InferenceOutOfMemoryError(OOM_MESSAGE)

    with pytest.raises(InferenceOutOfMemoryError):
        await guard.run(stage, _oom)

    assert len(registry.published) == 1
    transition = registry.published[0]
    assert transition.from_state == STATE_READY
    assert transition.to_state == STATE_FATAL
    assert transition.is_fatal is True  # -> `voice:health:fatal`, no expiry (§4.3)
    assert OOM_MESSAGE in (transition.detail or "")
    # §4.4 rule 4: the allocator is emptied once, and nothing is reloaded.
    assert registry.cache_emptied == 1
    assert registry.reloads == 0


async def test_a_fatal_service_is_never_auto_retried() -> None:
    """§4.1: "FATAL — nothing; only a process restart leaves FATAL". No re-warm, ever."""
    registry = _Registry(rewarm_interval_s=1)
    registry.warm_everything()
    guard = registry.guard()

    async def _oom() -> None:
        raise InferenceOutOfMemoryError(OOM_MESSAGE)

    with pytest.raises(InferenceOutOfMemoryError):
        await guard.run(STAGE_TTS, _oom)
    assert registry.health.due_for_rewarm(10_000.0) == ()
    assert registry.health.state("tts") == STATE_FATAL
    # The other three are untouched: one card's OOM is not a reason to distrust the CPU VAD.
    assert registry.health.state("vad") == STATE_READY
    assert registry.health.state("asr") == STATE_READY
    assert registry.health.state("llm") == STATE_READY


# -- the simulation half: the turn finishes, nothing is reset -----------------------------------


async def test_an_asr_oom_ends_the_turn_quietly_and_preserves_every_earlier_event(
    config: VoiceTurnConfig,
) -> None:
    """SPEC §39 #6, second half: "preserve session state" — and §4.4's `MODEL_ERROR`."""
    clock = FakeClock()
    store = VoiceStore()
    context = _context(config, store, clock)
    registry = _Registry()
    registry.warm_everything()
    next_stage = _RecordingNextStage()
    responder = AsrTurnResponder(
        asr=_OomAsr(),
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        stage_resolver=_a_stage,
        timeout_ms=4000,
        next_stage=next_stage,
        guard=registry.guard(),
    )

    # One healthy turn first, so "preserved" has something to be about.
    healthy = AsrTurnResponder(
        asr=FakeASR(),
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        stage_resolver=_a_stage,
        timeout_ms=4000,
        guard=NoOpInferenceGuard(),
    )
    await healthy.respond(_a_turn(config, index=0), context)
    before = _snapshot(store)
    assert before, "the healthy turn must have written something"

    await responder.respond(_a_turn(config, index=1), context)

    # The session is untouched and the log only grew.
    assert_prefix_preserved(before, _snapshot(store))
    # §4.4: `MODEL_ERROR{error_kind:"OOM", recoverable:false}`.
    errors = _model_errors(store)
    assert len(errors) == 1
    assert errors[0]["component"] == "ASR"
    assert errors[0]["error_code"] == "OOM"
    assert errors[0]["error_kind"] == "OOM"
    assert errors[0]["recoverable"] is False
    # No transcript, no hand-over to the dialogue stage — exactly the ordinary ASR-failure ending.
    types = [e.event_type for e in store.events]
    assert types.count(EventType.ASR_FINAL) == 1  # the healthy turn's, and only that one
    assert store.transcripts and len(store.transcripts) == 1
    assert next_stage.handed == []
    # The service is FATAL, the simulation is not.
    assert registry.health.state("asr") == STATE_FATAL
    assert EventType.SESSION_ABORTED not in types


async def test_the_oom_predicate_is_what_both_layers_agree_on() -> None:
    """D2 forbids `app.application` importing `app.inference`, so the two sides must still agree."""
    assert is_out_of_memory(InferenceOutOfMemoryError(OOM_MESSAGE)) is True
    assert is_out_of_memory(RuntimeError(OOM_MESSAGE)) is False

    class _Subclass(InferenceOutOfMemoryError):
        pass

    assert is_out_of_memory(_Subclass("x")) is True


async def test_three_ordinary_failures_demote_but_do_not_go_fatal(config: VoiceTurnConfig) -> None:
    """The contrast that makes FATAL mean something: §4.1 row 5 is NOT_READY, row 6 is FATAL."""
    registry = _Registry(failure_threshold=3)
    registry.warm_everything()
    guard = registry.guard()

    async def _ordinary() -> None:
        raise RuntimeError("the llama-server connection dropped")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await guard.run(STAGE_LLM, _ordinary)

    assert registry.health.state("llm") == "NOT_READY"
    assert registry.health.any_fatal is False
    assert registry.cache_emptied == 0
    # And it *is* retried, unlike FATAL: `rewarm_interval_s` later it is due.
    assert "llm" in registry.health.due_for_rewarm(10_000.0)


def test_the_state_machine_carries_no_clock_of_its_own() -> None:
    """A pure machine has no `at`: the publisher stamps the instant from the injected `Clock`,
    which is why none of these tests can be flaky about wall time."""
    transition = HealthTransition("llm", STATE_READY, STATE_FATAL, OOM_MESSAGE)
    assert not hasattr(transition, "at")
    assert (transition.service, transition.to_state) == ("llm", STATE_FATAL)


# -- the TTS stage: the turn still ends, silent but complete ------------------------------------


class _OomTts(FakeTTS):
    """A `FakeTTS` whose stream raises the allocation failure instead of yielding its first chunk.

    `FakeTTS(fail_on_chunk=0)` raises `TtsUnavailableError`; §4.4 is about the *other* failure, the
    one that is not recoverable, so this overrides the stream rather than reusing that flag.
    """

    def stream(self, text, voice, *, request_id, max_chunk_ms=20):  # type: ignore[no-untyped-def]
        async def _iter():  # type: ignore[no-untyped-def]
            raise InferenceOutOfMemoryError(OOM_MESSAGE)
            yield  # pragma: no cover - unreachable, makes this an async generator

        class _Stream:
            request_id = ""
            text = ""

            def __aiter__(self):  # type: ignore[no-untyped-def]
                return _iter()

            async def cancel(self) -> None:
                return None

        return _Stream()


async def test_a_tts_oom_ends_the_turn_silent_but_complete_and_preserves_the_log(
    config: VoiceTurnConfig,
) -> None:
    """SPEC §39 #6 at the TTS stage: no audio, but a complete turn and an intact log (INV 14).

    With `SIM_TTS_FALLBACK_PROVIDER=none` (the gate's selection) the first failure is already the
    last row of INV 14's ladder, so the turn ends silent-but-complete. Health went FATAL; the
    session did not move, and nothing already written changed.
    """
    clock = FakeClock()
    store = VoiceStore()
    context = _context(config, store, clock)
    registry = _Registry()
    registry.warm_everything()

    healthy_sink = TtsSpeechSink(
        provider=FakeTTS(),
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        uow_factory=uow_factory(store, clock),
    )
    await healthy_sink.speak(_a_planned(index=0), context)
    before = _snapshot(store)
    assert before, "the healthy utterance must have written something"

    sink = TtsSpeechSink(
        provider=_OomTts(),
        metrics=NullMetricsRecorder(),
        clock=clock,
        config=config,
        uow_factory=uow_factory(store, clock),
        guard=registry.guard(),
    )
    await sink.speak(_a_planned(index=1), context)

    assert_prefix_preserved(before, _snapshot(store))
    assert registry.health.state("tts") == STATE_FATAL
    assert registry.published[-1].to_state == STATE_FATAL

    errors = _model_errors(store)
    assert len(errors) == 1
    assert errors[0]["component"] == "TTS"
    assert errors[0]["error_code"] == "OOM"
    assert errors[0]["error_kind"] == "OOM"
    assert errors[0]["recoverable"] is False

    types = [e.event_type for e in store.events]
    # Silent but *complete*: no second `CALLER_TTS_STARTED`, and — because nothing was heard —
    # no second `FACTS_DELIVERED` (D10: facts are revealed by an uninterrupted playback).
    assert types.count(EventType.CALLER_TTS_STARTED) == 1
    assert types.count(EventType.FACTS_DELIVERED) == 1
    assert EventType.SESSION_ABORTED not in types
