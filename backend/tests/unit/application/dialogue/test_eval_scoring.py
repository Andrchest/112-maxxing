"""Gate-side test for `benchmarks/interpreter_eval/scoring.py` (this task's brief, CHANGE item 6:
"A gate-side unit test runs the tool's scoring functions against FakeLLM (no server).").

`scoring.py` lives in the `benchmarks` uv-workspace member, which is `package = false` (never
installed into `sys.path` the way `backend`/`workers/voice_agent` are) — it is loaded here by file
path rather than a normal import, exactly like `run_eval.py` loads it when run as a script. This
keeps `scoring.py` itself dependency-free (stdlib only) and this test needs no llama-server: it
drives the real `DialogueInterpreter` against `FakeLLM`, then scores the result.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.domain.facts.definitions import FactCatalog, FactCatalogEntry
from app.inference.llm.fake_llm import FakeLLM

REPO_ROOT = Path(__file__).resolve().parents[5]
SCORING_PATH = REPO_ROOT / "benchmarks" / "interpreter_eval" / "scoring.py"


def _load_scoring() -> ModuleType:
    spec = importlib.util.spec_from_file_location("interpreter_eval_scoring", SCORING_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scoring = _load_scoring()


def _catalog(*fact_ids: str) -> FactCatalog:
    return FactCatalog(
        FactCatalogEntry(fact_id=fact_id, label_ru=fact_id, aliases_ru=(), categories=())
        for fact_id in fact_ids
    )


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "speech_act": "QUESTION",
        "requested_facts": [{"fact_id": "address.street", "explicit": True}],
        "operator_assertions": [],
        "confirmation_targets": [],
        "semantic_confidence": 0.9,
    }
    payload.update(overrides)
    return payload


async def test_a_correct_call_scores_a_perfect_match() -> None:
    llm = FakeLLM([_valid_payload()])
    interpreter = DialogueInterpreter(llm, NullMetricsRecorder(), config=InterpreterConfig())

    outcome = await interpreter.interpret(
        "На какой улице это произошло?",
        (),
        _catalog("address.street"),
        request_id="r1",
        turn_index=0,
    )

    expected = {
        "speech_act": "QUESTION",
        "requested_facts": [{"fact_id": "address.street", "explicit": True}],
        "operator_assertions": [],
        "confirmation_targets": [],
    }
    scored = scoring.score_call(
        item_id="question_street_only",
        expected=expected,
        actual=outcome.interpretation.model_dump(mode="json"),
        fallback_used=outcome.fallback_used,
        repair_retry_used=outcome.repair_retry_used,
        latency_ms=42.0,
        completion_tokens=30,
    )

    assert scored.speech_act_correct is True
    assert scored.requested_precision == 1.0
    assert scored.requested_recall == 1.0
    assert scored.requested_exact_match is True
    assert scored.explicit_correct == 1
    assert scored.explicit_total == 1
    assert scored.fallback_used is False


async def test_a_missed_fact_lowers_recall_but_not_precision() -> None:
    llm = FakeLLM([_valid_payload(requested_facts=[])])
    interpreter = DialogueInterpreter(llm, NullMetricsRecorder(), config=InterpreterConfig())

    outcome = await interpreter.interpret(
        "На какой улице это произошло?",
        (),
        _catalog("address.street"),
        request_id="r1",
        turn_index=0,
    )

    expected = {
        "speech_act": "QUESTION",
        "requested_facts": [{"fact_id": "address.street", "explicit": True}],
        "operator_assertions": [],
        "confirmation_targets": [],
    }
    scored = scoring.score_call(
        item_id="question_street_only",
        expected=expected,
        actual=outcome.interpretation.model_dump(mode="json"),
    )

    assert scored.requested_recall == 0.0
    assert scored.requested_precision == 0.0  # actual is empty too: 0/expected non-empty
    assert scored.requested_exact_match is False


async def test_a_spurious_fact_lowers_precision_but_not_recall() -> None:
    llm = FakeLLM(
        [
            _valid_payload(
                requested_facts=[
                    {"fact_id": "address.street", "explicit": True},
                    {"fact_id": "address.house", "explicit": True},
                ]
            )
        ]
    )
    interpreter = DialogueInterpreter(llm, NullMetricsRecorder(), config=InterpreterConfig())

    outcome = await interpreter.interpret(
        "На какой улице это произошло?",
        (),
        _catalog("address.street", "address.house"),
        request_id="r1",
        turn_index=0,
    )

    expected = {
        "speech_act": "QUESTION",
        "requested_facts": [{"fact_id": "address.street", "explicit": True}],
        "operator_assertions": [],
        "confirmation_targets": [],
    }
    scored = scoring.score_call(
        item_id="question_street_only",
        expected=expected,
        actual=outcome.interpretation.model_dump(mode="json"),
    )

    assert scored.requested_recall == 1.0
    assert scored.requested_precision == 0.5
    assert scored.requested_exact_match is False


async def test_a_fallback_is_scored_as_a_speech_act_mismatch_not_an_exception() -> None:
    llm = FakeLLM(["мусор 1", "мусор 2"])
    interpreter = DialogueInterpreter(llm, NullMetricsRecorder(), config=InterpreterConfig())

    outcome = await interpreter.interpret(
        "Какой у вас адрес?", (), _catalog("address.street"), request_id="r1", turn_index=0
    )

    expected = {
        "speech_act": "QUESTION",
        "requested_facts": [{"fact_id": "address.street", "explicit": True}],
        "operator_assertions": [],
        "confirmation_targets": [],
    }
    scored = scoring.score_call(
        item_id="question_street_only",
        expected=expected,
        actual=outcome.interpretation.model_dump(mode="json"),
        fallback_used=outcome.fallback_used,
        repair_retry_used=outcome.repair_retry_used,
    )

    assert scored.fallback_used is True
    assert scored.repair_retry_used is True
    assert scored.speech_act_correct is False  # fallback's UNINTELLIGIBLE != QUESTION


def test_percentile_matches_known_values() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert scoring.percentile(values, 0.0) == 10.0
    assert scoring.percentile(values, 1.0) == 40.0
    assert scoring.percentile([], 0.5) is None
    assert scoring.percentile([7.0], 0.5) == 7.0


def test_aggregate_rates_and_counts_over_several_scored_calls() -> None:
    scored = [
        scoring.score_call(
            item_id="a",
            expected={
                "speech_act": "QUESTION",
                "requested_facts": [{"fact_id": "x", "explicit": True}],
                "operator_assertions": [],
                "confirmation_targets": [],
            },
            actual={
                "speech_act": "QUESTION",
                "requested_facts": [{"fact_id": "x", "explicit": True}],
                "operator_assertions": [],
                "confirmation_targets": [],
            },
            latency_ms=100.0,
            completion_tokens=20,
        ),
        scoring.score_call(
            item_id="b",
            expected={
                "speech_act": "GREETING",
                "requested_facts": [],
                "operator_assertions": [],
                "confirmation_targets": [],
            },
            actual={
                "speech_act": "CLOSING",
                "requested_facts": [],
                "operator_assertions": [],
                "confirmation_targets": [],
            },
            fallback_used=True,
            think_leak=True,
            latency_ms=200.0,
            completion_tokens=10,
        ),
    ]
    summary = scoring.aggregate(scored)
    assert summary["n"] == 2
    assert summary["speech_act_accuracy"] == 0.5
    assert summary["fallback_rate"] == 0.5
    assert summary["think_leak_count"] == 1
    assert summary["latency_ms_p50"] == 150.0
    assert summary["completion_tokens_p99"] is not None


def test_aggregate_of_no_calls_is_n_zero() -> None:
    assert scoring.aggregate([]) == {"n": 0}


def _scored(item_id: str, *, speech_act_correct: bool) -> object:
    speech_act = "QUESTION" if speech_act_correct else "GREETING"
    return scoring.score_call(
        item_id=item_id,
        expected={
            "speech_act": "QUESTION",
            "requested_facts": [],
            "operator_assertions": [],
            "confirmation_targets": [],
        },
        actual={
            "speech_act": speech_act,
            "requested_facts": [],
            "operator_assertions": [],
            "confirmation_targets": [],
        },
        latency_ms=100.0,
        completion_tokens=10,
    )


def test_aggregate_by_uncertainty_reports_every_metric_twice() -> None:
    """E13-B4 item 1 (MANAGER RULING): the five `uncertain: true` labels stay flagged, not
    changed — `aggregate_by_uncertainty` only changes which items feed the second aggregate."""
    scored = [
        _scored("known_good", speech_act_correct=True),
        _scored("known_good_2", speech_act_correct=True),
        _scored("uncertain_bad", speech_act_correct=False),
    ]

    both = scoring.aggregate_by_uncertainty(scored, frozenset({"uncertain_bad"}))

    assert set(both) == {"all", "excluding_uncertain"}
    assert both["all"]["n"] == 3
    assert both["all"]["speech_act_accuracy"] == 2 / 3
    assert both["excluding_uncertain"]["n"] == 2
    assert both["excluding_uncertain"]["speech_act_accuracy"] == 1.0
    # Every metric `aggregate()` reports appears in both dicts (the same key set).
    assert set(both["all"]) == set(both["excluding_uncertain"])


def test_aggregate_by_uncertainty_with_no_uncertain_ids_is_identical_to_aggregate() -> None:
    scored = [_scored("a", speech_act_correct=True), _scored("b", speech_act_correct=False)]

    both = scoring.aggregate_by_uncertainty(scored, frozenset())

    assert both["all"] == scoring.aggregate(scored)
    assert both["excluding_uncertain"] == scoring.aggregate(scored)


def test_aggregate_by_uncertainty_excluding_everything_is_n_zero() -> None:
    scored = [_scored("only_uncertain", speech_act_correct=True)]

    both = scoring.aggregate_by_uncertainty(scored, frozenset({"only_uncertain"}))

    assert both["all"]["n"] == 1
    assert both["excluding_uncertain"] == {"n": 0}
