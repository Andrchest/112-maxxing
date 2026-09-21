"""Gate-side tests for `benchmarks/caller_eval/scoring.py` and `cases_ru.yaml` (E13-B4, CHANGE
item 2, TESTS).

`scoring.py` lives in the `benchmarks` uv-workspace member (`package = false`, never installed into
`sys.path`), loaded here by file path exactly like `test_eval_scoring.py` loads the interpreter
eval's `scoring.py`. No server, no LLM — these tests build `CaseOutcome` rows by hand and check
`aggregate()`'s arithmetic, and separately parse `cases_ru.yaml` and check it against the real demo
scenario's fact catalog the same way `run_eval.py`'s own `_validate_cases_against_catalog` does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import yaml
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion

REPO_ROOT = Path(__file__).resolve().parents[5]
SCORING_PATH = REPO_ROOT / "benchmarks" / "caller_eval" / "scoring.py"
CASES_PATH = REPO_ROOT / "benchmarks" / "caller_eval" / "cases_ru.yaml"


def _load_scoring() -> ModuleType:
    spec = importlib.util.spec_from_file_location("caller_eval_scoring", SCORING_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scoring = _load_scoring()


def _outcome(case_id: str, **overrides: object) -> object:
    defaults: dict[str, object] = {
        "case_id": case_id,
        "category": "facts_known",
        "attempt1_ok": True,
        "attempt1_codes": (),
        "attempt2_ok": None,
        "fallback_row": None,
        "final_text": "Улица Николаева.",
        "latency_ms": 200.0,
        "prompt_tokens": 500,
        "completion_tokens": 20,
        "final_text_has_forbidden_value": False,
        "raw_attempt1_has_forbidden_value": False,
    }
    defaults.update(overrides)
    return scoring.CaseOutcome(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# scoring.py
# ---------------------------------------------------------------------------------------------


def test_percentile_matches_known_values() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert scoring.percentile(values, 0.0) == 10.0
    assert scoring.percentile(values, 1.0) == 40.0
    assert scoring.percentile([], 0.5) is None


def test_aggregate_of_no_cases_is_n_zero() -> None:
    assert scoring.aggregate([]) == {"n": 0}


def test_aggregate_rates_over_several_cases() -> None:
    outcomes = [
        _outcome("a", attempt1_ok=True, latency_ms=100.0, completion_tokens=10),
        _outcome(
            "b",
            attempt1_ok=False,
            attempt1_codes=("NEW_NUMBER",),
            attempt2_ok=True,
            latency_ms=200.0,
            completion_tokens=20,
        ),
        _outcome(
            "c",
            attempt1_ok=False,
            attempt1_codes=("META_LANGUAGE",),
            attempt2_ok=False,
            fallback_row=2,
            latency_ms=300.0,
            completion_tokens=15,
            raw_attempt1_has_forbidden_value=True,
        ),
    ]

    summary = scoring.aggregate(outcomes)

    assert summary["n"] == 3
    # a: validated first try. b, c: not.
    assert summary["validated_first_try_rate"] == 1 / 3
    # b and c both had a second attempt.
    assert summary["regeneration_rate"] == 2 / 3
    # only c fell back to §7.8.
    assert summary["fallback_rate"] == 1 / 3
    # only c's raw attempt-1 leaked.
    assert summary["raw_model_leak_rate"] == 1 / 3
    # the FINAL text never leaks in this fixture — the deterministic boundary.
    assert summary["forbidden_fact_leak_rate"] == 0.0
    assert summary["latency_ms_p50"] == 200.0
    assert summary["completion_tokens_p50"] == 15.0


def test_forbidden_fact_leak_rate_reflects_the_final_text_not_the_raw_one() -> None:
    """A raw-attempt-1 leak that the validator caught must not count against the FINAL rate; a
    leak that somehow reached the final text must."""
    outcomes = [
        _outcome("clean_raw_leak", raw_attempt1_has_forbidden_value=True),
        _outcome("dirty_final", final_text_has_forbidden_value=True),
    ]

    summary = scoring.aggregate(outcomes)

    assert summary["raw_model_leak_rate"] == 0.5
    assert summary["forbidden_fact_leak_rate"] == 0.5


def test_tokens_per_second_is_none_without_any_timed_completion() -> None:
    outcomes = [_outcome("a", latency_ms=None, completion_tokens=None)]
    summary = scoring.aggregate(outcomes)
    assert summary["tokens_per_second_mean"] is None
    assert summary["latency_ms_p50"] is None


# ---------------------------------------------------------------------------------------------
# cases_ru.yaml
# ---------------------------------------------------------------------------------------------


def _document() -> dict[str, object]:
    return yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))


def test_cases_file_parses_and_has_at_least_forty_cases() -> None:
    document = _document()
    cases = document["cases"]
    assert len(cases) >= 40


def test_cases_cover_all_ten_spec_43_categories() -> None:
    expected = {
        "facts_known",
        "facts_unknown",
        "incorrect_assumptions",
        "leading_questions",
        "numerics",
        "addresses",
        "names",
        "hazards",
        "victims",
        "causes",
    }
    categories = {case["category"] for case in _document()["cases"]}
    assert categories == expected


def test_case_ids_are_unique() -> None:
    ids = [case["id"] for case in _document()["cases"]]
    assert len(ids) == len(set(ids))


def test_every_case_references_only_fact_ids_in_the_demo_scenario() -> None:
    document = _document()
    scenario_path = REPO_ROOT / document["scenario"]
    version = ScenarioVersion.model_validate(
        yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    )
    catalog_ids = set(build_fact_definitions(version))

    for case in document["cases"]:
        interpreted = case["interpreted"]
        ids = (
            {f["fact_id"] for f in interpreted["requested_facts"]}
            | {a["fact_id"] for a in interpreted["operator_assertions"]}
            | set(interpreted["confirmation_targets"])
        )
        unknown = ids - catalog_ids
        assert not unknown, f"case {case['id']!r} references unknown fact id(s): {unknown}"


def test_every_case_has_the_fields_run_eval_needs() -> None:
    required_top = {"id", "category", "operator_utterance", "session_offset_ms", "interpreted"}
    required_interpreted = {
        "speech_act",
        "requested_facts",
        "operator_assertions",
        "confirmation_targets",
        "semantic_confidence",
    }
    for case in _document()["cases"]:
        assert required_top <= set(case), case["id"]
        assert required_interpreted <= set(case["interpreted"]), case["id"]
        for fact in case["interpreted"]["requested_facts"]:
            assert set(fact) == {"fact_id", "explicit"}
