"""INV 14 — "A model failure does not erase simulation data" (SPEC §42 item 14, §24, §39).

E12 proved it for the ASR stage (`test_inv_14_asr_failure_keeps_session.py`). This is the same
invariant for the two LLM calls E13 adds, and it is a stronger statement than "nothing crashed":

* the session is still `ACTIVE` — no state was moved, no card touched, nothing rolled back;
* the `ASR_FINAL` event, the `transcript_segments` row and the `audio_segments` reference of the
  **failing** turn are all still there, byte for byte;
* the failure is in the log as `MODEL_ERROR` and/or `MODEL_FALLBACK_USED`, so an instructor can
  see what happened rather than infer it from a gap;
* the caller still answers — SPEC §24's deterministic fallback — so the trainee is not left
  listening to silence because a model timed out. The single exception is a cancelled turn: a
  barge-in means a newer turn arrived, and answering the old one would be the bug;
* the **next** turn is processed normally, which is what "does not erase" actually has to mean
  for a training session that is still running.

The whole chain runs: `AsrTurnResponder` → `DialogueResponder` → interpreter → gate → generator →
validator → §7.8. Only the models are fakes (D13).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from app.application.dialogue.dialogue_context import DialogueContextLoader
from app.application.dialogue.fallbacks import FallbackTemplates
from app.application.dialogue.generator import (
    CallerResponseGenerator,
    GeneratorConfig,
)
from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
from app.application.dialogue.prompt_builder import CallerPromptBuilder, CallerPromptConfig
from app.application.dialogue.responder import DialogueResponder
from app.application.dialogue.speech_sink import NullCallerSpeechSink
from app.application.dialogue.validator import ResponseValidator, ValidatorConfig
from app.application.ports.llm import LlmTimeoutError, LlmUnavailableError
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeClock
from app.application.voice.asr_responder import AsrTurnResponder
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.turn_pipeline import TurnContext
from app.domain.common.ids import RoleStageId, SessionId
from app.domain.enums import SessionState
from app.inference.asr.fake_asr import FakeASR
from app.inference.llm.fake_llm import FakeLLM

from tests.unit.application.dialogue.conftest import (
    DialogueStore,
    InMemoryDialogueUnitOfWork,
    make_store,
    make_turn_context,
    make_uow_factory,
    transcribed_turn,
)

Factory = Callable[[], InMemoryDialogueUnitOfWork]


# The dialogue package's fixtures, re-declared here: a `conftest.py` is scoped to its directory,
# and the world these tests need is exactly the one its builders describe.


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(start=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.fixture
def store() -> DialogueStore:
    return make_store()


@pytest.fixture
def uow_factory(store: DialogueStore, clock: FakeClock) -> Factory:
    return make_uow_factory(store, clock)


@pytest.fixture
def turn_context(store: DialogueStore, clock: FakeClock, uow_factory: Factory) -> TurnContext:
    return make_turn_context(store, clock, uow_factory)


OPERATOR_TEXT = "Назовите адрес"
INTERPRETATION = {
    "speech_act": "QUESTION",
    "requested_facts": [{"fact_id": "address.street", "explicit": True}],
    "operator_assertions": [],
    "confirmation_targets": [],
    "semantic_confidence": 0.95,
}
GOOD_ANSWER = {"utterance": "Улица Николаева."}
#: Garbage the interpreter's schema rejects twice, so B1's ladder falls to UNINTELLIGIBLE.
GARBAGE = "не json"


def build_chain(
    store: DialogueStore,
    clock: FakeClock,
    uow_factory: Factory,
    script: list,
) -> tuple[AsrTurnResponder, NullCallerSpeechSink, FakeLLM]:
    """`AsrTurnResponder` with E13's `DialogueResponder` behind it — the production shape."""
    llm = FakeLLM(script)
    metrics = NullMetricsRecorder()
    sink = NullCallerSpeechSink()
    dialogue = DialogueResponder(
        loader=DialogueContextLoader(uow_factory, clock, window_turns=6),  # type: ignore[arg-type]
        interpreter=DialogueInterpreter(llm, metrics, config=InterpreterConfig()),
        generator=CallerResponseGenerator(
            llm,
            metrics,
            CallerPromptBuilder(CallerPromptConfig()),
            ResponseValidator(ValidatorConfig(small_count_allowlist=frozenset())),
            config=GeneratorConfig(),
        ),
        fallbacks=FallbackTemplates(),
        sink=sink,
        uow_factory=uow_factory,  # type: ignore[arg-type]
    )

    async def stage_resolver(session_id: SessionId) -> RoleStageId | None:
        return store.session.stages[0].role_stage_id

    responder = AsrTurnResponder(
        asr=FakeASR([OPERATOR_TEXT, OPERATOR_TEXT]),
        metrics=metrics,
        clock=clock,
        config=VoiceTurnConfig(),
        stage_resolver=stage_resolver,
        timeout_ms=4000,
        next_stage=dialogue,
    )
    return responder, sink, llm


def context_with_audio(context: TurnContext, turn_id: uuid.UUID) -> TurnContext:
    """A `TurnContext` whose turn already has a recorded `audio_segments` row (§9.1)."""
    return TurnContext(
        session_id=context.session_id,
        call_id=context.call_id,
        config=context.config,
        transport=context.transport,
        appender=context.appender,
        recorder=context.recorder,
        audio_segment_ids={turn_id: uuid.uuid4()},
    )


async def run_one_turn(
    responder: AsrTurnResponder,
    context: TurnContext,
    *,
    turn_index: int = 0,
) -> TurnContext:
    turn = transcribed_turn(OPERATOR_TEXT, turn_index=turn_index).turn
    scoped = context_with_audio(context, turn.turn_id)
    await responder.respond(turn, scoped)
    return scoped


def assert_turn_survived(store: DialogueStore, *, turn_index: int) -> None:
    """The ASR half of the turn is intact: event, transcript row, audio reference, turn row."""
    finals = [
        event
        for event in store.events
        if event.event_type.value == "ASR_FINAL" and event.payload["turn_index"] == turn_index
    ]
    assert len(finals) == 1, "the ASR_FINAL of the failing turn is gone"
    assert finals[0].payload["text"] == OPERATOR_TEXT
    assert finals[0].payload["audio_segment_id"] is not None
    transcripts = [row for row in store.transcripts if row.turn_index == turn_index]
    assert [row.text for row in transcripts] == [OPERATOR_TEXT]
    assert transcripts[0].audio_segment_id is not None
    assert (store.session.id, turn_index) in store.turns.rows


# ---------------------------------------------------------------------------------------------
# The interpreter's three failure modes
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "script"),
    [
        ("raises", [LlmUnavailableError("no server"), GOOD_ANSWER]),
        ("times out", [LlmTimeoutError("too slow"), GOOD_ANSWER]),
        ("returns garbage twice", [GARBAGE, GARBAGE, GOOD_ANSWER]),
    ],
)
async def test_an_interpreter_failure_keeps_the_turn_and_still_answers(
    name: str,
    script: list,
    store: DialogueStore,
    clock: FakeClock,
    uow_factory: Factory,
    turn_context: TurnContext,
) -> None:
    responder, sink, _ = build_chain(store, clock, uow_factory, script)

    await run_one_turn(responder, turn_context)

    assert store.session.state is SessionState.ACTIVE
    assert_turn_survived(store, turn_index=0)
    assert "MODEL_FALLBACK_USED" in store.event_types
    assert store.payloads("MODEL_FALLBACK_USED")[0]["component"] == "INTERPRETER"
    # SPEC §24: the caller still says something deterministic.
    assert len(sink.spoken) == 1
    assert sink.spoken[0].text
    assert sink.spoken[0].source == "FALLBACK"


# ---------------------------------------------------------------------------------------------
# The generator's two failure modes
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "error"),
    [("raises", LlmUnavailableError("no server")), ("times out", LlmTimeoutError("too slow"))],
)
async def test_a_generator_failure_keeps_the_turn_and_still_answers(
    name: str,
    error: Exception,
    store: DialogueStore,
    clock: FakeClock,
    uow_factory: Factory,
    turn_context: TurnContext,
) -> None:
    responder, sink, _ = build_chain(store, clock, uow_factory, [INTERPRETATION, error])

    await run_one_turn(responder, turn_context)

    assert store.session.state is SessionState.ACTIVE
    assert_turn_survived(store, turn_index=0)
    errors = store.payloads("MODEL_ERROR")
    assert [payload["component"] for payload in errors] == ["GENERATOR"]
    assert errors[0]["error_code"] == type(error).__name__
    assert errors[0]["recoverable"] is True
    fallbacks = store.payloads("MODEL_FALLBACK_USED")
    assert [payload["component"] for payload in fallbacks] == ["GENERATOR"]
    assert len(sink.spoken) == 1
    assert sink.spoken[0].source == "FALLBACK"
    assert sink.spoken[0].text
    # The plan was appended before the generation call, so the turn is still auditable.
    assert "CALLER_RESPONSE_PLANNED" in store.event_types


async def test_two_invalid_generations_keep_the_turn_and_still_answer(
    store: DialogueStore,
    clock: FakeClock,
    uow_factory: Factory,
    turn_context: TurnContext,
) -> None:
    """The validator rejected both attempts: §7.8 answers and the turn survives intact."""
    leak = {"utterance": "Нас тут сорок семь человек."}
    responder, sink, llm = build_chain(store, clock, uow_factory, [INTERPRETATION, leak, leak])

    await run_one_turn(responder, turn_context)

    assert store.session.state is SessionState.ACTIVE
    assert_turn_survived(store, turn_index=0)
    assert "CALLER_RESPONSE_GENERATED" not in store.event_types
    assert store.payloads("MODEL_FALLBACK_USED")[0]["failure_codes"] == ["NEW_NUMBER"]
    assert sink.spoken[0].source == "FALLBACK"
    assert len(llm.calls) == 3  # one interpreter call, then §7.7's two and no more


# ---------------------------------------------------------------------------------------------
# Cancellation is the one case with no answer — and it still erases nothing
# ---------------------------------------------------------------------------------------------


async def test_a_cancelled_generation_speaks_nothing_and_still_keeps_the_turn(
    store: DialogueStore,
    clock: FakeClock,
    uow_factory: Factory,
    turn_context: TurnContext,
) -> None:
    responder, sink, _ = build_chain(
        store, clock, uow_factory, [INTERPRETATION, asyncio.CancelledError()]
    )

    with pytest.raises(asyncio.CancelledError):
        await run_one_turn(responder, turn_context)

    assert store.session.state is SessionState.ACTIVE
    assert_turn_survived(store, turn_index=0)
    assert sink.spoken == []
    assert "MODEL_FALLBACK_USED" not in store.event_types


# ---------------------------------------------------------------------------------------------
# The next turn is processed normally
# ---------------------------------------------------------------------------------------------


async def test_the_next_turn_is_processed_normally_after_a_model_failure(
    store: DialogueStore,
    clock: FakeClock,
    uow_factory: Factory,
    turn_context: TurnContext,
) -> None:
    """ "Does not erase simulation data" has to mean the session keeps working."""
    responder, sink, _ = build_chain(
        store,
        clock,
        uow_factory,
        [INTERPRETATION, LlmTimeoutError("too slow"), INTERPRETATION, GOOD_ANSWER],
    )

    await run_one_turn(responder, turn_context, turn_index=0)
    await run_one_turn(responder, turn_context, turn_index=1)

    assert store.session.state is SessionState.ACTIVE
    assert_turn_survived(store, turn_index=0)
    assert_turn_survived(store, turn_index=1)
    assert [utterance.source for utterance in sink.spoken] == ["FALLBACK", "LLM"]
    assert sink.spoken[1].text == "Улица Николаева."
    generated = store.payloads("CALLER_RESPONSE_GENERATED")
    assert [payload["turn_index"] for payload in generated] == [1]


async def test_the_failing_turns_row_still_records_what_was_planned(
    store: DialogueStore,
    clock: FakeClock,
    uow_factory: Factory,
    turn_context: TurnContext,
) -> None:
    """§20.6: the read model records the fallback rather than losing the turn."""
    responder, sink, _ = build_chain(
        store, clock, uow_factory, [INTERPRETATION, LlmTimeoutError("too slow")]
    )

    await run_one_turn(responder, turn_context)

    row = store.turns.rows[(store.session.id, 0)]
    assert row.fallback_used is True
    assert row.planned_text == sink.spoken[0].text
    assert row.operator_transcript_segment_id is not None
