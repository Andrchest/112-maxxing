#!/usr/bin/env python3
"""Caller-generator eval runner (E13-B4, CHANGE item 2).

Runs `cases_ru.yaml` (>= 40 hand-labelled turns over the demo scenario, SPEC §43's 10 categories)
through the REAL chain — real `evaluate_fact_access`, real `CallerPromptBuilder`, real
`CallerResponseGenerator` on a real `LlamaCppClient`, real `ResponseValidator`, real
`FallbackTemplates` — against one or more real `.gguf` models, one at a time. It starts and stops
its own `llama-server` the same way `benchmarks/interpreter_eval/run_eval.py` does
(`tests.models.conftest`), but with `--parallel 2` / `ctx-size = n_ctx * 2`: the generator always
sends `id_slot=1` (`app.application.dialogue.generator.GENERATOR_ID_SLOT`, distinct from the
interpreter's `id_slot=0`), which needs a second slot to exist even when this tool never starts the
interpreter itself (E13-B4 item 3's ledger ruling).

This eval isolates the GENERATOR: the "interpreter output" each case needs is hand-labelled in
`cases_ru.yaml` (an `InterpretedUtterance`-shaped block), never produced by a model — that is what
`benchmarks/interpreter_eval/` already measures.

Usage (from the repo root; models comma-separated, run sequentially):
    uv run python benchmarks/caller_eval/run_eval.py \\
        --models models/Qwen3-4B-Q4_K_M.gguf,/home/andreipc/models/Qwen3.5-2B/Qwen3.5-2B-Q4_K_M.gguf

Writes `benchmarks/results/caller_eval/<UTC timestamp>/{results.json,report.md}` — a real, measured
run every time (SPEC §27: "Do not fake or hard-code benchmark values").

Note on TTFT: `LlamaCppClient.complete()` is non-streaming (§2.6) and `LlmCompletion` carries no
TTFT field (the same HLD gap `interpreter_eval/run_eval.py` already reports) — TTFT is reported as
`None` here, not fabricated; `latency_ms` is the attempt's whole round trip.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import scoring
import yaml
from app.application.dialogue.fallbacks import FallbackTemplates
from app.application.dialogue.forbidden_values import forbidden_values
from app.application.dialogue.generator import (
    CallerResponseGenerator,
    GeneratorConfig,
    ValidationInputs,
)
from app.application.dialogue.interpreter import (
    InterpretedUtterance,
    OperatorAssertion,
    RequestedFact,
)
from app.application.dialogue.prompt_builder import CallerPromptBuilder, CallerPromptConfig
from app.application.dialogue.text_normalization import normalize_text
from app.application.dialogue.validator import (
    ResponseValidator,
    ValidationFailureCode,
    ValidatorConfig,
)
from app.application.ports.metrics_recorder import InferenceMetric, NullMetricsRecorder
from app.domain.common.ids import IncidentId
from app.domain.facts.gate import FactRequest, GateConditionContext, evaluate_fact_access
from app.domain.layers.copies import instantiate_caller_belief
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion
from app.inference.llm.llama_cpp_client import LlamaCppClient
from tests.models.conftest import ServerHandle, start_server_trying_binaries, terminate

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = Path(__file__).resolve().parent / "cases_ru.yaml"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmarks" / "results" / "caller_eval"
#: A fixed, synthetic incident id — this tool never touches a database (D13-shaped: pure in-process
#: chain over a scenario document), so it needs no real session/incident row.
INCIDENT_ID = IncidentId(uuid.UUID("0e1a4b1e-9d2a-0a7c-5b2f-1d1100000099"))
#: E13-B4 item 3: distinct from the interpreter's `--parallel 1` (id_slot=0 only) — the generator
#: always sends `id_slot=1`.
SERVER_PARALLEL = 2
N_CTX = 4096


def _load_cases(path: Path) -> tuple[Path, list[dict[str, Any]]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenario_path = REPO_ROOT / document["scenario"]
    return scenario_path, document["cases"]


def _validate_cases_against_catalog(cases: list[dict[str, Any]], fact_ids: set[str]) -> None:
    categories: set[str] = set()
    for case in cases:
        categories.add(case["category"])
        interp = case["interpreted"]
        ids = (
            {f["fact_id"] for f in interp["requested_facts"]}
            | {a["fact_id"] for a in interp["operator_assertions"]}
            | set(interp["confirmation_targets"])
        )
        unknown = ids - fact_ids
        if unknown:
            raise SystemExit(f"case {case['id']!r} references unknown fact id(s): {unknown}")
    if len(categories) < 10:
        raise SystemExit(f"cases_ru.yaml covers only {len(categories)} categories, need 10")


def _interpreted_utterance(block: dict[str, Any]) -> InterpretedUtterance:
    return InterpretedUtterance(
        speech_act=block["speech_act"],
        requested_facts=tuple(
            RequestedFact(fact_id=f["fact_id"], explicit=f["explicit"])
            for f in block["requested_facts"]
        ),
        operator_assertions=tuple(
            OperatorAssertion(fact_id=a["fact_id"], asserted_value=a["asserted_value"])
            for a in block["operator_assertions"]
        ),
        confirmation_targets=tuple(block["confirmation_targets"]),
        semantic_confidence=block["semantic_confidence"],
    )


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[start : start + len(needle)] == needle
        for start in range(len(haystack) - len(needle) + 1)
    )


def _leak_scan(text: str, forbidden: tuple[str, ...]) -> bool:
    """True when `text` contains any of `forbidden`, normalised the way §7.6's own check is."""
    if not text:
        return False
    haystack = normalize_text(text).texts
    for value in forbidden:
        needle = normalize_text(value).texts
        if needle and _contains(haystack, needle):
            return True
    return False


def _machine_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {"hostname": platform.node(), "platform": platform.platform()}
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,memory.used", "--format=csv"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        snapshot["nvidia_smi"] = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        snapshot["nvidia_smi"] = None
    return snapshot


async def _run_one_model(
    model_path: Path,
    *,
    cases: list[dict[str, Any]],
    definitions: Any,
    profile: Any,
    caller_belief: Any,
    max_tokens: int,
    timeout_ms: int,
    use_grammar: bool,
    tmp_dir: Path,
) -> dict[str, Any]:
    server: ServerHandle = start_server_trying_binaries(
        model_path, tmp_dir, parallel=SERVER_PARALLEL, ctx_size=N_CTX * SERVER_PARALLEL
    )
    llm = LlamaCppClient(
        base_url=f"{server.base_url}/v1",
        model_name=model_path.stem,
        n_ctx=N_CTX,
        default_timeout_ms=timeout_ms,
    )
    metrics = NullMetricsRecorder()
    builder = CallerPromptBuilder(CallerPromptConfig())
    validator = ResponseValidator(ValidatorConfig(small_count_allowlist=frozenset()))
    generator = CallerResponseGenerator(
        llm,
        metrics,
        builder,
        validator,
        config=GeneratorConfig(
            max_tokens=max_tokens, timeout_ms=timeout_ms, use_grammar=use_grammar
        ),
    )
    fallback_templates = FallbackTemplates()

    per_case: list[dict[str, Any]] = []
    outcomes: list[scoring.CaseOutcome] = []
    try:
        # Warm-up call, same shape as interpreter_eval's, so the first real case is not the
        # server's cold call.
        warmup_package, _ = evaluate_fact_access(
            (), definitions, caller_belief, frozenset(), 0, GateConditionContext()
        )
        await generator.generate(
            warmup_package,
            profile,
            caller_belief.emotion,
            (),
            (),
            "Алло",
            inputs=ValidationInputs(),
            session_id=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            request_id="warmup",
        )
        server.sample_vram()

        for index, case in enumerate(cases):
            interpreted = _interpreted_utterance(case["interpreted"])
            requests = [
                FactRequest(fact_id=f.fact_id, explicit=f.explicit)
                for f in interpreted.requested_facts
            ]
            package, _decisions = evaluate_fact_access(
                requests,
                definitions,
                caller_belief,
                frozenset(),
                case["session_offset_ms"],
                GateConditionContext(),
            )
            forbidden = forbidden_values(definitions, package, frozenset())

            before = len(metrics.metrics)
            turn_id = uuid.uuid4()
            response = await generator.generate(
                package,
                profile,
                caller_belief.emotion,
                (),
                (),
                case["operator_utterance"],
                inputs=ValidationInputs(
                    revealed_values=(),
                    operator_utterances=(case["operator_utterance"],),
                    persona_whitelist=tuple(profile.persona_whitelist_ru),
                    forbidden_values=forbidden,
                ),
                session_id=uuid.UUID(int=index + 1),
                turn_id=turn_id,
                request_id=f"caller-eval:{case['id']}",
            )
            call_metrics: list[InferenceMetric] = metrics.metrics[before:]
            attempt1 = call_metrics[0] if call_metrics else None

            if response.validated:
                final_text = response.utterance
                fallback_row = None
            else:
                choice = fallback_templates.select(package, interpreted)
                final_text = choice.text
                fallback_row = int(choice.template_row)

            raw_leak = bool(
                response.verdicts
                and ValidationFailureCode.WORLD_VALUE_LEAK in response.verdicts[0].codes
            )
            final_leak = _leak_scan(final_text, forbidden)

            outcome = scoring.CaseOutcome(
                case_id=case["id"],
                category=case["category"],
                attempt1_ok=bool(response.verdicts) and response.verdicts[0].ok,
                attempt1_codes=(
                    tuple(code.value for code in response.verdicts[0].codes)
                    if response.verdicts
                    else ()
                ),
                attempt2_ok=(response.verdicts[1].ok if len(response.verdicts) > 1 else None),
                fallback_row=fallback_row,
                final_text=final_text,
                latency_ms=attempt1.total_latency_ms if attempt1 else None,
                prompt_tokens=attempt1.input_tokens if attempt1 else None,
                completion_tokens=attempt1.output_tokens if attempt1 else None,
                final_text_has_forbidden_value=final_leak,
                raw_attempt1_has_forbidden_value=raw_leak,
            )
            outcomes.append(outcome)
            per_case.append(
                {
                    "case_id": outcome.case_id,
                    "category": outcome.category,
                    "operator_utterance": case["operator_utterance"],
                    "attempt1_ok": outcome.attempt1_ok,
                    "attempt1_codes": list(outcome.attempt1_codes),
                    "attempt2_ok": outcome.attempt2_ok,
                    "fallback_row": outcome.fallback_row,
                    "final_text": outcome.final_text,
                    "llm_calls": len(call_metrics),
                    "latency_ms": outcome.latency_ms,
                    "prompt_tokens": outcome.prompt_tokens,
                    "completion_tokens": outcome.completion_tokens,
                    "final_text_has_forbidden_value": outcome.final_text_has_forbidden_value,
                    "raw_attempt1_has_forbidden_value": outcome.raw_attempt1_has_forbidden_value,
                }
            )
            server.sample_vram()

        summary = scoring.aggregate(outcomes)
        summary["model"] = model_path.name
        summary["model_path"] = str(model_path)
        summary["binary"] = str(server.binary)
        summary["offload_mode"] = server.offload_mode
        summary["n_gpu_layers"] = server.n_gpu_layers
        summary["vram_free_mb_at_start"] = server.vram_free_mb_at_start
        summary["peak_vram_mb"] = server.peak_vram_mb
        summary["load_seconds"] = round(server.load_seconds, 1)
        summary["use_grammar"] = use_grammar
        summary["server_parallel"] = SERVER_PARALLEL
        return {"summary": summary, "cases": per_case, "status": "OK"}
    finally:
        await llm.close()
        terminate(server.process)


def _write_report(out_dir: Path, results: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    header = (
        "| model | status | offload | validated_1st | regen | fallback | raw_leak | final_leak "
        "| p50_ms | p95_ms | max_ms | tok_p50 | tok_p99 | tok/s | load_s | peak_vram_mb |"
    )
    separator = "|" + "---|" * 16
    rows = [header, separator]

    def fmt(value: Any, digits: int = 2) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        return str(value)

    for model_result in results["models"]:
        s = model_result["summary"]
        status = model_result.get("status", "OK")
        if status != "OK":
            # The full reason (often a multi-line server log tail) lives in `results.json`
            # verbatim; the table gets a one-line summary so a FAILED/NOT_RUN row does not break
            # the markdown table's row structure.
            reason = (
                str(model_result.get("reason", "")).splitlines()[0]
                if model_result.get("reason")
                else ""
            )
            rows.append(
                f"| {s.get('model', '?')} | {status} | - | - | - | - | - | - | - | - | - | - | "
                f"- | - | - | {reason} — see results.json for the full reason |"
            )
            continue
        rows.append(
            "| "
            + " | ".join(
                [
                    s["model"],
                    "OK",
                    f"{s['offload_mode']}({s['n_gpu_layers']})",
                    fmt(s["validated_first_try_rate"]),
                    fmt(s["regeneration_rate"]),
                    fmt(s["fallback_rate"]),
                    fmt(s["raw_model_leak_rate"]),
                    fmt(s["forbidden_fact_leak_rate"]),
                    fmt(s["latency_ms_p50"], 0),
                    fmt(s["latency_ms_p95"], 0),
                    fmt(s["latency_ms_max"], 0),
                    fmt(s["completion_tokens_p50"], 0),
                    fmt(s["completion_tokens_p99"], 0),
                    fmt(s["tokens_per_second_mean"]),
                    fmt(s["load_seconds"], 1),
                    fmt(s["peak_vram_mb"], 0),
                ]
            )
            + " |"
        )

    report = [
        f"# Caller-generator eval — {results['generated_at']}",
        "",
        f"Cases: `{results['cases_file']}` ({results['n_cases']} cases, "
        f"{results['n_categories']} SPEC §43 categories). "
        f"Machine: `{results['machine']['hostname']}`.",
        "",
        "```",
        str(results["machine"].get("nvidia_smi")),
        "```",
        "",
        "\n".join(rows),
        "",
    ]
    (out_dir / "report.md").write_text("\n".join(report), encoding="utf-8")


async def _main_async(args: argparse.Namespace, *, out_dir: Path, tmp_dir: Path) -> None:
    cases_path = Path(args.cases)
    scenario_path, cases = _load_cases(cases_path)
    version = ScenarioVersion.model_validate(
        yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    )
    definitions = build_fact_definitions(version)
    _validate_cases_against_catalog(cases, set(definitions))
    profile = version.caller_profile
    caller_belief = instantiate_caller_belief(version, INCIDENT_ID)

    model_paths = [Path(p.strip()) for p in args.models.split(",") if p.strip()]

    model_results: list[dict[str, Any]] = []
    for model_path in model_paths:
        if not model_path.exists():
            print(f"=== {model_path}: NOT_RUN (path does not exist) ===", flush=True)
            model_results.append(
                {
                    "summary": {"model": model_path.name},
                    "cases": [],
                    "status": "NOT_RUN",
                    "reason": "model path does not exist",
                }
            )
            continue
        print(f"=== running caller eval: {model_path} ===", flush=True)
        try:
            result = await _run_one_model(
                model_path,
                cases=cases,
                definitions=definitions,
                profile=profile,
                caller_belief=caller_belief,
                max_tokens=args.max_tokens,
                timeout_ms=args.timeout_ms,
                use_grammar=not args.no_grammar,
                tmp_dir=tmp_dir,
            )
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except BaseException as exc:
            # `tests.models.conftest.start_server_trying_binaries` calls `pytest.fail`/
            # `pytest.skip` on a load failure (it is shared with pytest tests) — both raise a
            # `BaseException` subclass (`_pytest.outcomes.OutcomeException`), not `Exception`, so
            # a plain `except Exception` here would let a model that fails to load (e.g. CUDA OOM
            # sizing `--ctx-size` for `--parallel 2`) crash the whole sweep instead of becoming
            # the FAILED row the brief asks for. Every other model still runs.
            print(f"=== {model_path}: FAILED ({type(exc).__name__}: {exc}) ===", flush=True)
            model_results.append(
                {
                    "summary": {"model": model_path.name},
                    "cases": [],
                    "status": "FAILED",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        model_results.append(result)
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))

    categories = {case["category"] for case in cases}
    results = {
        "generated_at": datetime.now(UTC).isoformat(),
        "cases_file": str(cases_path.relative_to(REPO_ROOT)),
        "scenario": str(scenario_path.relative_to(REPO_ROOT)),
        "n_cases": len(cases),
        "n_categories": len(categories),
        "machine": _machine_snapshot(),
        "server_parallel": SERVER_PARALLEL,
        "models": model_results,
    }
    _write_report(out_dir, results)
    print(f"wrote {out_dir / 'results.json'} and {out_dir / 'report.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models", required=True, help="comma-separated .gguf paths, run sequentially"
    )
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--max-tokens", type=int, default=80)
    parser.add_argument("--timeout-ms", type=int, default=8_000)
    parser.add_argument("--no-grammar", action="store_true", help="use response_format instead")
    args = parser.parse_args()

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = DEFAULT_OUT_DIR / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="caller-eval-"))

    asyncio.run(_main_async(args, out_dir=out_dir, tmp_dir=tmp_dir))


if __name__ == "__main__":
    main()
