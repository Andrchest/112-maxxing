#!/usr/bin/env python3
"""Interpreter eval runner (this task's brief, CHANGE item 6).

Runs the labelled Russian eval set (`ru_operator_utterances.yaml`, over the demo scenario's fact
catalog) through the PRODUCTION `DialogueInterpreter` + `LlamaCppClient` — the same classes
`backend/app/application/dialogue/interpreter.py` and `backend/app/inference/llm/
llama_cpp_client.py` ship — against one or more real `.gguf` models, one at a time. It starts and
stops its own `llama-server` the same way `backend/tests/models/test_llama_cpp_contract.py` does
(`tests.models.conftest`): a probed, never-8000/8001/8080 port, offload sized from free VRAM and
the model's own GGUF layer count, and the PID it started is always terminated, even on failure.

Usage (from the repo root; models comma-separated, run sequentially):
    uv run python benchmarks/interpreter_eval/run_eval.py \\
        --models models/Qwen3-4B-Q4_K_M.gguf,/home/andreipc/models/Qwen3.5-2B/Qwen3.5-2B-Q4_K_M.gguf

Writes `benchmarks/results/interpreter_eval/<UTC timestamp>/{results.json,report.md}` — a real,
measured run every time (SPEC §27: "Do not fake or hard-code benchmark values"), never generated
without a live model actually answering.

Note on `timings`/`tokens_evaluated` (CHANGE item 3): llama-server's raw HTTP response carries
these (see this task's report for a manual, real measurement showing `cache_n` reused on a
byte-identical 2nd call), but `LlmCompletion` (`app.application.ports.llm`) has no field for them
and this tool deliberately goes through the production `LlamaCppClient`/`DialogueInterpreter`
only — it does not bypass the port with a second, raw HTTP client to smuggle the field in. Report
only, not recorded per-item here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import scoring
import yaml
from app.application.dialogue.catalog import build_fact_catalog
from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
from app.application.ports.metrics_recorder import InferenceMetric, NullMetricsRecorder
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion
from app.inference.llm.llama_cpp_client import LlamaCppClient
from tests.models.conftest import ServerHandle, start_server_trying_binaries, terminate

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVAL_SET = Path(__file__).resolve().parent / "ru_operator_utterances.yaml"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmarks" / "results" / "interpreter_eval"
_WARMUP_UTTERANCE = "Алло"


def _load_eval_set(path: Path) -> tuple[Path, list[dict[str, Any]]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenario_path = REPO_ROOT / document["scenario"]
    return scenario_path, document["items"]


def _catalog_and_ids(scenario_path: Path) -> tuple[Any, set[str]]:
    version = ScenarioVersion.model_validate(
        yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    )
    definitions = build_fact_definitions(version)
    catalog = build_fact_catalog(definitions)
    return catalog, {entry.fact_id for entry in catalog}


def _validate_items_against_catalog(items: list[dict[str, Any]], catalog_ids: set[str]) -> None:
    for item in items:
        expected = item["expected"]
        ids = (
            {f["fact_id"] for f in expected.get("requested_facts", [])}
            | {a["fact_id"] for a in expected.get("operator_assertions", [])}
            | set(expected.get("confirmation_targets", []))
        )
        unknown = ids - catalog_ids
        if unknown:
            raise SystemExit(
                f"eval item {item['id']!r} expects fact id(s) not in the catalog: {unknown}"
            )


def _machine_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {"hostname": platform.node(), "platform": platform.platform()}
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free,memory.used",
                "--format=csv",
            ],
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
    items: list[dict[str, Any]],
    catalog: Any,
    max_tokens: int,
    timeout_ms: int,
    use_grammar: bool,
    tmp_dir: Path,
) -> dict[str, Any]:
    """`tmp_dir` must already exist — created once, synchronously, by the caller (`main()`)."""
    server: ServerHandle = start_server_trying_binaries(model_path, tmp_dir)
    llm = LlamaCppClient(
        base_url=f"{server.base_url}/v1",
        model_name=model_path.stem,
        n_ctx=4096,
        default_timeout_ms=timeout_ms,
    )
    metrics = NullMetricsRecorder()
    interpreter = DialogueInterpreter(
        llm,
        metrics,
        config=InterpreterConfig(
            max_tokens=max_tokens, timeout_ms=timeout_ms, use_grammar=use_grammar
        ),
    )

    per_item: list[dict[str, Any]] = []
    scored: list[scoring.ScoredCall] = []
    try:
        await interpreter.interpret(
            _WARMUP_UTTERANCE, (), catalog, request_id="warmup", turn_index=0
        )
        server.sample_vram()

        for index, item in enumerate(items):
            think_leaks_before = len(llm.think_leaks)
            before = len(metrics.metrics)
            started = time.perf_counter()
            outcome = await interpreter.interpret(
                item["utterance"], (), catalog, request_id=f"eval:{item['id']}", turn_index=index
            )
            latency_ms = (time.perf_counter() - started) * 1000
            server.sample_vram()
            call_metrics: list[InferenceMetric] = metrics.metrics[before:]
            completion_tokens = sum(m.output_tokens or 0 for m in call_metrics) or None
            prompt_tokens = call_metrics[0].input_tokens if call_metrics else None
            think_leak = len(llm.think_leaks) > think_leaks_before

            actual = outcome.interpretation.model_dump(mode="json")
            one_scored = scoring.score_call(
                item_id=item["id"],
                expected=item["expected"],
                actual=actual,
                fallback_used=outcome.fallback_used,
                repair_retry_used=outcome.repair_retry_used,
                think_leak=think_leak,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            scored.append(one_scored)
            per_item.append(
                {
                    "item_id": item["id"],
                    "utterance": item["utterance"],
                    "expected": item["expected"],
                    "actual": actual,
                    "uncertain": bool(item.get("uncertain", False)),
                    "speech_act_correct": one_scored.speech_act_correct,
                    "requested_precision": one_scored.requested_precision,
                    "requested_recall": one_scored.requested_recall,
                    "requested_exact_match": one_scored.requested_exact_match,
                    "fallback_used": outcome.fallback_used,
                    "repair_retry_used": outcome.repair_retry_used,
                    "failure_reason": outcome.failure_reason,
                    "think_leak": think_leak,
                    "latency_ms": round(latency_ms, 1),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                }
            )

        uncertain_ids = frozenset(item["id"] for item in items if item.get("uncertain"))
        both = scoring.aggregate_by_uncertainty(scored, uncertain_ids)
        summary = both["all"]
        summary_excluding_uncertain = both["excluding_uncertain"]
        metadata = {
            "model": model_path.name,
            "model_path": str(model_path),
            "binary": str(server.binary),
            "offload_mode": server.offload_mode,
            "n_gpu_layers": server.n_gpu_layers,
            "vram_free_mb_at_start": server.vram_free_mb_at_start,
            "peak_vram_mb": server.peak_vram_mb,
            "load_seconds": round(server.load_seconds, 1),
            "use_grammar": use_grammar,
        }
        for one_summary, rows in (
            (summary, per_item),
            (summary_excluding_uncertain, [r for r in per_item if not r["uncertain"]]),
        ):
            one_summary.update(metadata)
            one_summary["think_leak_count"] = sum(1 for row in rows if row["think_leak"])
            row_tok_s = [
                row["completion_tokens"] / (row["latency_ms"] / 1000)
                for row in rows
                if row["completion_tokens"] and row["latency_ms"] > 0
            ]
            one_summary["tokens_per_second_mean"] = (
                round(sum(row_tok_s) / len(row_tok_s), 2) if row_tok_s else None
            )
            row_latencies = [row["latency_ms"] for row in rows]
            row_completion = [
                float(row["completion_tokens"]) for row in rows if row["completion_tokens"]
            ]
            one_summary["latency_ms_p50_measured"] = one_summary["latency_ms_p50"]
            one_summary["latency_ms_p95_measured"] = one_summary["latency_ms_p95"]
            one_summary["latency_ms_max_measured"] = max(row_latencies) if row_latencies else None
            one_summary["completion_tokens_p99_measured"] = scoring.percentile(row_completion, 0.99)
        return {
            "summary": summary,
            "summary_excluding_uncertain": summary_excluding_uncertain,
            "items": per_item,
        }
    finally:
        await llm.close()
        terminate(server.process)


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


_TABLE_HEADER = (
    "| model | offload | speech_act_acc | facts_P | facts_R | exact_match | explicit_acc "
    "| fallback | repair | think_leak | p50_ms | p95_ms | max_ms | tok_p50 | tok_p99 | "
    "tok/s | load_s | peak_vram_mb |"
)
_TABLE_SEPARATOR = "|" + "---|" * 17


def _table_rows(models: list[dict[str, Any]], summary_key: str) -> list[str]:
    """One markdown table over `summary_key` ('summary' or 'summary_excluding_uncertain')."""
    rows = [_TABLE_HEADER, _TABLE_SEPARATOR]
    for model_result in models:
        s = model_result[summary_key]
        rows.append(
            "| "
            + " | ".join(
                [
                    s["model"],
                    f"{s['offload_mode']}({s['n_gpu_layers']})",
                    _fmt(s["speech_act_accuracy"]),
                    _fmt(s["requested_facts_precision_mean"]),
                    _fmt(s["requested_facts_recall_mean"]),
                    _fmt(s["requested_facts_exact_match_rate"]),
                    _fmt(s["explicit_flag_accuracy"]),
                    _fmt(s["fallback_rate"]),
                    _fmt(s["repair_rate"]),
                    _fmt(s["think_leak_count"], 0),
                    _fmt(s["latency_ms_p50_measured"], 0),
                    _fmt(s["latency_ms_p95_measured"], 0),
                    _fmt(s["latency_ms_max_measured"], 0),
                    _fmt(s["completion_tokens_p50"], 0),
                    _fmt(s["completion_tokens_p99_measured"], 0),
                    _fmt(s["tokens_per_second_mean"]),
                    _fmt(s["load_seconds"], 1),
                    _fmt(s["peak_vram_mb"], 0),
                ]
            )
            + " |"
        )
    return rows


def _write_report(out_dir: Path, results: dict[str, Any]) -> None:
    """Writes `results.json`, `report.md` (all items) and `report_excluding_uncertain.md`.

    E13-B4 item 1 (MANAGER RULING): every aggregate metric is reported TWICE — over all items and
    over items without `uncertain: true`. The all-items table is `report.md` (unchanged shape from
    B3); the excluding-uncertain one is its own sibling file, so a reader can tell at a glance which
    table they are looking at, and so `_recompute_report` (no server, no re-run) can regenerate it
    alone from an already-written `results.json`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    header = [
        f"# Interpreter eval — {results['generated_at']}",
        "",
        f"Eval set: `{results['eval_set']}` ({results['n_items']} items). "
        f"Machine: `{results['machine']['hostname']}`.",
        "",
        "```",
        str(results["machine"].get("nvidia_smi")),
        "```",
        "",
    ]
    (out_dir / "report.md").write_text(
        "\n".join([*header, "\n".join(_table_rows(results["models"], "summary")), ""]),
        encoding="utf-8",
    )

    uncertain_note = (
        "Excluding the eval set's `uncertain: true` items (MANAGER RULING: those 5 labels stay as "
        "labelled and stay flagged, not changed or dropped from the eval set — only excluded from "
        "this second aggregate)."
    )
    (out_dir / "report_excluding_uncertain.md").write_text(
        "\n".join(
            [
                *header,
                uncertain_note,
                "",
                "\n".join(_table_rows(results["models"], "summary_excluding_uncertain")),
                "",
            ]
        ),
        encoding="utf-8",
    )


def _recompute_report(results_path: Path) -> None:
    """Regenerate `report.md` / `report_excluding_uncertain.md` from an existing `results.json`.

    No server, no LLM call, no `uv sync` — pure recomputation from what a previous real run
    persisted (SPEC §27: nothing here is a fabricated number, every one of them was already
    measured; this only re-derives the aggregate). Used by E13-B4 item 1 to add the
    excluding-uncertain table to B3's already-measured `20260921T180708Z` sweep without re-running
    it, and safe to rerun on any future `results.json` that has per-item `expected`/`actual`.
    """
    results = json.loads(results_path.read_text(encoding="utf-8"))
    eval_set_path = REPO_ROOT / results["eval_set"]
    _scenario_path, eval_items = _load_eval_set(eval_set_path)
    uncertain_ids = frozenset(item["id"] for item in eval_items if item.get("uncertain"))

    for model_result in results["models"]:
        items = model_result["items"]
        scored = [
            scoring.score_call(
                item_id=row["item_id"],
                expected=row["expected"],
                actual=row["actual"],
                fallback_used=row.get("fallback_used", False),
                repair_retry_used=row.get("repair_retry_used", False),
                think_leak=row.get("think_leak", False),
                latency_ms=row.get("latency_ms"),
                prompt_tokens=row.get("prompt_tokens"),
                completion_tokens=row.get("completion_tokens"),
            )
            for row in items
        ]
        both = scoring.aggregate_by_uncertainty(scored, uncertain_ids)
        metadata_keys = (
            "model",
            "model_path",
            "binary",
            "offload_mode",
            "n_gpu_layers",
            "vram_free_mb_at_start",
            "peak_vram_mb",
            "load_seconds",
            "use_grammar",
        )
        old_summary = model_result["summary"]
        metadata = {key: old_summary[key] for key in metadata_keys}
        for row in items:
            row["uncertain"] = row["item_id"] in uncertain_ids
        for key, summary in both.items():
            summary.update(metadata)
            summary["latency_ms_p50_measured"] = summary["latency_ms_p50"]
            summary["latency_ms_p95_measured"] = summary["latency_ms_p95"]
            rows = items if key == "all" else [r for r in items if not r["uncertain"]]
            latencies = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
            summary["latency_ms_max_measured"] = max(latencies) if latencies else None
            completion = [float(r["completion_tokens"]) for r in rows if r.get("completion_tokens")]
            summary["completion_tokens_p99_measured"] = scoring.percentile(completion, 0.99)
            tok_s = [
                r["completion_tokens"] / (r["latency_ms"] / 1000)
                for r in rows
                if r.get("completion_tokens") and r.get("latency_ms")
            ]
            summary["tokens_per_second_mean"] = round(sum(tok_s) / len(tok_s), 2) if tok_s else None
        model_result["summary"] = both["all"]
        model_result["summary_excluding_uncertain"] = both["excluding_uncertain"]

    _write_report(results_path.parent, results)
    print(
        f"recomputed {results_path.parent / 'report.md'} and "
        f"{results_path.parent / 'report_excluding_uncertain.md'}"
    )


async def _main_async(args: argparse.Namespace, *, out_dir: Path, tmp_dir: Path) -> None:
    eval_set_path = Path(args.eval_set)
    scenario_path, items = _load_eval_set(eval_set_path)
    catalog, catalog_ids = _catalog_and_ids(scenario_path)
    _validate_items_against_catalog(items, catalog_ids)

    model_paths = [Path(p.strip()) for p in args.models.split(",") if p.strip()]
    for model_path in model_paths:
        if not model_path.exists():
            raise SystemExit(f"model path does not exist: {model_path}")

    model_results: list[dict[str, Any]] = []
    for model_path in model_paths:
        print(f"=== running eval: {model_path} ===", flush=True)
        result = await _run_one_model(
            model_path,
            items=items,
            catalog=catalog,
            max_tokens=args.max_tokens,
            timeout_ms=args.timeout_ms,
            use_grammar=not args.no_grammar,
            tmp_dir=tmp_dir,
        )
        model_results.append(result)
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))

    results = {
        "generated_at": datetime.now(UTC).isoformat(),
        "eval_set": str(eval_set_path.relative_to(REPO_ROOT)),
        "scenario": str(scenario_path.relative_to(REPO_ROOT)),
        "n_items": len(items),
        "machine": _machine_snapshot(),
        "models": model_results,
    }
    _write_report(out_dir, results)
    print(f"wrote {out_dir / 'results.json'} and {out_dir / 'report.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models", required=False, help="comma-separated .gguf paths, run sequentially"
    )
    parser.add_argument("--eval-set", default=str(DEFAULT_EVAL_SET))
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=300,
        help="generous headroom for measuring the real p99 completion-token count (CHANGE item 4)",
    )
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    parser.add_argument("--no-grammar", action="store_true", help="use response_format instead")
    parser.add_argument(
        "--recompute-report",
        default=None,
        metavar="RESULTS_JSON",
        help=(
            "no server, no model: recompute report.md / report_excluding_uncertain.md from an "
            "already-written results.json (E13-B4 item 1) and exit"
        ),
    )
    args = parser.parse_args()

    if args.recompute_report:
        _recompute_report(Path(args.recompute_report))
        return
    if not args.models:
        parser.error("--models is required unless --recompute-report is given")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = DEFAULT_OUT_DIR / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    # Server logs are debug output, not a measurement — kept out of the committed results
    # directory (that one holds only results.json/report.md, per this task's brief) in a real OS
    # temp dir instead.
    tmp_dir = Path(tempfile.mkdtemp(prefix="interpreter-eval-"))

    asyncio.run(_main_async(args, out_dir=out_dir, tmp_dir=tmp_dir))


if __name__ == "__main__":
    main()
