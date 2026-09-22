"""SPEC §39 #3 — "Invalid LLM structured output: one repair retry, then safe fallback."
(`docs/SPEC.md:1035-1036`).

The mechanism (HLD `50-voice-pipeline.md` §5.1/§7.7/§7.8, D9): the interpreter's schema validation
gets one repair attempt before falling back to `UNINTELLIGIBLE`+`MODEL_FALLBACK_USED`; the
generator's `ResponseValidator` gets one regeneration before falling back to a deterministic
template, also announced by `MODEL_FALLBACK_USED`. Both already exist end-to-end
(`DialogueInterpreter`, `CallerResponseGenerator`) and are proven in depth by
`test_inv_14_llm_failure_keeps_session.py`. This module drives the same public seam
(`AsrTurnResponder` -> `DialogueResponder` -> interpreter/generator) once for each half, for
exactly SPEC §39's own wording, and closes on "never silently reset": the session stays ACTIVE,
the turn's own record survives, and nothing an earlier turn wrote is touched by a later one.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from app.application.dialogue.dialogue_context import DialogueContextLoader
from app.application.dialogue.fallbacks import FallbackTemplates
from app.application.dialogue.generator import CallerResponseGenerator, GeneratorConfig
from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
from app.application.dialogue.prompt_builder import CallerPromptBuilder, CallerPromptConfig
from app.application.dialogue.responder import DialogueResponder
from app.application.dialogue.speech_sink import NullCallerSpeechSink
from app.application.dialogue.validator import ResponseValidator, ValidatorConfig
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeClock
from app.application.voice.asr_responder import AsrTurnResponder
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.turn_pipeline import TurnContext
from app.domain.common.ids import RoleStageId, SessionId
from app.domain.enums import SessionState
from app.inference.asr.fake_asr import FakeASR
from app.inference.llm.fake_llm import FakeLLM

from tests.resilience.conftest import assert_prefix_preserved
from tests.unit.application.dialogue.conftest import (
    DialogueStore,
    InMemoryDialogueUnitOfWork,
    make_store,
    make_turn_context,
    make_uow_factory,
    transcribed_turn,
)

Factory = Callable[[], InMemoryDialogueUnitOfWork]

OPERATOR_TEXT = "Назовите адрес"
#: Rejected by the interpreter's own schema twice, so the repair ladder falls to UNINTELLIGIBLE.
GARBAGE = "не json"
#: Rejected by `ResponseValidator` (a leaked number) twice, so the generator ladder falls back.
LEAKED_NUMBER = {"utterance": "Нас тут сорок семь человек."}
GOOD_INTERPRETATION = {
    "speech_act": "QUESTION",
    "requested_facts": [{"fact_id": "address.street", "explicit": True}],
    "operator_assertions": [],
    "confirmation_targets": [],
    "semantic_confidence": 0.95,
}
GOOD_ANSWER = {"utterance": "Улица Николаева."}


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store() -> DialogueStore:
    return make_store()


@pytest.fixture
def uow_factory(store: DialogueStore, clock: FakeClock) -> Factory:
    return make_uow_factory(store, clock)


@pytest.fixture
def turn_context(store: DialogueStore, clock: FakeClock, uow_factory: Factory) -> TurnContext:
    return make_turn_context(store, clock, uow_factory)


def build_chain(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, script: list
) -> tuple[AsrTurnResponder, NullCallerSpeechSink]:
    """`AsrTurnResponder` with `DialogueResponder` behind it — the production shape."""
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
    return responder, sink


async def run_turn(
    responder: AsrTurnResponder, context: TurnContext, *, turn_index: int = 0
) -> None:
    turn = transcribed_turn(OPERATOR_TEXT, turn_index=turn_index).turn
    await responder.respond(turn, context)


async def test_interpreter_gets_one_repair_then_a_safe_fallback_and_never_resets(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """Two garbage responses: one repair attempt, then `UNINTELLIGIBLE` + `MODEL_FALLBACK_USED`."""
    before = list(store.events)
    responder, sink = build_chain(store, clock, uow_factory, [GARBAGE, GARBAGE, GOOD_ANSWER])

    await run_turn(responder, turn_context)

    assert store.session.state is SessionState.ACTIVE
    assert "MODEL_FALLBACK_USED" in store.event_types
    fallback = store.payloads("MODEL_FALLBACK_USED")[0]
    assert fallback["component"] == "INTERPRETER"
    # SPEC §24: the caller still says something deterministic — not silence.
    assert len(sink.spoken) == 1
    assert sink.spoken[0].source == "FALLBACK"
    assert sink.spoken[0].text
    assert_prefix_preserved(before, store.events)


async def test_generator_gets_one_repair_then_a_safe_fallback_and_never_resets(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """Two invalid generations (a leaked number): one repair, then the deterministic template."""
    before = list(store.events)
    responder, sink = build_chain(
        store, clock, uow_factory, [GOOD_INTERPRETATION, LEAKED_NUMBER, LEAKED_NUMBER]
    )

    await run_turn(responder, turn_context)

    assert store.session.state is SessionState.ACTIVE
    assert "CALLER_RESPONSE_GENERATED" not in store.event_types, "an invalid draft must not land"
    fallback = store.payloads("MODEL_FALLBACK_USED")[0]
    assert fallback["component"] == "GENERATOR"
    assert fallback["failure_codes"] == ["NEW_NUMBER"]
    assert sink.spoken[0].source == "FALLBACK"
    assert sink.spoken[0].text
    assert_prefix_preserved(before, store.events)


async def test_the_next_turn_is_processed_normally_and_the_failing_turn_is_untouched(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """ "Never silently reset" across turns: turn 0's fallback record survives turn 1 verbatim.

    The responder still runs the generator after an `UNINTELLIGIBLE` interpretation (SPEC §24:
    "the caller still answers"), so turn 0's script also covers that generator call — twice, so it
    too exhausts its repair budget and falls back, exactly as the interpreter did.
    """
    responder, sink = build_chain(
        store,
        clock,
        uow_factory,
        [GARBAGE, GARBAGE, LEAKED_NUMBER, LEAKED_NUMBER, GOOD_INTERPRETATION, GOOD_ANSWER],
    )

    await run_turn(responder, turn_context, turn_index=0)
    turn_0_snapshot = list(store.events)
    await run_turn(responder, turn_context, turn_index=1)

    assert_prefix_preserved(turn_0_snapshot, store.events)
    assert [utterance.source for utterance in sink.spoken] == ["FALLBACK", "LLM"]
    assert sink.spoken[1].text == GOOD_ANSWER["utterance"]
    assert store.session.state is SessionState.ACTIVE
