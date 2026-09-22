#!/usr/bin/env python
"""LLM benchmark (SPEC §20-§22, §35, §40, §43; HLD `60-inference-ops.md` §7.2).

Three suites, selected with `--suite interpreter|dialogue|explanation|all` (the flag is additive
to HLD §7.2, this epic's R6):

* **interpreter** — `benchmarks/data/llm/interpreter_cases.jsonl` through the real
  `DialogueInterpreter`. Every metric is reported **twice**, all / excluding `uncertain`, exactly
  as the interpreter eval already does (E13-B3); the per-item scoring is *reused* from
  `benchmarks/interpreter_eval/scoring.py` (a stdlib-only pure module) rather than reimplemented.
* **dialogue** — `benchmarks/data/llm/dialogue_cases.jsonl`, multi-turn scripts through the real
  `CallerResponseGenerator` + `ResponseValidator`. `dialogue_consistency_rate` is an **exact
  canonical comparison** of the values a fact came back with when it was asked twice (§7.2's
  numeral folding), never a model judging another model (HLD §7.2, SPEC §44).
* **explanation** — the E16 explanation prompt (`app.application.reports.explanation.prompt`)
  over a fixture `ScoreReport`, which is what closes `docs/hld/60-inference-ops.md` §12's
  open E19 item (a real-model latency number for `SIM_EXPLANATION_*`).

`forbidden_fact_leak` is measured per sample at the **output** boundary with the product's own
`forbidden_values()` over that turn's `AllowedFactsPackage`, and the SPEC §43 attack matrix is
**reused** from `backend/tests/adversarial/test_forbidden_fact_leak_suite.py` (D13, HLD §7.2:
"rather than duplicating"). `_common.ensure_backend_on_path()` is what makes that import possible;
benchmarks are dev tooling and that allowance is documented there and in `benchmarks/README.md`.

`--provider real` starts one llama-server through the `backend/tests/models/` harness (see
`benchmarks/_llama.py`) unless `--base-url` points at a running one; `--provider fake` drives the
D13 `FakeLLM` — the gate's shape run.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import sys
import time
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from _common import (
    REPO_ROOT,
    Envelope,
    NvmlSampler,
    aggregate,
    elapsed_ms,
    ensure_backend_on_path,
    finish,
    fold,
    load_jsonl,
    load_profile_for_bench,
    not_run,
    parse_common_args,
    profile_config_subtree,
    rate,
    resolve_model_path,
)

BENCHMARK = "llm"
DATA = Path("benchmarks/data/llm")
SUITES = ("interpreter", "dialogue", "explanation")


def _extra(parser: Any) -> None:
    parser.add_argument(
        "--suite", choices=(*SUITES, "all"), default="all", help="which sub-suite(s) to run"
    )
    parser.add_argument("--interpreter-cases", type=Path, default=DATA / "interpreter_cases.jsonl")
    parser.add_argument("--dialogue-cases", type=Path, default=DATA / "dialogue_cases.jsonl")
    parser.add_argument(
        "--explanation-fixture",
        type=Path,
        default=DATA / "explanation_fixture.json",
        help="the committed ScoreReport the explanation suite explains (E19-C)",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=None,
        help="GGUF to serve instead of the profile's (the owner's read-only GGUFs go here)",
    )
    parser.add_argument("--parallel", type=int, default=None, help="llama-server --parallel slots")
    parser.add_argument(
        "--warmup",
        type=int,
        default=2,
        help="throw-away completions before the first measured sample (real provider only)",
    )
    parser.add_argument(
        "--llama-server-bin",
        default=None,
        help="llama-server binary to try first (env: SIM_LLAMA_SERVER_BIN)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="an ALREADY-RUNNING llama-server's OpenAI base URL; no server is started or stopped",
    )


def _scoring() -> Any:
    """`benchmarks/interpreter_eval/scoring.py`, loaded by path — reused, never copied."""
    name = "interpreter_eval_scoring"
    if name in sys.modules:
        return sys.modules[name]
    path = REPO_ROOT / "benchmarks" / "interpreter_eval" / "scoring.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - the file is committed
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` resolves annotations through `sys.modules[cls.__module__]`, so the module has
    # to be registered before it is executed, not after.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _setting_defaults(*names: str) -> dict[str, Any]:
    """The product's own default for each `Settings` field (E19-C).

    `InterpreterConfig()`/`GeneratorConfig()`'s *dataclass* defaults are not the product's: the
    interpreter's dataclass says `max_tokens=200` while `Settings.llm_interpreter_max_tokens` — the
    number E13-B3 measured and the product actually ships (138) — lives on `Settings`, and
    `interpreter_config_from_settings` is what joins them. A benchmark that used the dataclass
    default would measure a configuration nobody runs, so the defaults are read off the `Settings`
    class here. `Settings()` itself cannot be instantiated without a database/LiveKit/LLM URL, and
    a benchmark has no business inventing those, so only the field defaults are read.
    """
    from app.config.settings import Settings

    return {name: Settings.model_fields[name].default for name in names}


def _adversarial() -> Any:
    """The SPEC §43 attack matrix and gate helpers, imported from `backend/tests/adversarial/`."""
    ensure_backend_on_path()
    import tests.adversarial.test_forbidden_fact_leak_suite as suite

    return suite


# ---------------------------------------------------------------------------------------------
# Suites
# ---------------------------------------------------------------------------------------------


async def _interpreter_suite(args: Any, llm: Any, envelope: Envelope) -> list[dict[str, Any]]:
    import yaml
    from app.application.dialogue.catalog import build_fact_catalog
    from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
    from app.application.ports.metrics_recorder import NullMetricsRecorder
    from app.domain.scenario.validation import build_fact_definitions
    from app.domain.scenario.version import ScenarioVersion

    rows = load_jsonl(args.interpreter_cases)
    scenario = REPO_ROOT / str(rows[0].get("scenario", "scenarios/examples/apartment-fire/v1.yaml"))
    version = ScenarioVersion.model_validate(yaml.safe_load(scenario.read_text(encoding="utf-8")))
    catalog = build_fact_catalog(build_fact_definitions(version))

    if args.provider == "fake":
        llm = _scripted_interpreter_llm(rows, args.runs)
    metrics = NullMetricsRecorder()
    settings = _setting_defaults(
        "llm_interpreter_max_tokens", "llm_interpreter_timeout_ms", "llm_interpreter_use_grammar"
    )
    config = InterpreterConfig(
        max_tokens=settings["llm_interpreter_max_tokens"],
        timeout_ms=settings["llm_interpreter_timeout_ms"],
        use_grammar=settings["llm_interpreter_use_grammar"],
    )
    envelope.config["interpreter"] = {
        "max_tokens": config.max_tokens,
        "timeout_ms": config.timeout_ms,
        "use_grammar": config.use_grammar,
    }
    interpreter = DialogueInterpreter(llm, metrics, config=config)
    scoring = _scoring()

    samples: list[dict[str, Any]] = []
    for run_index in range(max(1, args.runs)):
        for index, row in enumerate(rows):
            before = len(metrics.metrics)
            started = time.perf_counter()
            outcome = await interpreter.interpret(
                str(row["utterance"]),
                (),
                catalog,
                request_id=f"bench-llm-interp:{row['id']}:{run_index}",
                turn_index=index,
            )
            total_ms = elapsed_ms(started)
            call_metrics = metrics.metrics[before:]
            output_tokens = sum(m.output_tokens or 0 for m in call_metrics) or None
            ttft_ms = next((m.ttft_ms for m in call_metrics if m.ttft_ms is not None), None)
            actual = outcome.interpretation.model_dump(mode="json")
            scored = scoring.score_call(
                item_id=str(row["id"]),
                expected=row["expected"],
                actual=actual,
                fallback_used=outcome.fallback_used,
                repair_retry_used=outcome.repair_retry_used,
                latency_ms=total_ms,
                completion_tokens=output_tokens,
            )
            text = json.dumps(actual, ensure_ascii=False)
            samples.append(
                {
                    "id": row["id"],
                    "run_index": run_index,
                    "suite": "interpreter",
                    "uncertain": bool(row.get("uncertain", False)),
                    "ttft_ms": ttft_ms,
                    "total_latency_ms": round(total_ms, 3),
                    "output_tokens": output_tokens,
                    "tokens_per_second": _tps(output_tokens, total_ms),
                    "output_chars": len(text),
                    "chars_per_output_token": round(len(text) / output_tokens, 3)
                    if output_tokens
                    else None,
                    "structured_output_valid": not outcome.fallback_used,
                    "repair_used": outcome.repair_retry_used,
                    "forbidden_fact_leak": False,
                    "validator_failure_codes": [],
                    "speech_act_correct": scored.speech_act_correct,
                    "requested_exact_match": scored.requested_exact_match,
                    "requested_precision": scored.requested_precision,
                    "requested_recall": scored.requested_recall,
                    "explicit_correct": scored.explicit_correct,
                    "explicit_total": scored.explicit_total,
                }
            )
    envelope.note(f"interpreter suite: {len(rows)} cases x {max(1, args.runs)} run(s)")
    return samples


def _scripted_interpreter_llm(rows: list[dict[str, Any]], runs: int) -> Any:
    """A `FakeLLM` that answers each case with its own labelled `expected` block (D13).

    The fake therefore produces a schema-valid answer for every case, which is what makes the
    gate-side run a *shape* test (`status: OK`, a complete envelope) and never a quality claim.
    """
    from app.inference.llm.fake_llm import FakeLLM

    script: list[str] = []
    for _run in range(max(1, runs)):
        for row in rows:
            expected = row["expected"]
            script.append(
                json.dumps(
                    {
                        "speech_act": expected["speech_act"],
                        "requested_facts": expected.get("requested_facts", []),
                        "operator_assertions": expected.get("operator_assertions", []),
                        "confirmation_targets": expected.get("confirmation_targets", []),
                        "semantic_confidence": 0.9,
                    },
                    ensure_ascii=False,
                )
            )
    return FakeLLM(script)


async def _dialogue_suite(args: Any, llm: Any, envelope: Envelope) -> list[dict[str, Any]]:
    """Multi-turn scripts: a fact asked twice must come back with the same canonical value."""
    from app.application.dialogue.fallbacks import FallbackTemplates
    from app.application.dialogue.forbidden_values import forbidden_values
    from app.application.dialogue.generator import (
        CallerResponseGenerator,
        GeneratorConfig,
        ValidationInputs,
    )
    from app.application.dialogue.prompt_builder import CallerPromptBuilder, CallerPromptConfig
    from app.application.dialogue.validator import ResponseValidator, ValidatorConfig
    from app.application.ports.metrics_recorder import NullMetricsRecorder

    suite = _adversarial()
    rows = load_jsonl(args.dialogue_cases)
    metrics = NullMetricsRecorder()
    samples: list[dict[str, Any]] = []
    settings = _setting_defaults(
        "llm_generator_max_tokens",
        "llm_generator_temperature",
        "llm_generator_top_p",
        "llm_generator_timeout_ms",
        "llm_generator_use_grammar",
    )
    #: `generator_config_from_settings`, built from the product's own defaults (see
    #: `_setting_defaults`) so the benchmark measures the shipped 80-token, grammar-on call.
    generator_config = GeneratorConfig(
        max_tokens=settings["llm_generator_max_tokens"],
        temperature=settings["llm_generator_temperature"],
        top_p=settings["llm_generator_top_p"],
        timeout_ms=settings["llm_generator_timeout_ms"],
        use_grammar=settings["llm_generator_use_grammar"],
    )
    envelope.config["generator"] = {
        "max_tokens": generator_config.max_tokens,
        "timeout_ms": generator_config.timeout_ms,
        "use_grammar": generator_config.use_grammar,
        "temperature": generator_config.temperature,
        "top_p": generator_config.top_p,
    }
    #: R13/E19-C2: the dialogue suite measures the PRODUCT chain, so it runs the **product's**
    #: `ValidatorConfig` (`validator_config_from_settings`' three settings, with the default
    #: `small_count_allowlist={"0","1","2","3"}`). The §43 suite's `STRICT` config — which empties
    #: that allowlist — belongs to the adversarial leak sub-suite and is not the shipped gate; using
    #: it here counted «3» (подъезд) and «1» (один человек) as `NEW_NUMBER`, which no deployment
    #: does. The forbidden-value scan below is unaffected: `leaked_values`/`forbidden_values` take
    #: no `ValidatorConfig` at all, so §43's measurement keeps its own strictness.
    validator_settings = _setting_defaults(
        "caller_max_chars", "caller_max_sentences", "llm_generator_max_tokens"
    )
    validator_config = ValidatorConfig(
        max_chars=validator_settings["caller_max_chars"],
        max_sentences=validator_settings["caller_max_sentences"],
        max_response_tokens=validator_settings["llm_generator_max_tokens"],
    )
    envelope.config["validator"] = {
        "source": "product defaults (validator_config_from_settings)",
        "max_chars": validator_config.max_chars,
        "max_sentences": validator_config.max_sentences,
        "max_response_tokens": validator_config.max_response_tokens,
        "small_count_allowlist": sorted(validator_config.small_count_allowlist),
    }

    for run_index in range(max(1, args.runs)):
        for row in rows:
            revealed: set[str] = set()
            seen: dict[str, tuple[str, ...] | None] = {}
            for turn_index, turn in enumerate(row["turns"]):
                fact_ids = tuple(turn.get("fact_ids", ()))
                probe = suite.Probe(
                    category=str(row.get("category", "dialogue")),
                    utterance=str(turn["utterance"]),
                    fact_ids=fact_ids,
                    explicit=bool(turn.get("explicit", True)),
                )
                package = suite.gate_for(probe, frozenset(revealed))
                forbidden = forbidden_values(suite.DEFINITIONS, package, frozenset(revealed))
                turn_llm = _scripted_dialogue_llm(package) if args.provider == "fake" else llm
                generator = CallerResponseGenerator(
                    turn_llm,
                    metrics,
                    CallerPromptBuilder(CallerPromptConfig()),
                    ResponseValidator(validator_config),
                    config=generator_config,
                )
                before = len(metrics.metrics)
                started = time.perf_counter()
                response = await generator.generate(
                    package,
                    suite.PROFILE,
                    suite.EMOTION,
                    (),
                    (),
                    probe.utterance,
                    inputs=ValidationInputs(
                        revealed_values=(),
                        operator_utterances=(probe.utterance,),
                        persona_whitelist=suite.PROFILE.persona_whitelist_ru,
                        forbidden_values=forbidden,
                    ),
                    session_id=suite.SESSION_ID,
                    turn_id=uuid.uuid4(),
                    request_id=f"bench-llm-dlg:{row['id']}:{turn_index}:{run_index}",
                )
                total_ms = elapsed_ms(started)
                call_metrics = metrics.metrics[before:]
                output_tokens = sum(m.output_tokens or 0 for m in call_metrics) or None
                if response.validated:
                    spoken, from_fallback = response.utterance, False
                else:
                    spoken = FallbackTemplates().select(package, suite.interpreted(*fact_ids)).text
                    from_fallback = True
                leaked = suite.leaked_values(
                    spoken, package, frozenset(revealed), check_enum_ru=True
                )
                delivered = _delivered_values(package, spoken)
                # A fact asked a second time is scored only when the caller actually SAID the
                # value at least once: two turns that both said nothing about the fact agree
                # trivially, and counting that as "consistent" would let a model that never
                # answers score 1.0 (E19-C fix; the pairs are counted separately instead).
                consistent: bool | None = None
                undelivered_repeats = 0
                for fact_id in fact_ids:
                    value = delivered.get(fact_id)
                    if fact_id in seen:
                        previous = seen[fact_id]
                        if previous is None and value is None:
                            undelivered_repeats += 1
                            continue
                        consistent = bool(consistent is not False and previous == value)
                    else:
                        seen[fact_id] = value
                revealed.update(fact.fact_id for fact in package.allowed)
                samples.append(
                    {
                        "id": f"{row['id']}:{turn_index}",
                        "script_id": row["id"],
                        "run_index": run_index,
                        "suite": "dialogue",
                        "turn_index": turn_index,
                        "ttft_ms": next(
                            (m.ttft_ms for m in call_metrics if m.ttft_ms is not None), None
                        ),
                        "total_latency_ms": round(total_ms, 3),
                        "output_tokens": output_tokens,
                        "tokens_per_second": _tps(output_tokens, total_ms),
                        "output_chars": len(spoken),
                        "chars_per_output_token": round(len(spoken) / output_tokens, 3)
                        if output_tokens
                        else None,
                        "structured_output_valid": bool(response.validated),
                        "repair_used": response.regeneration_count > 0,
                        "fallback_used": from_fallback,
                        "forbidden_fact_leak": bool(leaked),
                        "leaked_values": leaked,
                        "validator_failure_codes": list(response.failure_codes),
                        "repeat_consistent": consistent,
                        "repeat_undelivered": undelivered_repeats,
                        "delivered_values": {k: " ".join(v) for k, v in delivered.items() if v},
                        "spoken": spoken,
                    }
                )
    envelope.note(f"dialogue suite: {len(rows)} script(s) x {max(1, args.runs)} run(s)")
    return samples


def _delivered_values(package: Any, spoken: str) -> dict[str, tuple[str, ...] | None]:
    """`fact_id -> the canonical token sequence of the value the caller actually said`.

    The turn's `AllowedFactsPackage` says what value each allowed fact carries (`value_ru`, the
    caller's Russian spoken form); this folds both that value and the utterance through
    `50-voice-pipeline.md` §7.2 and reports the value when its token sequence appears verbatim in
    what was said. `None` means "this fact was allowed but not actually stated". Comparing these
    across two turns is the **exact canonical comparison** HLD §7.2 requires for
    `dialogue_consistency_rate` — no model judges anything, and «27» matches «двадцать семь».
    """
    haystack = fold(spoken)
    out: dict[str, tuple[str, ...] | None] = {}
    for fact in package.allowed:
        needle = fold(fact.value_ru)
        out[fact.fact_id] = needle if needle and _subsequence(haystack, needle) else None
    return out


def _subsequence(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[start : start + len(needle)] == needle
        for start in range(len(haystack) - len(needle) + 1)
    )


def _scripted_dialogue_llm(package: Any) -> Any:
    """A `FakeLLM` that answers only from the turn's own allowed-facts package (D13).

    This is the §43 suite's own *honest-model control*: an answer built out of permitted values
    only, so the gate-side run measures the harness, never the model.
    """
    from app.inference.llm.fake_llm import FakeLLM

    suite = _adversarial()
    return FakeLLM([suite.honest_answer(package)] * 4)


async def _explanation_suite(args: Any, llm: Any, envelope: Envelope) -> list[dict[str, Any]]:
    """The E16 explanation call over a fixture `ScoreReport` — docs 60 §12's open E19 item."""
    from app.application.reports.explanation.prompt import build_messages

    #: `ExplanationAudience` is a `Literal["TRAINEE", "INSTRUCTOR"]`, not an Enum (E16-A).
    audiences = ("TRAINEE", "INSTRUCTOR")
    report, titles, fixture_source = _fixture_report(getattr(args, "explanation_fixture", None))
    #: The product's own `SIM_EXPLANATION_*` call parameters (E19-C: 512/0.3/30 s were this
    #: script's own numbers, which no deployment runs — docs 60 §12 asks for the shipped call's
    #: latency).
    settings = _setting_defaults(
        "explanation_max_tokens", "explanation_temperature", "explanation_timeout_ms"
    )
    envelope.config["explanation"] = {
        "max_tokens": settings["explanation_max_tokens"],
        "temperature": settings["explanation_temperature"],
        "timeout_ms": settings["explanation_timeout_ms"],
    }
    samples: list[dict[str, Any]] = []
    for run_index in range(max(1, args.runs)):
        for audience in audiences:
            messages = build_messages(report, titles, audience)
            started = time.perf_counter()
            completion = await llm.complete(
                messages,
                request_id=f"bench-llm-expl:{audience}:{run_index}",
                max_tokens=settings["explanation_max_tokens"],
                temperature=settings["explanation_temperature"],
                timeout_ms=settings["explanation_timeout_ms"],
            )
            total_ms = elapsed_ms(started)
            output_tokens = completion.usage.completion_tokens if completion.usage else None
            samples.append(
                {
                    "id": f"explanation:{audience}",
                    "run_index": run_index,
                    "suite": "explanation",
                    "audience": audience,
                    "ttft_ms": None,
                    "total_latency_ms": round(total_ms, 3),
                    "output_tokens": output_tokens,
                    "tokens_per_second": _tps(output_tokens, total_ms),
                    "output_chars": len(completion.text),
                    "chars_per_output_token": round(len(completion.text) / output_tokens, 3)
                    if output_tokens
                    else None,
                    "structured_output_valid": bool(completion.text.strip()),
                    "repair_used": False,
                    "forbidden_fact_leak": False,
                    "validator_failure_codes": [],
                }
            )
    envelope.note(
        "explanation suite: the E16 prompt over a fixture ScoreReport "
        f"({fixture_source}) — docs 60 §12"
    )
    return samples


def _fixture_report(path: Path | None = None) -> tuple[Any, dict[str, str], str]:
    """The `ScoreReport` + rule titles the explanation suite explains.

    `path` (default `benchmarks/data/llm/explanation_fixture.json`, E19-C's committed demo good-run
    report) is validated by the domain's own `ScoreReport`, so a fixture that drifts out of the
    domain shape fails loudly instead of quietly changing the prompt. When the file is absent the
    small built-in fixture below is used instead and the envelope says so — a benchmark must never
    stop producing a number because a *fixture* is missing, but it must always say which one it
    used.
    """
    if path is not None and Path(path).is_file():
        from app.domain.scoring.results import ScoreReport

        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        report = ScoreReport.model_validate(payload["report"])
        titles = {str(k): str(v) for k, v in payload["rule_titles"].items()}
        return report, titles, str(path)
    report, titles = _builtin_fixture_report()
    return report, titles, "built-in"


def _builtin_fixture_report() -> tuple[Any, dict[str, str]]:
    """A demo-shaped good run: one passed rule, one failed critical rule (latency fixture only)."""
    from app.domain.common.ids import ScenarioVersionId, SessionId
    from app.domain.enums import EvaluatorType, ScoringCategory
    from app.domain.scoring.results import (
        ScoreCategoryTotal,
        ScoreEvidence,
        ScoreReport,
        ScoreResult,
    )

    session = SessionId(uuid.UUID("11111111-2222-4333-8444-555555555555"))
    scenario = ScenarioVersionId(uuid.UUID("66666666-7777-4888-8999-aaaaaaaaaaaa"))
    passed = ScoreResult(
        rule_id="rule.address_obtained",
        evaluator_type=EvaluatorType.FACT_OBTAINED,
        category=ScoringCategory.INFORMATION_GATHERING,
        points_awarded=10.0,
        max_points=10.0,
        passed=True,
        critical_failure=False,
        evidence=(
            ScoreEvidence(
                event_id=uuid.UUID("bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"),
                note_ru="Адрес получен на 42-й секунде",
            ),
        ),
    )
    failed = ScoreResult(
        rule_id="rule.victims_asked",
        evaluator_type=EvaluatorType.FACT_OBTAINED,
        category=ScoringCategory.TIMELINESS,
        points_awarded=0.0,
        max_points=15.0,
        passed=False,
        critical_failure=True,
        evidence=(
            ScoreEvidence(
                event_id=uuid.UUID("cccccccc-dddd-4eee-8fff-000000000000"),
                note_ru="Вопрос о пострадавших не задан за всё время разговора",
            ),
        ),
    )
    report = ScoreReport(
        scenario_version_id=scenario,
        session_id=session,
        total_points=10.0,
        total_max_points=25.0,
        by_category=(
            ScoreCategoryTotal(
                category=ScoringCategory.INFORMATION_GATHERING,
                points_awarded=10.0,
                max_points=10.0,
            ),
            ScoreCategoryTotal(
                category=ScoringCategory.TIMELINESS, points_awarded=0.0, max_points=15.0
            ),
        ),
        critical_errors=(failed,),
        results=(passed, failed),
        computed_from_event_count=128,
    )
    titles = {
        "rule.address_obtained": "Адрес происшествия получен",
        "rule.victims_asked": "Вопрос о пострадавших задан",
    }
    return report, titles


def _tps(output_tokens: int | None, total_ms: float) -> float | None:
    if not output_tokens or total_ms <= 0:
        return None
    return round(output_tokens / (total_ms / 1000.0), 4)


# ---------------------------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------------------------


def _metrics_for(samples: list[dict[str, Any]]) -> dict[str, Any]:
    codes: dict[str, int] = {}
    for sample in samples:
        for code in sample.get("validator_failure_codes", ()):
            codes[code] = codes.get(code, 0) + 1
    payload: dict[str, Any] = {
        "n": len(samples),
        "ttft_ms": aggregate([s["ttft_ms"] for s in samples if s.get("ttft_ms") is not None]),
        "total_latency_ms": aggregate([s["total_latency_ms"] for s in samples]),
        "tokens_per_second": aggregate(
            [s["tokens_per_second"] for s in samples if s.get("tokens_per_second") is not None]
        ),
        "chars_per_output_token": aggregate(
            [
                s["chars_per_output_token"]
                for s in samples
                if s.get("chars_per_output_token") is not None
            ]
        ),
        "structured_output_validity_rate": rate(
            [bool(s["structured_output_valid"]) for s in samples]
        ),
        "repair_rate": rate([bool(s["repair_used"]) for s in samples]),
        "forbidden_fact_leak_rate": rate([bool(s["forbidden_fact_leak"]) for s in samples]),
        "validator_failure_codes": dict(sorted(codes.items(), key=lambda kv: -kv[1])),
    }
    interpreter = [s for s in samples if s["suite"] == "interpreter"]
    if interpreter:
        payload["speech_act_acc"] = rate([bool(s["speech_act_correct"]) for s in interpreter])
        explicit_total = sum(s["explicit_total"] for s in interpreter)
        payload["explicit_acc"] = {
            "n": explicit_total,
            "rate": (sum(s["explicit_correct"] for s in interpreter) / explicit_total)
            if explicit_total
            else None,
        }
        payload["requested_exact_match_rate"] = rate(
            [bool(s["requested_exact_match"]) for s in interpreter]
        )
    dialogue = [s for s in samples if s["suite"] == "dialogue"]
    if dialogue:
        checked = [s["repeat_consistent"] for s in dialogue if s["repeat_consistent"] is not None]
        payload["dialogue_consistency_rate"] = rate([bool(v) for v in checked])
        payload["repeat_pairs_never_delivered"] = sum(
            int(s.get("repeat_undelivered") or 0) for s in dialogue
        )
        payload["fallback_rate"] = rate([bool(s.get("fallback_used")) for s in dialogue])
    return payload


def _aggregates(samples: list[dict[str, Any]]) -> dict[str, Any]:
    by_suite: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        by_suite.setdefault(str(sample["suite"]), []).append(sample)
    payload: dict[str, Any] = {
        "overall": _metrics_for(samples),
        "by_suite": {k: _metrics_for(v) for k, v in sorted(by_suite.items())},
    }
    certain = [s for s in samples if not s.get("uncertain", False)]
    if len(certain) != len(samples):
        payload["excluding_uncertain"] = _metrics_for(certain)
    return payload


# ---------------------------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------------------------


def _missing_corpora(args: Any, suites: list[str]) -> list[Path]:
    """Corpus files a selected suite needs and this machine does not have (checked synchronously,
    before any event loop work, so the answer is a plain `NOT_RUN` reason)."""
    return [
        Path(path)
        for suite, path in (
            ("interpreter", args.interpreter_cases),
            ("dialogue", args.dialogue_cases),
        )
        if suite in suites and not Path(path).is_file()
    ]


async def run(args: Any) -> Envelope:
    profile = load_profile_for_bench(args.profile)
    suites = list(SUITES) if args.suite == "all" else [args.suite]
    config = profile_config_subtree(profile, "llm")
    config.update(
        {
            "provider_mode": args.provider,
            "suites": suites,
            "runs": args.runs,
            "seed": args.seed,
            "tag": args.tag,
            "parallel_slots": args.parallel or profile.llm.parallel_slots,
            "warmup_requests": args.warmup if args.provider == "real" else 0,
        }
    )

    missing = _missing_corpora(args, suites)
    if missing:
        return not_run(BENCHMARK, args.profile, f"corpus not found: {missing[0]}", config=config)

    envelope = Envelope(benchmark=BENCHMARK, status="OK", profile=args.profile, config=config)
    # HLD §7.0's envelope always carries `hardware:{gpu_name, driver, total_vram_mb}` (E19-C: it
    # was left empty here, the same single instantaneous read `benchmark_asr.py` already takes).
    if args.provider == "real":
        sampler = NvmlSampler()
        envelope.hardware = sampler.hardware
        envelope.note(f"nvml_mode={sampler.mode}")

    if args.provider == "fake":
        from app.inference.llm.fake_llm import FakeLLM

        await _run_suites(args, FakeLLM(["Готово."] * 64), envelope, suites)
        return _finalize(envelope)

    model_path: Path
    if args.model_path is not None:
        model_path = args.model_path
        if not model_path.is_file():
            return not_run(BENCHMARK, args.profile, f"GGUF not found: {model_path}", config=config)
    else:
        resolved, exists = resolve_model_path(profile.llm.model_path, args.models_root)
        if not exists:
            return not_run(BENCHMARK, args.profile, f"GGUF not found: {resolved}", config=config)
        model_path = resolved
    config["model_path"] = str(model_path)

    from _llama import LlamaServerUnavailable, server
    from app.inference.llm.llama_cpp_client import LlamaCppClient

    parallel = args.parallel or profile.llm.parallel_slots

    async def _with(base_url: str) -> None:
        llm = LlamaCppClient(
            base_url=f"{base_url}/v1" if not base_url.rstrip("/").endswith("/v1") else base_url,
            model_name=model_path.stem,
            n_ctx=profile.llm.n_ctx,
            default_timeout_ms=profile.llm.request_timeout_ms,
        )
        try:
            await _warm_up(llm, args.warmup, envelope)
            await _run_suites(args, llm, envelope, suites)
        finally:
            await llm.close()

    if args.base_url:
        envelope.note(f"using an already-running llama-server at {args.base_url}")
        await _with(args.base_url)
        return _finalize(envelope)

    with TemporaryDirectory(prefix="bench-llm-") as tmp:
        try:
            with server(
                model_path,
                Path(tmp),
                parallel=parallel,
                ctx_size=profile.llm.n_ctx * parallel,
                binary=args.llama_server_bin,
            ) as handle:
                envelope.note(
                    f"llama-server binary={handle.binary} offload={handle.offload_mode} "
                    f"n_gpu_layers={handle.n_gpu_layers} "
                    f"vram_free_mb_at_start={handle.vram_free_mb_at_start} "
                    f"load_s={handle.load_seconds:.1f}"
                )
                config["offload_mode"] = handle.offload_mode
                config["n_gpu_layers"] = handle.n_gpu_layers
                sampler = asyncio.create_task(_sample_server_vram(handle.process.pid, envelope))
                try:
                    await _with(handle.base_url)
                finally:
                    sampler.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await sampler
        except LlamaServerUnavailable as exc:
            return _server_unavailable(args.profile, exc, config)
    return _finalize(envelope)


#: Signatures llama.cpp/CUDA print when the card ran out of memory. Matched case-insensitively
#: against the whole captured server log — a benchmark must never guess an OOM from an exit code.
_OOM_SIGNATURES = ("out of memory", "cudamalloc failed", "failed to allocate")


def _server_unavailable(profile: str, exc: Exception, config: dict[str, Any]) -> Envelope:
    """`FAILED` when the server was launched and died out of VRAM; `NOT_RUN` otherwise (R4).

    E19-C2's ruling: "an OOM after the server started is `FAILED`; `NOT_RUN` stays for never
    attempted". The distinction is what a reader needs — *this model does not fit on this card*
    (a measurement outcome, exit code 1) versus *this model was never on this machine* (nothing
    was measured). The verbatim llama.cpp log stays in `reason` either way, so nothing is hidden
    and nothing is inferred: the words come from the server's own output.
    """
    text = str(exc)
    status = "FAILED" if any(sig in text.lower() for sig in _OOM_SIGNATURES) else "NOT_RUN"
    return Envelope(
        benchmark=BENCHMARK,
        status=status,
        profile=profile,
        reason=f"llama-server: {text}",
        config=config,
    )


async def _sample_server_vram(pid: int, envelope: Envelope, interval_s: float = 1.0) -> None:
    """Poll the llama-server's own VRAM residency for the whole run (E19-C).

    `benchmark_vram.py` owns the *project's* peak; this is the one number `docs/benchmarks/llm.md`
    needs per model — how much of the card that model's server held while the suites ran. It is the
    harness's own `pid_vram_mb` (`nvidia-smi --query-compute-apps`) for the PID this process
    started, sampled off the event loop so it never delays a completion, and reported as a
    **sampled lower bound** in `notes` (a peak between two samples is invisible, which is why the
    wording says "sampled").
    """
    from _llama import pid_vram_mb

    peak = 0
    taken = 0
    try:
        while True:
            observed = await asyncio.to_thread(pid_vram_mb, pid)
            if observed is not None:
                taken += 1
                peak = max(peak, int(observed))
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        envelope.note(
            f"llama-server peak VRAM (sampled lower bound, {taken} sample(s) "
            f"every {interval_s:.0f}s): {peak} MiB"
        )
        raise


async def _warm_up(llm: Any, count: int, envelope: Envelope) -> None:
    """Issue `count` throw-away completions before the first measured sample (E19-C).

    The first request against a freshly loaded llama-server pays for CUDA graph capture, the KV
    cache's first allocation and the prompt cache's cold start; including it would make a p95 that
    no trainee ever experiences. The warm-ups are **excluded** — they never become samples — and
    their count and observed latencies are recorded in `notes` so the exclusion is visible.
    """
    if count <= 0:
        envelope.note("warm-up: none requested")
        return
    from app.application.ports.llm import ChatMessage

    messages = (
        ChatMessage(role="system", content="Ты диспетчер службы 112."),
        ChatMessage(role="user", content="Назовите улицу."),
    )
    latencies: list[float] = []
    for index in range(count):
        started = time.perf_counter()
        try:
            await llm.complete(
                messages,
                request_id=f"bench-llm-warmup:{index}",
                max_tokens=32,
                temperature=0.0,
                timeout_ms=120_000,
            )
        except Exception as exc:  # a cold-start failure is a note, not a sample
            envelope.note(f"warm-up {index}: {type(exc).__name__}: {exc}")
            continue
        latencies.append(round(elapsed_ms(started), 1))
    envelope.note(
        f"warm-up: {count} request(s) excluded from every sample, latencies_ms={latencies}"
    )


async def _run_suites(args: Any, llm: Any, envelope: Envelope, suites: list[str]) -> None:
    runners = {
        "interpreter": _interpreter_suite,
        "dialogue": _dialogue_suite,
        "explanation": _explanation_suite,
    }
    for name in suites:
        try:
            envelope.samples.extend(await runners[name](args, llm, envelope))
        except Exception as exc:
            envelope.status = "PARTIAL"
            envelope.reason = f"suite {name} failed: {type(exc).__name__}: {exc}"
            envelope.note(f"suite {name}: {type(exc).__name__}: {exc}")


def _finalize(envelope: Envelope) -> Envelope:
    if envelope.samples:
        envelope.aggregates = _aggregates(envelope.samples)
    elif envelope.status == "OK":
        envelope.status = "NOT_RUN"
        envelope.reason = "no suite produced a sample"
    return envelope


def main(argv: list[str] | None = None) -> int:
    args = parse_common_args(BENCHMARK, argv, extra=_extra, description=__doc__)
    envelope = asyncio.run(run(args))
    return finish(envelope, args.out)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
