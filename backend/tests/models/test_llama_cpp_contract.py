"""`LlamaCppClient` contract test against a real llama-server (SPEC §22, §27, §41).

Marker `requires_models` (E12 ruling 1): `make test-models` only, or
`SIM_RUN_MODEL_TESTS=1 uv run pytest -m requires_models backend/tests/models/
test_llama_cpp_contract.py`. Starts its own `llama-server` on a probed, never-8000/8001/8080 port
(`tests.models.conftest`), waits for `/health`, and **always** terminates the PID it captured, even
on failure — the shared GPU and the two reserved ports belong to other work on this machine (never
touched here). The offload (all layers / a proportional slice / CPU) is sized from the model's own
file size and GGUF layer count against free VRAM at that moment (this task's brief, CHANGE item 5;
`tests.models.conftest.choose_offload`) — not a flat "< 3000 MB free -> CPU" rule.

Which model(s) run is controlled by `SIM_LLM_CONTRACT_MODELS` — a comma-separated list of `.gguf`
paths, run **sequentially**, one server at a time, each fully torn down before the next starts.
With no override, exactly one model runs: `SIM_LLM_MODEL_PATH`, else `models/Qwen3-4B-Q4_K_M.gguf`
(`make models-llm`), else the read-only smoke fallback at
`/home/andreipc/models/Qwen3.5-4B/Qwen3.5-4B-Q4_K_M.gguf` — never modified, never moved.

Every assertion is over Russian operator utterances from the demo scenario's own fact catalog, so
"parses into `InterpretedUtterance`" and "no `<think>` leak" are checked against the same prompt a
real training session would send, not a synthetic one. The interpreter's real CHANGE-item defaults
(grammar, few-shot prefix, `cache_prompt`) are exercised as-is, not disabled for the test.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from app.application.dialogue.catalog import build_fact_catalog
from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
from app.application.ports.llm import ChatMessage
from app.application.ports.metrics_recorder import InferenceMetric, NullMetricsRecorder
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion
from app.inference.llm.llama_cpp_client import LlamaCppClient

from tests.fixtures.scenarios import demo_document
from tests.models._skip import require_model_env
from tests.models.conftest import ServerHandle, start_server_trying_binaries, terminate

pytestmark = pytest.mark.requires_models

#: SPEC §43-flavoured smoke set: a mix of QUESTION/GREETING/INSTRUCTION-shaped operator turns
#: over the demo scenario, in Russian, none of them containing a scenario value.
UTTERANCES_RU: tuple[str, ...] = (
    "Какой у вас адрес?",
    "Есть ли пострадавшие?",
    "Как вас зовут?",
    "Алло, служба 112, что случилось?",
    "Оставайтесь на линии",
)

_FALLBACK_MODEL = Path("/home/andreipc/models/Qwen3.5-4B/Qwen3.5-4B-Q4_K_M.gguf")


def _resolve_model_paths() -> list[Path]:
    """`SIM_LLM_CONTRACT_MODELS` (comma-separated), else the brief's single-model fallback chain."""
    override = os.environ.get("SIM_LLM_CONTRACT_MODELS")
    if override:
        return [Path(item.strip()) for item in override.split(",") if item.strip()]
    configured = Path(os.environ.get("SIM_LLM_MODEL_PATH", "models/Qwen3-4B-Q4_K_M.gguf"))
    if configured.exists():
        return [configured]
    default = Path("models/Qwen3-4B-Q4_K_M.gguf")
    if default.exists():
        return [default]
    return [_FALLBACK_MODEL]


MODEL_PATHS = _resolve_model_paths()


def _demo_catalog_and_client(base_url: str, model_name: str) -> tuple:
    version = ScenarioVersion.model_validate(demo_document())
    definitions = build_fact_definitions(version)
    catalog = build_fact_catalog(definitions)
    llm = LlamaCppClient(
        base_url=f"{base_url}/v1", model_name=model_name, n_ctx=4096, default_timeout_ms=20_000
    )
    return catalog, llm


@pytest.mark.parametrize("model_path", MODEL_PATHS, ids=lambda p: p.name)
async def test_llama_cpp_client_contract(model_path: Path, tmp_path: Path) -> None:
    require_model_env(paths=(model_path,))
    server: ServerHandle = start_server_trying_binaries(model_path, tmp_path)
    catalog, llm = _demo_catalog_and_client(server.base_url, model_path.stem)
    metrics = NullMetricsRecorder()
    interpreter = DialogueInterpreter(
        llm, metrics, config=InterpreterConfig(timeout_ms=20_000, max_tokens=200)
    )
    catalog_ids = {entry.fact_id for entry in catalog}

    try:
        # One warm-up call, discarded from the measurements (owner request).
        await interpreter.interpret("Алло", (), catalog, request_id="warmup", turn_index=0)
        server.sample_vram()

        results: list[dict[str, object]] = []
        for index, utterance in enumerate(UTTERANCES_RU):
            before = len(metrics.metrics)
            started = time.perf_counter()
            outcome = await interpreter.interpret(
                utterance, (), catalog, request_id=f"contract:{index}", turn_index=index
            )
            latency_ms = (time.perf_counter() - started) * 1000
            server.sample_vram()
            call_metrics: list[InferenceMetric] = metrics.metrics[before:]

            assert not outcome.fallback_used, (
                f"{utterance!r} fell back: {outcome.failure_reason} (model={model_path.name})"
            )
            all_ids = (
                {fact.fact_id for fact in outcome.interpretation.requested_facts}
                | {a.fact_id for a in outcome.interpretation.operator_assertions}
                | set(outcome.interpretation.confirmation_targets)
            )
            assert all_ids <= catalog_ids, (
                f"{utterance!r} referenced ids outside the catalog: {all_ids - catalog_ids}"
            )

            output_tokens = sum(m.output_tokens or 0 for m in call_metrics)
            prompt_tokens = call_metrics[0].input_tokens if call_metrics else None
            tokens_per_s = (
                output_tokens / (latency_ms / 1000) if output_tokens and latency_ms > 0 else None
            )
            results.append(
                {
                    "utterance": utterance,
                    "latency_ms": round(latency_ms, 1),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": output_tokens,
                    "tokens_per_s": round(tokens_per_s, 1) if tokens_per_s else None,
                    "repair_retry_used": outcome.repair_retry_used,
                    "interpretation": outcome.interpretation.model_dump(mode="json"),
                }
            )

        assert not llm.think_leaks, f"<think> text leaked for request ids: {llm.think_leaks}"

        # Streaming: first delta arrives, and cancel() stops the stream.
        stream = llm.stream(
            [ChatMessage(role="user", content="Скажи одно короткое русское слово.")],
            request_id="contract:stream",
            max_tokens=40,
            temperature=0.2,
            timeout_ms=20_000,
        )
        first_delta = await stream.__anext__()
        await llm.cancel("contract:stream")

        print(f"\n=== LLM contract measurements: model={model_path.name} ===")
        print(
            f"binary={server.binary} offload={server.offload_mode} "
            f"n_gpu_layers={server.n_gpu_layers} "
            f"vram_free_mb_at_start={server.vram_free_mb_at_start}"
        )
        print(f"load_s={server.load_seconds:.1f} peak_vram_mb={server.peak_vram_mb}")
        print(f"first stream delta: {first_delta.text!r}")
        for row in results:
            print(row)
    finally:
        await llm.close()
        terminate(server.process)
