"""`DialogueInterpreter.interpret` takes the real session/turn ids (R6, SPEC §27).

E13-B1 had to derive `InferenceMetric.session_id`/`turn_id` with `uuid5` because §5.1's signature
carries only a `request_id` and a `turn_index` — an HLD gap that file's own comment records. The
turn pipeline does have the real ids, so `interpret()` now accepts them as **optional** keyword
arguments: every existing caller keeps the reproducible stand-ins, and the responder hands over the
ids an instructor can actually join `inference_metrics` on.

A separate file from `test_interpreter.py` on purpose: that one belongs to E13-B3.
"""

from __future__ import annotations

import uuid

from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
from app.application.ports.metrics_recorder import InferenceStage, NullMetricsRecorder
from app.domain.facts.definitions import FactCatalog
from app.inference.llm.fake_llm import FakeLLM

SESSION_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TURN_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
REQUEST_ID = "turn-7:interpret"

GOOD = {
    "speech_act": "QUESTION",
    "requested_facts": [],
    "operator_assertions": [],
    "confirmation_targets": [],
    "semantic_confidence": 0.9,
}


def make(script: list) -> tuple[DialogueInterpreter, NullMetricsRecorder]:
    metrics = NullMetricsRecorder()
    return DialogueInterpreter(FakeLLM(script), metrics, config=InterpreterConfig()), metrics


async def test_the_supplied_ids_reach_the_metric_row() -> None:
    interpreter, metrics = make([GOOD])

    await interpreter.interpret(
        "Назовите адрес",
        (),
        FactCatalog(),
        request_id=REQUEST_ID,
        turn_index=7,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
    )

    assert [metric.stage for metric in metrics.metrics] == [InferenceStage.LLM_INTERPRET]
    assert metrics.metrics[0].session_id == SESSION_ID
    assert metrics.metrics[0].turn_id == TURN_ID


async def test_the_repair_call_carries_the_same_ids() -> None:
    """Both calls of one turn must join to the same turn row (SPEC §27)."""
    interpreter, metrics = make(["not json", GOOD])

    await interpreter.interpret(
        "Назовите адрес",
        (),
        FactCatalog(),
        request_id=REQUEST_ID,
        turn_index=7,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
    )

    assert len(metrics.metrics) == 2
    assert {metric.session_id for metric in metrics.metrics} == {SESSION_ID}
    assert {metric.turn_id for metric in metrics.metrics} == {TURN_ID}


async def test_without_the_ids_the_deterministic_stand_ins_are_kept() -> None:
    """B1's callers keep working: the fallback is the documented `uuid5` of the request id."""
    interpreter, metrics = make([GOOD])

    await interpreter.interpret(
        "Назовите адрес", (), FactCatalog(), request_id=REQUEST_ID, turn_index=7
    )

    expected = uuid.uuid5(uuid.NAMESPACE_URL, f"sim-112:interpret:{REQUEST_ID}")
    assert metrics.metrics[0].session_id == expected
    assert metrics.metrics[0].session_id != SESSION_ID


async def test_the_stand_in_is_reproducible_for_the_same_request_id() -> None:
    first, first_metrics = make([GOOD])
    second, second_metrics = make([GOOD])

    await first.interpret("а", (), FactCatalog(), request_id=REQUEST_ID, turn_index=0)
    await second.interpret("б", (), FactCatalog(), request_id=REQUEST_ID, turn_index=0)

    assert first_metrics.metrics[0].session_id == second_metrics.metrics[0].session_id
