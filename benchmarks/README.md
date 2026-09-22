# benchmarks

Distribution `sim-benchmarks` (workspace member, `package = false`). The five SPEC §35/§40
benchmark scripts live here, designed in `docs/hld/60-inference-ops.md` §7:

| File | SPEC | Measures |
|:--|:--|:--|
| `benchmark_asr.py` | §19, §40 | latency, RTF, WER, CER, entity accuracy per category × condition × source |
| `benchmark_llm.py` | §20-§22, §40, §43 | TTFT, tokens/s, structured-output validity, forbidden-fact leak rate, dialogue consistency, explanation latency |
| `benchmark_tts.py` | §25, §40 | first-audio latency, total synthesis latency, RTF, peak VRAM, cancellation behaviour |
| `benchmark_e2e.py` | §27, §40 | `USER_SPEECH_ENDED` → first caller audio, the per-stage split, barge-in cutoff |
| `benchmark_vram.py` | §26, §40 | idle residency and peak across a realistic load sequence |
| `_common.py` | §27 | the CLI, profile loading, model-path mapping, NVML sampling, percentiles, WER folding, **the one result writer** |
| `_llama.py` | — | a thin wrapper over the `backend/tests/models/` llama-server harness (reused, not copied) |

**How to run them, the envelope and the honesty rule are documented once, in
`docs/benchmarks/README.md`.** This file covers only what is specific to the directory.

## The gate never runs a benchmark; it runs their shape

`benchmarks/tests/` drives every script's `main()` with `--provider fake` into a tmp directory and
asserts the envelope's keys, the CSV header, `status: "OK"` and the `NOT_RUN`/`FAILED` honesty
rules. It needs no GPU, no model file, no network and no running server, and it is in the root
`pyproject.toml`'s `testpaths`, so `make test-backend` collects it like any other suite. Nothing in
it is marked `requires_models`, and nothing in it asserts a number a fake produced.

The real runs are the `make bench-*` targets. They are deliberately absent from `gate`/
`gate-backend` (D13).

## Two deliberate dev-tooling allowances

1. **`backend/` goes on `sys.path`** (`_common.ensure_backend_on_path()`). `app.*` and
   `voice_agent.*` are ordinary workspace dependencies, but `tests.*` is not installed, and HLD
   §7.2 says the §43 adversarial attack matrix must be **reused** from
   `backend/tests/adversarial/` "rather than duplicating" it. `_llama.py` reuses
   `backend/tests/models/conftest.py`'s llama-server harness the same way, and
   `benchmark_e2e.py` reuses the voice-pipeline test's in-memory Unit of Work. These are dev
   tools; nothing in `backend/app/**` or `workers/**` imports anything from here.
2. **The scripts import each other as top-level modules** (`from _common import ...`), because
   they are run as `uv run python benchmarks/benchmark_asr.py`, which puts this directory on
   `sys.path[0]`. `benchmarks/tests/conftest.py` does the same for the test run.

`backend/tools/check_imports.py` forbids `livekit` anywhere under `benchmarks/`; the LiveKit
transport for `benchmark_e2e.py --transport livekit` therefore lives in
`workers/voice_agent/voice_agent/transport/headless_client.py`, which is the only place the SDK is
imported (D9, SPEC §15).

## Corpora

The scripts are corpus-driven and own no data of their own:

```
benchmarks/data/asr/manifest.jsonl + clean/ noisy/   # E19-B
benchmarks/data/llm/{interpreter_cases,dialogue_cases}.jsonl
benchmarks/data/tts/lines.jsonl
benchmarks/data/e2e/turns.jsonl
```

A missing corpus is a `NOT_RUN` naming the path, never an empty run that reports zero.
`benchmarks/tests/fixtures/` holds the tiny stand-ins the gate-side shape tests use; they are
fixtures, not a corpus, and no number is ever drawn from them.

## Precursor tools (kept, not replaced)

`interpreter_eval/`, `caller_eval/` and `tts_qwen3_0_6b_real_run.py` are the one-off real-model
evaluation tools E13/E14 wrote, and the measurements in those tasks' reports come from them. They
predate the HLD §7.0 envelope and write their own result shape. `benchmark_llm.py` **reuses**
`interpreter_eval/scoring.py` (a stdlib-only pure module) rather than reimplementing its scoring,
so the two cannot drift.
