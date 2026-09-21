"""`DialogueResponder` — the chain behind ASR, in SPEC §16's fixed order (R8, §3.7, §7.7, §7.8).

The first test is the one the rest hang off: the event order is asserted **literally** against
`50-voice-pipeline.md` §3.7's "per-turn event order for a normal turn", up to
`CALLER_RESPONSE_GENERATED`. Everything after that (`CALLER_TTS_*`, `FACTS_DELIVERED`) is E14's and
must therefore be absent — a responder that emitted them would make a fact "revealed" without a
millisecond of audio reaching the trainee (D10, SPEC §42 test 10).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable

import pytest
from app.application.dialogue.dialogue_context import DialogueContextLoader
from app.application.dialogue.fallback_templates_ru import FallbackRow
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
from app.application.ports.llm import LlmTimeoutError
from app.application.ports.metrics_recorder import InferenceStage, NullMetricsRecorder
from app.application.testing.fakes import FakeClock
from app.application.voice.turn_pipeline import TranscribedTurn, TurnContext
from app.domain.enums import GateOutcome
from app.inference.llm.fake_llm import FakeLLM

from tests.unit.application.dialogue._support import scenario_values
from tests.unit.application.dialogue.conftest import (
    DialogueStore,
    InMemoryDialogueUnitOfWork,
    seed_turn_row,
    transcribed_turn,
)

Factory = Callable[[], InMemoryDialogueUnitOfWork]

#: §3.7's documented order for a normal turn, restricted to the events E13 owns.
NORMAL_TURN_ORDER = [
    "DIALOGUE_INTERPRETED",
    "FACT_GATE_EVALUATED",
    "CALLER_RESPONSE_PLANNED",
    "CALLER_RESPONSE_GENERATED",
]

ADDRESS_INTERPRETATION = {
    "speech_act": "QUESTION",
    "requested_facts": [
        {"fact_id": "address.street", "explicit": True},
        {"fact_id": "address.house", "explicit": True},
    ],
    "operator_assertions": [],
    "confirmation_targets": [],
    "semantic_confidence": 0.95,
}
GOOD_ANSWER = {"utterance": "Улица Николаева, дом 27."}
#: The responder runs the gate with the production `max_spontaneous_per_turn = 2`, so every turn
#: also carries the demo's two `SPONTANEOUS` facts until they have been revealed (§10.12).
SPONTANEOUS_IDS = ("incident.type", "incident.smoke_visible")
ADDRESS_IDS = ("address.street", "address.house")
ALLOWED_IDS = (*ADDRESS_IDS, *SPONTANEOUS_IDS)
LEAKY_ANSWER = {"utterance": "Тут ещё 47 человек."}


def build(
    store: DialogueStore,
    clock: FakeClock,
    uow_factory: Factory,
    script: list,
    *,
    sink: NullCallerSpeechSink | None = None,
) -> tuple[DialogueResponder, FakeLLM, NullMetricsRecorder, NullCallerSpeechSink]:
    llm = FakeLLM(script)
    metrics = NullMetricsRecorder()
    speech = sink or NullCallerSpeechSink()
    validator = ResponseValidator(ValidatorConfig(small_count_allowlist=frozenset()))
    responder = DialogueResponder(
        loader=DialogueContextLoader(uow_factory, clock, window_turns=6),  # type: ignore[arg-type]
        interpreter=DialogueInterpreter(llm, metrics, config=InterpreterConfig()),
        generator=CallerResponseGenerator(
            llm,
            metrics,
            CallerPromptBuilder(CallerPromptConfig()),
            validator,
            config=GeneratorConfig(),
        ),
        fallbacks=FallbackTemplates(),
        sink=speech,
        uow_factory=uow_factory,  # type: ignore[arg-type]
    )
    return responder, llm, metrics, speech


async def run_turn(
    responder: DialogueResponder,
    store: DialogueStore,
    context: TurnContext,
    *,
    text: str = "Назовите адрес",
    turn_index: int = 0,
) -> TranscribedTurn:
    turn = transcribed_turn(text, turn_index=turn_index)
    seed_turn_row(store, turn)
    await responder.respond_transcribed(turn, context)
    return turn


# ---------------------------------------------------------------------------------------------
# The order (R8, §3.7)
# ---------------------------------------------------------------------------------------------


async def test_a_normal_turn_emits_the_documented_events_in_the_documented_order(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    responder, _, _, _ = build(store, clock, uow_factory, [ADDRESS_INTERPRETATION, GOOD_ANSWER])

    await run_turn(responder, store, turn_context)

    assert store.event_types == NORMAL_TURN_ORDER


async def test_e13_emits_no_tts_and_no_facts_delivered(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """Shared ruling 5: a fact is revealed by code at `CALLER_TTS_ENDED`, which E14 owns."""
    responder, _, _, _ = build(store, clock, uow_factory, [ADDRESS_INTERPRETATION, GOOD_ANSWER])

    await run_turn(responder, store, turn_context)

    assert not [name for name in store.event_types if name.startswith("CALLER_TTS")]
    assert "FACTS_DELIVERED" not in store.event_types


async def test_the_plan_is_appended_before_any_generation_call(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """§3.5: "so the plan is auditable even if generation fails"."""
    responder, _, _, _ = build(
        store, clock, uow_factory, [ADDRESS_INTERPRETATION, LlmTimeoutError("slow")]
    )

    await run_turn(responder, store, turn_context)

    assert store.event_types.index("CALLER_RESPONSE_PLANNED") < store.event_types.index(
        "MODEL_ERROR"
    )


# ---------------------------------------------------------------------------------------------
# The gate stage
# ---------------------------------------------------------------------------------------------


async def test_the_gate_payload_carries_the_turn_index_the_pipeline_stamped(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """§10.12's signature has no turn index, so the pipeline stamps it (E13-A's open gap)."""
    responder, _, _, _ = build(store, clock, uow_factory, [ADDRESS_INTERPRETATION, GOOD_ANSWER])

    await run_turn(responder, store, turn_context, turn_index=3)

    payload = store.payloads("FACT_GATE_EVALUATED")[0]
    assert payload["turn_index"] == 3
    assert payload["metadata"]["turn_index"] == 3


async def test_the_gate_payload_never_carries_a_world_only_value(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """INV 1 at the event boundary: caller values are allowed here, world-only values never."""
    from tests.unit.application.dialogue._support import demo_definitions

    definitions = demo_definitions()
    responder, _, _, _ = build(store, clock, uow_factory, [ADDRESS_INTERPRETATION, GOOD_ANSWER])

    await run_turn(responder, store, turn_context)

    dumped = json.dumps(store.payloads("FACT_GATE_EVALUATED")[0], ensure_ascii=False)
    world_only = [
        str(definition.world_value)
        for definition in definitions.values()
        if definition.world_value != definition.caller_value
        and not isinstance(definition.world_value, bool)
        and len(str(definition.world_value)) >= 2
    ]
    assert world_only, "the demo scenario must have at least one world-only value"
    assert [value for value in world_only if value in dumped] == []
    assert "неисправная электропроводка" not in dumped


async def test_the_gate_decisions_are_in_the_payload(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    responder, _, _, _ = build(store, clock, uow_factory, [ADDRESS_INTERPRETATION, GOOD_ANSWER])

    await run_turn(responder, store, turn_context)

    payload = store.payloads("FACT_GATE_EVALUATED")[0]
    assert [decision["fact_id"] for decision in payload["decisions"]] == list(ALLOWED_IDS)
    assert {decision["outcome"] for decision in payload["decisions"]} == {
        GateOutcome.ALLOWED.value,
        GateOutcome.ALLOWED_SPONTANEOUS.value,
    }
    assert payload["allowed_fact_ids"] == list(ALLOWED_IDS)
    assert payload["spontaneous_attached"] == list(SPONTANEOUS_IDS)


# ---------------------------------------------------------------------------------------------
# The generation stage
# ---------------------------------------------------------------------------------------------


async def test_a_validated_answer_is_announced_and_handed_to_the_sink(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    responder, _, _, sink = build(store, clock, uow_factory, [ADDRESS_INTERPRETATION, GOOD_ANSWER])

    turn = await run_turn(responder, store, turn_context)

    payload = store.payloads("CALLER_RESPONSE_GENERATED")[0]
    assert payload["utterance_ru"] == "Улица Николаева, дом 27."
    assert payload["validated"] is True
    assert payload["attempt"] == 1
    assert payload["validator_verdict"] == "PASS"
    assert len(sink.spoken) == 1
    assert sink.spoken[0].text == "Улица Николаева, дом 27."
    assert sink.spoken[0].source == "LLM"
    assert sink.spoken[0].turn_id == turn.turn.turn_id
    assert sink.spoken[0].fact_ids == ALLOWED_IDS


async def test_the_sink_is_called_last(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """R5: "after every event and row of the turn is committed"."""
    seen: list[tuple[int, int]] = []

    class Watching(NullCallerSpeechSink):
        async def speak(self, planned, context) -> None:  # type: ignore[no-untyped-def]
            seen.append((len(store.events), len(store.turns.rows)))
            await super().speak(planned, context)

    responder, _, _, _ = build(
        store, clock, uow_factory, [ADDRESS_INTERPRETATION, GOOD_ANSWER], sink=Watching()
    )

    await run_turn(responder, store, turn_context)

    assert seen == [(len(NORMAL_TURN_ORDER), 1)]
    assert store.turns.rows[(store.session.id, 0)].planned_text == "Улица Николаева, дом 27."


async def test_a_regenerated_answer_says_so_in_the_event(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    responder, llm, _, _ = build(
        store, clock, uow_factory, [ADDRESS_INTERPRETATION, LEAKY_ANSWER, GOOD_ANSWER]
    )

    await run_turn(responder, store, turn_context)

    payload = store.payloads("CALLER_RESPONSE_GENERATED")[0]
    assert payload["validator_verdict"] == "REGENERATED"
    assert payload["regeneration_count"] == 1
    assert payload["attempt"] == 2
    assert len(llm.calls) == 3  # one interpreter call + two generator calls


# ---------------------------------------------------------------------------------------------
# The fallback path (SPEC §24: the caller never goes silent)
# ---------------------------------------------------------------------------------------------


async def test_two_invalid_answers_end_in_a_deterministic_fallback(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    responder, llm, _, sink = build(
        store, clock, uow_factory, [ADDRESS_INTERPRETATION, LEAKY_ANSWER, LEAKY_ANSWER]
    )

    await run_turn(responder, store, turn_context)

    assert "CALLER_RESPONSE_GENERATED" not in store.event_types
    fallback = store.payloads("MODEL_FALLBACK_USED")[0]
    assert fallback["component"] == "GENERATOR"
    assert fallback["failure_codes"] == ["NEW_NUMBER"]
    assert sink.spoken[0].source == "FALLBACK"
    assert sink.spoken[0].template_row is FallbackRow.ALLOWED_FACTS
    # §7.8 row 2 caps at three facts and reveals exactly those.
    assert sink.spoken[0].text == "Улица — улица Николаева, Дом — 27, Тип происшествия — пожар."
    assert sink.spoken[0].fact_ids == (*ADDRESS_IDS, "incident.type")
    assert len(llm.calls) == 3


async def test_a_generator_error_emits_model_error_and_still_answers(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """INV 14: the caller does not go silent because a model failed."""
    responder, _, metrics, sink = build(
        store, clock, uow_factory, [ADDRESS_INTERPRETATION, LlmTimeoutError("slow")]
    )

    await run_turn(responder, store, turn_context)

    assert "MODEL_ERROR" in store.event_types
    error = store.payloads("MODEL_ERROR")[0]
    assert error["component"] == "GENERATOR"
    assert error["error_code"] == "LlmTimeoutError"
    assert sink.spoken[0].source == "FALLBACK"
    assert [
        metric.status for metric in metrics.metrics if metric.stage is InferenceStage.LLM_GENERATE
    ] == ["TIMEOUT"]


async def test_an_interpreter_fallback_is_announced_too(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """B1's ladder fell: the responder emits `MODEL_FALLBACK_USED {stage: INTERPRETER}`."""
    responder, _, _, sink = build(
        store, clock, uow_factory, ["not json", "still not json", GOOD_ANSWER]
    )

    await run_turn(responder, store, turn_context)

    fallbacks = store.payloads("MODEL_FALLBACK_USED")
    assert fallbacks[0]["component"] == "INTERPRETER"
    assert fallbacks[0]["fallback_kind"] == "UNINTELLIGIBLE_FALLBACK"
    assert store.event_types[:2] == ["DIALOGUE_INTERPRETED", "MODEL_FALLBACK_USED"]
    # An UNINTELLIGIBLE turn takes §7.8 row 1, whatever the generator would have said.
    assert sink.spoken[0].template_row is FallbackRow.UNINTELLIGIBLE


async def test_a_cancelled_generation_speaks_nothing_and_re_raises(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """A barge-in must stop the turn — no fallback, no sink call, no turn row update."""
    responder, _, _, sink = build(
        store, clock, uow_factory, [ADDRESS_INTERPRETATION, asyncio.CancelledError()]
    )

    with pytest.raises(asyncio.CancelledError):
        await run_turn(responder, store, turn_context)

    assert sink.spoken == []
    assert "MODEL_FALLBACK_USED" not in store.event_types
    assert store.turns.rows[(store.session.id, 0)].planned_text is None


# ---------------------------------------------------------------------------------------------
# The turn row (§20.6) and the real metric ids (R6)
# ---------------------------------------------------------------------------------------------


async def test_the_turn_row_records_the_interpretation_gate_output_and_text(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    responder, _, _, _ = build(store, clock, uow_factory, [ADDRESS_INTERPRETATION, GOOD_ANSWER])

    await run_turn(responder, store, turn_context)

    row = store.turns.rows[(store.session.id, 0)]
    assert row.interpretation["speech_act"] == "QUESTION"
    assert [fact["fact_id"] for fact in row.gate_output["allowed"]] == list(ALLOWED_IDS)
    assert row.planned_text == "Улица Николаева, дом 27."
    assert row.fallback_used is False
    # E12's columns are untouched by E13's pass (§20.6's three-pass rule).
    assert row.operator_transcript_segment_id is not None


async def test_a_fallback_turn_marks_the_row(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    responder, _, _, _ = build(
        store, clock, uow_factory, [ADDRESS_INTERPRETATION, LEAKY_ANSWER, LEAKY_ANSWER]
    )

    await run_turn(responder, store, turn_context)

    assert store.turns.rows[(store.session.id, 0)].fallback_used is True


async def test_every_metric_of_the_turn_carries_the_real_session_and_turn_ids(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """R6: B1's uuid5 stand-ins are replaced once the pipeline has the real ids."""
    responder, _, metrics, _ = build(
        store, clock, uow_factory, [ADDRESS_INTERPRETATION, GOOD_ANSWER]
    )

    turn = await run_turn(responder, store, turn_context)

    assert [metric.stage for metric in metrics.metrics] == [
        InferenceStage.LLM_INTERPRET,
        InferenceStage.LLM_GENERATE,
    ]
    assert all(metric.session_id == uuid.UUID(str(store.session.id)) for metric in metrics.metrics)
    assert all(metric.turn_id == turn.turn.turn_id for metric in metrics.metrics)


# ---------------------------------------------------------------------------------------------
# The information boundary, end to end
# ---------------------------------------------------------------------------------------------


async def test_no_prompt_of_the_turn_carries_a_value_outside_the_package(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory, turn_context: TurnContext
) -> None:
    """SPEC §21 over a whole turn: only the two released values may appear in any prompt."""
    from app.application.dialogue.text_normalization import normalize_text

    from tests.unit.application.dialogue._support import demo_definitions

    responder, llm, _, _ = build(store, clock, uow_factory, [ADDRESS_INTERPRETATION, GOOD_ANSWER])

    await run_turn(responder, store, turn_context)

    # The two facts asked about, plus the two the gate attached spontaneously.
    released = {"улица Николаева", "27", "FIRE", "да"}
    rendered = "\n".join(message.content for call in llm.calls for message in call.messages)
    haystack = normalize_text(rendered).texts
    leaked = [
        value
        for value in scenario_values(demo_definitions())
        if value not in released and _contains(haystack, normalize_text(value).texts)
    ]
    assert leaked == []


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[start : start + len(needle)] == needle
        for start in range(len(haystack) - len(needle) + 1)
    )
