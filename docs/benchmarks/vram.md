# VRAM benchmark (SPEC §26, §27, §40; HLD `60-inference-ops.md` §7.5) — E19-D / E19-D2 / E19-D3

Machine: `andreipc-B660M-DS3H-DDR4`, RTX 3060 Ti 8 GB. Date: **2026-09-22**. Script:
`benchmarks/benchmark_vram.py`. NVML mode: `pynvml` (every run — `make deps` installed it earlier
this epic; the `nvidia-smi` fallback was not needed). §1's `DEV_3060TI_SHARED` run and §2.1's first
two `DEV_3060TI` attempts ran while the owner's resident process (PID 1082982, ~4638-5000 MiB) was
still up, untouched throughout, and every run confirms that with `nvidia-smi --query-compute-apps`
before/after. §2's final `DEV_3060TI` run (E19-D3) ran **after the owner stopped that process** —
the card was genuinely free (~6.2-7.8 GB), which is what let the three-model sequence complete; that
run's own before/after `nvidia-smi --query-compute-apps` is empty (no process at all), not "only
PID 1082982".

Sequence (HLD §7.5, fixed): nothing loaded → load VAD → load ASR → load TTS → wait for llama-server
→ sample idle → run `--turns 20` realistic turns → sample peak → idle again, NVML sampled every
100 ms throughout. **Note (addendum (b)):** `--turns` runs turns sequentially, not concurrently —
accepted for one session (a single session's turn is sequential by construction); multi-session
concurrency is `TODO(POST-I1)` (reworded from the epic's own open-item marker, E20-D2, 2026-09-22 — genuinely open past
this epic's close, not claimed by any E20 phase-1 FILES list; `docs/AUDIT.md` §3 deviation 8): a
`benchmark_vram.py` sequence that drives several sessions' turns concurrently (matching
`parallel_slots` genuinely being shared across sessions, not just declared) has never been built or
run.

## 1. `DEV_3060TI_SHARED` — OK, real combined peak

Free VRAM before: 3196 MiB. Command:

```
flock -w 10800 /tmp/teamwork-112-maxxing/gpu.lock bash \
  /tmp/teamwork-112-maxxing/logs/e19-d-vram-shared-run.sh
# = uv run python benchmarks/benchmark_vram.py --profile DEV_3060TI_SHARED --provider real --turns 20
```

This profile runs ASR (GigaAM, cpu) and TTS (Piper, cpu) off the GPU entirely — the LLM
(Qwen3.5-2B Q4_K_M, `--parallel 2`, GPU_FULL) is the **only** GPU-resident component, so its
combined peak is a true, not partial, measurement:

| Step | delta_mb | Cumulative used_mb |
|:--|--:|--:|
| baseline (owner's process) | — | 4996 |
| VAD (silero, cpu) | 0 | 4996 |
| ASR (GigaAM, cpu) | 0 | 4996 |
| TTS (Piper, cpu) | 0 | 4996 |
| LLM (Qwen3.5-2B, GPU_FULL n_gpu_layers=999, `--parallel 2`) | **1559** | 6555 |
| 20 sequential turns | (no further growth) | 6555 |

`idle_after_load_mb: 6555`, `peak_mb: 6555`, **`project_peak_mb: 1559`**, `free_min_mb: 1636`.
Free VRAM after (worker/server all stopped by the script): 3196 MiB.
`nvidia-smi --query-compute-apps` after: only PID 1082982.

**This confirms the earlier single-call e13-b4 measurement (1558 MB) almost exactly** — 1 MB of
sampling-window noise between a one-shot generation call and a genuine 20-turn `benchmark_vram.py`
sequence. **Applied to the profile**: `backend/app/config/profiles/DEV_3060TI_SHARED.yaml` —
`measured_peak_vram_mb: 1559`, `measured_at: 2026-09-22` (was 1558 / 2026-09-21).

Source: `docs/benchmarks/results/vram-DEV_3060TI_SHARED-20260922T050401Z.{json,csv}`.

## 2. `DEV_3060TI` — OK, real combined three-model peak (E19-D3)

**The owner stopped their GPU process (PID 1082982) between E19-D and this follow-up (E19-D3)**,
freeing the card to ~6.2-7.8 GB. That is the fact that makes this section's result possible — see
§2.1 for the two PARTIAL attempts this profile went through first, on the shared card, and §2.2 for
two real script bugs this run surfaced and fixed.

Free VRAM before: 7842 MiB. Command:

```
flock -w 10800 /tmp/teamwork-112-maxxing/gpu.lock bash \
  /tmp/teamwork-112-maxxing/logs/e19-d-vram-dev-run.sh
# starts workers/tts_qwen3 (SIM_TTS_QWEN3_MODEL=0.6B, NOT pre-warmed) on 8112 itself, waits
# /health, then:
# uv run python benchmarks/benchmark_vram.py --profile DEV_3060TI --provider real --turns 20 \
#   --tts-base-url http://127.0.0.1:8112
# stops the worker itself afterward
```

This profile puts ASR (GigaAM, cuda), TTS (Qwen3-TTS, cuda via the worker) and the LLM
(Qwen3.5-2B, GPU_FULL) all on the GPU at once — the "dedicated card" assumption `DEV_3060TI`
documents (§1 of `docs/hld/60-inference-ops.md`). With the card actually free, the full sequence
completed:

| Step | delta_mb | Cumulative used_mb | Outcome |
|:--|--:|--:|:--|
| baseline | — | 350 | |
| VAD (silero, cpu) | 0 | 350 | OK |
| ASR (GigaAM v3_e2e_ctc, cuda, float16) | **1530** | 1880 | OK |
| TTS (Qwen3-TTS 0.6B, via the tts_qwen3 worker) | **2373** | 4253 | OK |
| LLM (Qwen3.5-2B, GPU_FULL n_gpu_layers=999, `--parallel 2`) | **1559** | 5812 | OK |
| 20 sequential turns | peak reached during turns | 5910 | OK, all 20 completed |

`idle_after_load_mb: 5812`, `peak_mb: 5910`, **`project_peak_mb: 5560`** (`5910 − 350`),
`free_min_mb: 2281`. Status: **`OK`**. Free VRAM after (worker and llama-server both stopped by the
script): 7842 MiB (back to the pre-run figure). `nvidia-smi --query-compute-apps` after: **empty**
— no process at all (the owner's process is stopped; nothing of this task's own is left running).

**Applied to the profile**: `backend/app/config/profiles/DEV_3060TI.yaml` —
`measured_peak_vram_mb: 5560`, `measured_at: 2026-09-22`. Margin check:
`vram_budget_mb 7168 − 5560 = 1608 ≥ min_vram_margin_mb 512` — passes outright, no DEV-only warning
needed any more (`validate_vram_margin` confirmed not to raise or warn).
`backend/tests/unit/config/test_profile.py::test_dev_3060ti_passes_with_a_measured_margin` asserts
this; the old `test_dev_profile_with_no_measurement_only_warns` (which used to load `DEV_3060TI`
itself to exercise the "unmeasured" branch) now uses a synthetic profile
(`DEV_3060TI_SHARED.model_copy(update={"measured_peak_vram_mb": None})`) so the *mechanism* stays
tested independently of which shipped profile currently has a real number.

Source: `docs/benchmarks/results/vram-DEV_3060TI-20260922T092121636Z.{json,csv}`.

### 2.1 History — two PARTIAL attempts on the shared card (E19-D, E19-D2)

Before the owner stopped their process, this profile was attempted twice with only ~3.2 GB free
beside it, and both came back honestly `PARTIAL`:

1. **E19-D** (first attempt): ASR loaded (delta 1527 MB), then the TTS step (Qwen3-TTS 0.6B worker)
   FAILED — `TtsTimeoutError: tts_qwen3 warm_up timed out after 20000ms; free_mb=585`. Free VRAM had
   dropped to 585 MiB by the time the worker's cold load+generate was running; the load became slow
   enough under VRAM pressure that it did not finish inside the client's 20 s timeout. `project_peak_mb`
   observed (2610 MB) was deliberately NOT written anywhere as a measurement — the sequence never
   completed.
2. **E19-D2** (retry, same shared-card conditions): same failure mode, `free_mb=6311` this time —
   **not** VRAM-constrained at all; a genuinely cold worker load can exceed a 20 s client timeout
   regardless of headroom. This pointed at the real bug fixed in §2.2 below.

Both superseded; their result files were removed from `docs/benchmarks/results/` when this run's OK
result replaced them (only the current, completed measurement is kept, per R8 — a superseded
PARTIAL/FAILED pair is not itself a citable number).

### 2.2 Two real script bugs found and fixed in `benchmark_vram.py` (E19-D3)

1. **`_load_tts`'s TTS client used the wrong timeout.** `Qwen3TTS`'s default `timeout_ms` (20 000)
   is sized for an already-warm, per-turn production call (SPEC §27's turn budget) — this
   benchmark's TTS *load* step is a cold load-then-generate (observed 2.4-43 s across real runs,
   `docs/benchmarks/tts.md`), exactly what the profile's own `warmup.timeout_ms` (60 000 on
   `DEV_3060TI`) already budgets for (HLD 60 §4.2). Fixed: `_load_tts` now constructs `Qwen3TTS`
   with `timeout_ms=profile.warmup.timeout_ms` for this one client instance (reused for the
   `--turns` loop afterward, where per-turn calls are already warm and fast).
2. **`_run_turns` passed an invalid `TtsVoiceSpec.voice_id`.** `voice = TtsVoiceSpec(voice_id="bench",
   ...)` — `"bench"` is not one of the four vendor speakers, so `Qwen3TTS.stream()` rejected every
   turn's TTS call with `ValueError`, and because this happened *after* every load step had already
   succeeded, the whole run went `FAILED` with `samples: []` — discarding the perfectly good
   VAD/ASR/TTS/LLM load-phase deltas the sequence had already measured. Same bug class (and fix) as
   `benchmark_tts.py`'s `_synthesize`/`_cancel` (E19-D): `voice_id=""` lets `Qwen3TTS` fall back to
   its constructed default speaker. **Also hardened**: `_run_turns` now returns `(turns_done,
   failure)` instead of raising, and a turn-phase exception is reported as `PARTIAL` with whatever
   deltas the load steps measured, rather than discarding them as `FAILED` — matching the same
   "an honest PARTIAL, not a silent data-losing FAILED" rule `_Steps.step()` already applies to the
   load steps.

`uv run pytest -q benchmarks/tests` — 48 passed, both before and after these fixes.

### 2.3 The same stack with the Qwen3-TTS **1.7B** variant (E20-I, 2026-09-22) — does NOT fit

§2's peak was measured with `SIM_TTS_QWEN3_MODEL=0.6B`, but the profile left `model_variant` null,
so the worker would have loaded its own default, the 1.7B. Re-run identically with 1.7B (free VRAM
before 7842 MiB; `/tmp/teamwork-112-maxxing/logs/e20-i-vram-dev-run.sh`, 20 turns) —
`docs/benchmarks/results/vram-DEV_3060TI-20260922T192503527Z.json`, status OK:

| Step | delta_mb |
|:--|--:|
| VAD (Silero, cpu) | 0 |
| ASR (GigaAM v3_e2e_ctc, cuda) | 1530 |
| TTS (Qwen3-TTS **1.7B**) | **4299** |
| LLM (Qwen3.5-2B) | 1515 — **GPU_PARTIAL, 23 layers** (only 2013 MB free when it started) |
| **project_peak_mb** | **7448** (> `vram_budget_mb` 7168; card minimum free 393 MB) |

The 1.7B costs +1.9 GB over the 0.6B, pushes the LLM partly onto the CPU (slower caller replies)
and exceeds the budget. **Ruling (by measurement): `DEV_3060TI` ships `tts.model_variant: "0.6B"`**
— the variant its `measured_peak_vram_mb: 5560` describes and the one `make models` downloads.
The variant now reaches the worker through `make profile-env` (`SIM_TTS_QWEN3_MODEL` in
`infra/.env.profile`, read by compose's `tts-qwen3` and `make run-tts-qwen3`); before E20-I it
was hard-coded to 1.7B in compose, the Makefile and `.env.example`, whatever the profile said.
1.7B stays selectable for a card with ~2 GB more headroom (owner item: it is the voice the owner
evaluated as "very good"; RTF 0.823 vs 0.848, so it is a quality choice, not a speed one).

## 3. Reading for the owner

**With the owner's GPU process stopped, `DEV_3060TI`'s three simulator components load together and
run 20 real turns without incident: 5560 MB total (ASR 1530 + TTS 2373 + LLM 1559), comfortably
inside the profile's 7168 MB budget with a 1608 MB margin.** `DEV_3060TI_SHARED` (§1, LLM-only on
GPU, 1559 MB) remains the profile to use whenever the card is shared with other GPU work — its
budget (3000 MB) is sized for exactly that case and its margin (1441 MB) is tighter but still safe.
Both profiles now carry a completed, dated, real measurement; nothing here is invented, and the two
PARTIAL attempts that came before this one are kept as history (§2.1), not silently overwritten.

## 4. `TODO(POST-I1)`

Multi-session concurrency: `benchmark_vram.py --turns N` runs N turns of **one** session
sequentially (addendum (b), accepted for this epic). A benchmark that drives several concurrent
sessions' turns against the same loaded models — closer to what `parallel_slots` in the LLM config
is actually for — has never been built. This was out of E19's scope and stayed out of E20's too (no
FILES list in this epic's phase-1 concurrency note claims it, and E20-C's §46 walk exercises one
session at a time); whoever picks it up post-I1 should decide whether it is a
`benchmark_vram.py --sessions N` flag or a separate script. Reworded from the epic's own
open-item marker (E20-D2, 2026-09-22) — the epic is closing without this being picked up.

## 5. How to reproduce

```bash
# SHARED (LLM only on GPU) — OK on either a shared or a free card
flock -w 10800 /tmp/teamwork-112-maxxing/gpu.lock \
  bash /tmp/teamwork-112-maxxing/logs/e19-d-vram-shared-run.sh

# DEV (three GPU models) — OK once the card is actually free (>= ~6 GB); PARTIAL if something
# else is resident (§2.1's history)
flock -w 10800 /tmp/teamwork-112-maxxing/gpu.lock \
  bash /tmp/teamwork-112-maxxing/logs/e19-d-vram-dev-run.sh
```
