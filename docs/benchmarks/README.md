# `docs/benchmarks/` — durable benchmark results and model provenance

This directory holds the benchmark tables/reports the rest of the documentation cites (SPEC §40;
`docs/hld/60-inference-ops.md` §7) and, under `results/`, the small JSON/CSV envelopes those tables
are drawn from. `benchmarks/results/` (repo root) stays gitignored scratch — every number a doc,
profile or ruling depends on is copied here as a committed file, so `git blame` on a number always
finds the run that produced it.

See `docs/benchmarks/models.md` for the local model inventory (source repo, pinned revision,
sha256, licence, who downloaded it and when) and `docs/benchmarks/results/` for the raw envelopes.

## Index

| Doc | What it measures |
|:--|:--|
| [`asr.md`](asr.md) | ASR (GigaAM `v3_e2e_ctc`/`v3_ctc`, cuda+cpu): latency, RTF, WER/CER, entity accuracy, per category × condition × source |
| [`llm.md`](llm.md) | LLM (interpreter, dialogue, explanation suites across Qwen3.5-{0.8B,2B,4B}, Qwen3-4B, Qwen3-8B): latency, structured-output validity, forbidden-fact leak rate, dialogue consistency, the DEV-default bar table |
| [`tts.md`](tts.md) | TTS (Piper vs Qwen3-TTS 0.6B): time-to-first-audio, RTF, cancellation, the streaming-capability finding |
| [`e2e.md`](e2e.md) | SPEC §27's critical product metric (`speech_end_to_first_audio_ms`) and its stage split; barge-in |
| [`vram.md`](vram.md) | Idle/peak VRAM residency over a realistic VAD→ASR→TTS→LLM sequence, per-component deltas |
| [`models.md`](models.md) | Every model file on disk: source repo, pinned revision, sha256, licence, who downloaded it |

## Owner-facing summary (2026-09-22)

**SPEC §27's critical metric** (`speech_end_to_first_audio_ms`, trainee-stops-talking to
caller-audible-audio), **final (E19-E2/E19-E3):** in-process, real full dialogue chain,
`DEV_3060TI_SHARED`, `--runs 4` — **p50 1192 ms / p95 1864 ms / p99 2056 ms** against the DEV
targets of 1500 / 2500 ms, `meets_target: true`, on 35 of 36 scripted turns (the earlier 7-of-18
figure was the minority of turns that survived a since-fixed defect, see the six-bug paragraph
below). A full real LiveKit call also now runs end to end — the agent joins the room, 34 of 39
detected turns are answered, and **24 of 24 scripted barge-ins are cut off inside the 250 ms
budget over real WebRTC** — but its own latency figure cannot be published: `speech_end_to_
first_audio_ms` is stamped from two different clocks over that transport, so every real sample
came out negative and the benchmark discarded them rather than invent a percentile. The quoted
number above therefore remains the in-process one — a lower bound that excludes the LiveKit
media-plane hop. See `e2e.md`.

**TTS TTFA finding.** Piper meets SPEC §27's target trivially (overall first-audio p50 **136 ms**).
Qwen3-TTS, the owner's chosen default, is whole-utterance-per-call (no chunked/streaming output
exists in the installed `qwen_tts==0.1.1` package) — **20-40x slower to first audio** than Piper on
every text category (p50 **4130 ms** on a NUMERIC-category sentence, 0.6B variant). The 1.7B
variant (the owner's originally evaluated checkpoint) is now measured too: mean RTF **0.823**,
first-audio p50 **3519 ms** / p95 **8780 ms** — latency-indistinguishable from 0.6B (0.848 RTF),
so the 0.6B/1.7B choice is a quality decision, not a latency one. The mitigation already in the
product is the sentence chunker, which keeps every call to one short clause; nothing in this
benchmark reveals a fix at the adapter level. See `tts.md`.

**LLM bar verdict.** No candidate model clears E19's DEV quality bar (`explicit_acc ≥ 0.95`,
`structured_output_validity_rate ≥ 0.95`, `forbidden_fact_leak_rate == 0`,
`dialogue_consistency_rate ≥ 0.90`); `forbidden_fact_leak_rate` is **0.0 on every model tested**
(SPEC §43's target is met everywhere). Qwen3.5-2B stays the DEV default: fastest by more than 2x
(combined p50 462.5 ms) and the only model clearing 3 of the 4 criteria — only
`dialogue_consistency_rate` (0.538) fails. SPEC §22's own "Qwen3-4B" reaches consistency 0.929 but
at combined p50 ≈ 3.5 s, well past the development target. See `llm.md`.

**Six product bugs this epic's benchmarks found** (history kept in `e2e.md` §6; four fixed, two
open). (1) The caller went silent on ~40% of turns: a bare `}` utterance passed `Response
Validator`'s `EMPTY` check — fixed (E19-C2, grammar + validator). (2) The voice agent's per-call
VAD was never warmed, crashing the first real frame of every call — fixed (E19-E2). (3)/(4) The
voice agent could not join a LiveKit room at all: no per-call access token was ever minted, and the
failure was silently swallowed by an unawaited task — fixed (E19-E3: the agent now mints its own
token via the backend's `LiveKitTokenService`). (5) `speech_end_to_first_audio_ms` is not derivable
over LiveKit — the transport's capture-offset clock and the session-offset clock the TTS event uses
diverge — **open, `E20 R13`**. (6) The API's `SimulationRunner` tick and the voice agent deadlock on
the same `simulation_sessions` row lock at the shipped `SIM_SIM_TICK_MS` — **open, `E20 R14`**.

**What is NOT measured here, and why.**

- The `FINAL_3080TI_12GB`/`FINAL_3080TI_16GB` profiles: no RTX 3080 Ti and no Qwen3-8B GGUF file
  exist on this dev machine (see the section below).
- The LiveKit media-plane hop in the E2E latency number (above) — the transport is real and
  exercised, but its own latency figure is withheld pending `E20 R13`.
- faster-whisper (SPEC §19's optional ASR fallback): never installed by this project (E12 ruling).
- Chatterbox Multilingual TTS: provider not implemented in this repo.

## How to run a benchmark

Five scripts, the SPEC §35 names literally, designed in `docs/hld/60-inference-ops.md` §7. Every
one of them is a plain `uv run python benchmarks/benchmark_X.py`; the `make bench-*` targets are
the same command with `PROFILE`/`BENCH_ARGS` passed through, and **none of them is part of
`make gate`** (D13 — the gate runs the scripts against the *fake* providers only, for shape).

```
make bench-asr    # or: uv run python benchmarks/benchmark_asr.py
make bench-llm
make bench-tts
make bench-e2e
make bench-vram
make bench-all
make bench-asr PROFILE=DEV_3060TI_SHARED BENCH_ARGS="--model-version v3_ctc --device cpu"
```

Common flags (HLD §7.0, plus the two additive ones this epic ruled):

| Flag | Default | Meaning |
|:--|:--|:--|
| `--profile NAME` | `$SIM_MODEL_PROFILE`, else `DEV_3060TI` | which `backend/app/config/profiles/*.yaml` to read |
| `--out DIR` | `benchmarks/results/` | where the JSON+CSV pair goes |
| `--runs N` | 1 | repetitions of the whole corpus |
| `--seed N` | 0 | seed for every random choice |
| `--tag TEXT` | `""` | free text recorded in `config.tag` |
| `--provider fake\|real` | `real` | `fake` = the D13 fake providers (what the gate exercises) |
| `--models-root DIR` | `./models` | host directory the profile's `/models/<kind>/<file>` paths map onto |

Per-script flags: `benchmark_asr.py --manifest --model-version v3_e2e_ctc|v3_ctc --device cuda|cpu
--model-dir`; `benchmark_llm.py --suite interpreter|dialogue|explanation|all --interpreter-cases
--dialogue-cases --model-path --parallel --llama-server-bin --base-url`; `benchmark_tts.py --lines
--tts-provider piper|qwen3_tts|chatterbox|fake --tts-base-url --voice --cancel-after-ms
--no-cancel-suite --nvml`; `benchmark_e2e.py --turns-file --transport inprocess|livekit --scenario
--livekit-url --livekit-token --room --session-id --clock`; `benchmark_vram.py --turns
--start-tts-worker --tts-base-url --llama-server-bin --model-path --nvml`. `--help` on any script
prints the authoritative list.

## The envelope

Every run writes **two** files, `{out}/{name}-{profile}-{timestamp}.json` and a flat
`.csv` of the per-sample rows (SPEC §40 "export to JSON/CSV"). The CSV's header is the union of
the sample keys in first-seen order, so the two files always describe the same rows.

```json
{
  "schema_version": 1,
  "benchmark": "asr",
  "status": "OK",
  "profile": "DEV_3060TI",
  "git_sha": "…",
  "started_at": "…", "finished_at": "…",
  "hardware": {"gpu_name": "…", "driver": "…", "total_vram_mb": 8192},
  "config": { "…the relevant profile subtree, plus the CLI…" },
  "samples": [ … ],
  "aggregates": { … },
  "notes": [ … ]
}
```

`status` is `OK`, `PARTIAL`, `FAILED` or `NOT_RUN`. A `NOT_RUN` or `FAILED` result also carries a
`reason` string. Percentiles are nearest-rank over the raw samples, and every aggregate carries
its own `n`.

## The honesty rule

`benchmarks/_common.py::write_result()` is the **only** writer of a benchmark result, and it
raises `BenchmarkHonestyError` rather than emit:

1. an aggregate with no sample behind it;
2. a `NOT_RUN` result that carries any sample or any aggregate;
3. a `NOT_RUN`/`FAILED` result with no `reason`.

That is the mechanical form of SPEC §27's "Do not fake or hard-code benchmark values": there is no
default, no estimate and no carried-over figure anywhere in this directory. A missing model file, a
missing corpus, an unreachable TTS worker, a provider this repo has not implemented, a profile the
product itself refuses to start on — each is a `NOT_RUN` naming the exact path, URL or refusal,
with zero numbers. A CUDA OOM partway through a load sequence is a `PARTIAL` with the deltas that
were genuinely measured and a `reason` naming the step that failed and the free VRAM at that
moment; it is never re-run with a smaller number typed by hand.

Consequently: **no number in any document, profile YAML or HLD section may exist that one of these
JSON files (or an already-cited earlier task report, kept as history) does not contain.** Every
table below states the machine and the date it was measured on, and links the JSON under
`results/`.

<!-- E19-A appends the "how to run" / envelope / honesty-rule sections above this line. -->

## Not measured on the dev machine

This machine is an RTX 3060 Ti 8 GB, never a 3080 Ti — one thing SPEC §26/§40 asks for cannot be
produced here, by construction, not by omission:

- **`FINAL_3080TI_12GB` / `FINAL_3080TI_16GB`** (`backend/app/config/profiles/FINAL_3080TI_*.yaml`):
  no RTX 3080 Ti and no `Qwen3-8B-Q4_K_M.gguf` file exist on this machine (`models-llm-qwen3-8b` is
  defined — Makefile — but was never run, R4/R9 of this task's brief). Both profiles'
  `measured_peak_vram_mb` stay `null`; `validate_vram_margin` (HLD 60 §2.5) therefore refuses both
  at process start, which is the intended, honest state, not a bug. **On the target card:**
  `make models-llm-qwen3-8b && make bench-vram PROFILE=FINAL_3080TI_12GB` (and again for
  `FINAL_3080TI_16GB`), then paste the printed `project_peak_mb` and today's date into the YAML's
  `measured_peak_vram_mb` / `measured_at` fields — a human decision, per HLD §7.5, never the script.

**RESOLVED, E19-D3 (2026-09-22, superseding the paragraph E19-F wrote here):**
`DEV_3060TI`'s combined three-model peak — the gap this section used to describe as unmeasurable on
this shared machine — **has now been measured for real**: once the owner stopped their resident
~4.6 GB GPU process, `benchmark_vram.py`'s full "load VAD → ASR → TTS → llama-server, run 20 turns"
sequence completed with `status: OK`, `project_peak_mb` **5560** (VAD 0 + ASR 1530 + TTS 2373 +
LLM 1559), now written into `DEV_3060TI.measured_peak_vram_mb` (margin 1608 MB against the 7168 MB
budget). `DEV_3060TI_SHARED`'s LLM-only peak (1559 MB) remains the number to use whenever this card
is shared with other GPU work — both profiles now carry a real, non-`null` measurement.
`docs/benchmarks/results/vram-DEV_3060TI-20260922T092121636Z.json`, `vram.md`.

No VRAM number is invented for the one remaining gap above (SPEC §27).
