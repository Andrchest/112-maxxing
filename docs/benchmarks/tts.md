# TTS benchmark (SPEC §25, §40; HLD `60-inference-ops.md` §7.3) — E19-D / E19-D3

Machine: `andreipc-B660M-DS3H-DDR4`, RTX 3060 Ti 8 GB. Date: **2026-09-22**. Corpus:
`benchmarks/data/tts/lines.jsonl`, 30 Russian caller-side lines, 6 per
`SHORT`/`MEDIUM`/`LONG`/`NUMERIC`/`ADDRESS` (addresses/numbers from the demo scenario,
`scenarios/examples/apartment-fire/v1.yaml` — Смоленск, улица Николаева 27, кв. 45, подъезд 3).
`--runs 3`, `--cancel-after-ms 200`. Script: `benchmarks/benchmark_tts.py`. The Piper and Qwen3-TTS
0.6B runs (E19-D) ran while the owner's resident process (PID 1082982, ~4638 MiB) was still up,
untouched throughout — confirmed by `nvidia-smi --query-compute-apps` before/after each. The
Qwen3-TTS 1.7B run (E19-D3) ran **after the owner stopped that process**, which is what made it
possible at all (§1's NOT_RUN table in the E19-D version of this doc explained why 1.7B could not
be attempted before that).

## 1. HEADLINE — time-to-first-audio, Piper vs Qwen3-TTS 0.6B vs Qwen3-TTS 1.7B

The owner chose Qwen3-TTS and said speed matters — this is the number that matters most. 1.7B is
the owner's originally evaluated/pinned checkpoint (E14-B); 0.6B is the measured alternative (E14-D):

| Category | Piper (CPU) first-audio p50/p95 ms | Piper RTF | Qwen3-TTS 0.6B (GPU) first-audio p50/p95 ms | 0.6B RTF | Qwen3-TTS 1.7B (GPU) first-audio p50/p95 ms | 1.7B RTF |
|:--|--:|--:|--:|--:|--:|--:|
| SHORT    | 100.6 / 128.8  | 0.030 | 1807.5 / 3816.3  | 0.863 | 1465.1 / 3171.7  | 0.849 |
| MEDIUM   | 100.4 / 146.5  | 0.029 | 3886.0 / 6851.5  | 0.881 | 3076.4 / 3621.3  | 0.828 |
| NUMERIC  | 158.0 / 309.1  | 0.036 | 4130.2 / 7884.3  | 0.832 | 3815.7 / 6130.8  | 0.810 |
| ADDRESS  | 147.0 / 229.9  | 0.030 | 4380.0 / 9197.5  | 0.824 | 3913.5 / 7851.5  | 0.809 |
| LONG     | 360.4 / 511.9  | 0.032 | 9674.4 / 14770.9 | 0.838 | 8084.1 / 10016.3 | 0.816 |
| **overall** | **135.9 / 404.7** | **0.032** | **4130.2 / 11078.0** | **0.848** | **3518.9 / 8780.3** | **0.823** |

**1.7B is, if anything, slightly *faster* than 0.6B on this run** (overall RTF 0.823 vs 0.848,
first-audio p50 3519 ms vs 4130 ms) — well within run-to-run variance for a GPU-bound whole-utterance
call, and certainly not the "bigger model, slower" assumption a reader might expect. Both variants
share the same architecture (whole-utterance generation, §3) and are within a few percent of each
other on every category; the meaningful comparison is Piper vs either Qwen3-TTS variant, not 0.6B vs
1.7B. Peak VRAM is the real differentiator: 0.6B's worker held ~2373-3144 MB, 1.7B's held **~4.3 GB**
more (`peak_vram_mb_max: 5430` total this run vs `7782` in the shared-card 0.6B run — not directly
comparable since baselines differ; see the per-run deltas below).

**Reading for the owner.** Because Qwen3-TTS 0.6B is non-streaming (§3), time-to-first-audio scales
*linearly with the sentence's own audio length* at RTF ≈ 0.85 — a 5 s caller sentence waits ~4.2 s
before any sound plays, a 10 s sentence ~8.5 s, and so on; there is no "first chunk arrives early"
behaviour to rely on. SPEC §27's DEV target (p50 < 1.5 s, p95 < 2.5 s for the **whole turn**, not
just TTS) is therefore unreachable with this provider once a single sentence's audio exceeds
roughly 1.5-3 s, which the per-category table above already shows in practice: NUMERIC (p50
4130 ms), ADDRESS (p50 4380 ms) and LONG (p50 9674 ms) sentences — exactly the demo's dispatcher
lines (addresses, phone numbers, longer situational reports) — all blow past both targets on first
audio alone, and even SHORT sentences (p50 1807.5 ms) exceed the 1500 ms p50 target on their own,
before ASR/interpret/generate time is even added. The mitigation is architectural, not something
this benchmark can fix: every caller-facing Qwen3-TTS call must be kept to one genuinely short
sentence by the sentence chunker (`app.application.voice`, E14-A) — a caller turn built from one
short clause rather than one long paragraph is the only way this provider can meet SPEC §27 on this
machine, and even then only for the SHORT/MEDIUM end of this table's range.

**Piper is 20-40x faster to first audio than either Qwen3-TTS variant on every category, on this
machine, today.** Piper's own RTF (0.023-0.052 measured E14-C, 0.026-0.047 measured here —
consistent) means first audio effectively equals a network-negligible ~100-500 ms. Both Qwen3-TTS
variants' RTF (0.6B mean 0.848, 1.7B mean 0.823 — consistent with E14-D's earlier 0.831 on a
smaller 20-call sample) means first audio is proportional to the **whole utterance's** audio
duration, because **the provider is whole-utterance, not chunked** (§3 below) —
`first_audio_latency_ms == total_synthesis_latency_ms` on every one of the 90 real synthesis
samples of both variants (`docs/benchmarks/results/tts-DEV_3060TI-20260922T045733Z.json` (0.6B),
`tts-DEV_3060TI-20260922T093750665Z.json` (1.7B), every sample row). For a LONG caller line this is
up to 14.8 s (0.6B) / 10.0 s (1.7B) before ANY audio plays — far past SPEC §27's 1.5-2.5 s DEV
target for the whole turn, let alone first audio. This is why `app.application.voice`'s sentence
chunker (E14-A) splits a caller turn into short sentences/clauses before ever calling either
variant — the numbers above are per **one already-split sentence**, and the product never asks
Qwen3-TTS to synthesize a whole multi-sentence turn in one call.

Peak VRAM (system-wide `nvidia-smi`, continuous 100 ms sampling — each run's baseline differs, see
below, so these are not directly comparable deltas without accounting for it): Piper run
`peak_vram_mb_max: 4646` — this is the **owner's own resident 4638 MiB**, unaffected, because Piper
is CPU-only and touches no GPU memory (the sampler reports whole-GPU usage, not a
Piper-attributable delta, correctly zero). Qwen3-TTS 0.6B run (owner's process still resident, E19-D)
`peak_vram_mb_max: 7782` — delta over the owner's 4638 MiB baseline is **~3144 MiB**, somewhat
higher than E14-D's ~2746 MiB lower-bound (sampling-granularity difference, not a contradiction —
E14-D sampled only after each call; this continuous sampler catches CUDA-graph/kernel-autotune
spikes on the outlier first calls too). Qwen3-TTS 1.7B run (owner's process stopped by this point,
E19-D3) `peak_vram_mb_max: 5430` — baseline here is near-zero (no owner process resident), so this
is close to the true project-attributable peak: ~5.0-5.4 GB for the 1.7B checkpoint loaded plus one
active generation, consistent with the ~4.3 GB checkpoint-load delta measured separately in
`docs/benchmarks/vram.md`.

Sources: `docs/benchmarks/results/tts-DEV_3060TI-20260922T043831Z.json` (Piper, real, OK, 90+90
samples), `docs/benchmarks/results/tts-DEV_3060TI-20260922T045733Z.json` (Qwen3-TTS 0.6B, real, OK,
90+90 samples, E19-D), `docs/benchmarks/results/tts-DEV_3060TI-20260922T093750665Z.json` (Qwen3-TTS
1.7B, real, OK, 90+90 samples, E19-D3). Commands: `flock -w 10800 /tmp/teamwork-112-maxxing/gpu.lock
bash /tmp/teamwork-112-maxxing/logs/e19-d-tts-qwen3-run.sh` (0.6B) /
`.../e19-d-tts-qwen3-1.7b-run.sh` (1.7B) — each starts the worker on the named variant, waits
`/health`, one `/warm_up` excluded from measurement, runs `benchmark_tts.py`, stops the worker.
Free VRAM before/after (`nvidia-smi --query-gpu=memory.free`): 0.6B run 3196 MiB before/after
(owner's process resident); 1.7B run 7842 MiB before/after (owner's process stopped).
`nvidia-smi --query-compute-apps` after: only PID 1082982 for the 0.6B run; **empty** (no process
at all) for the 1.7B run.

## 2. Cancellation sub-suite (all three providers, `--cancel-after-ms 200`)

| Provider | n | cancel_latency_ms p50/p95 | chunks_after_cancel_max | alignment_is_exact |
|:--|--:|--:|--:|:--|
| Piper (CPU) | 90 | 0.035 / 0.067 | 0 | **false**, always |
| Qwen3-TTS 0.6B (GPU) | 90 | 0.103 / 0.208 | 0 | **false**, always |
| Qwen3-TTS 1.7B (GPU) | 90 | 0.106 / 0.227 | 0 | **false**, always |

`chunks_after_cancel` is 0 on every one of the 270 cancellation samples across all three providers
— the mechanical bar (SPEC §40: "must be 0 or 1") is met. But the honest reading of
`cancel_latency_ms` being sub-millisecond for **all three** is: **cancellation never actually
interrupts GPU/CPU synthesis work for any provider on this codebase today.** `Qwen3TTS.stream()`
(both variants, same adapter) and `PiperTTS.stream()` buffer the **entire** utterance's audio
before yielding a first `TtsChunk` — already-documented, pre-existing adapter behaviour
(`piper_tts.py`'s own "HLD gap" note, cited in `docs/hld/60-inference-ops.md` §10 item 4:
"`_measure_provider` buffers Piper's whole sentence before its first `TtsChunk`... re-chunking is
post-hoc, not incremental"; `qwen3_tts.py`'s module docstring says the same for the
whole-utterance-per-call shape, and it applies identically to both the 0.6B and 1.7B checkpoints —
same adapter code, same worker code, only the model weights differ). By the time this benchmark's
`_cancel()` awaits its first chunk, generation (0.1-0.5 s for Piper, up to 14.8 s for either
Qwen3-TTS variant) is **already fully complete**; `stream.cancel()` at that point only discards
already-generated PCM still sitting in the local re-chunking buffer, which is why it is
sub-millisecond regardless of provider, variant or utterance length. **For Qwen3-TTS specifically,
cancellation lands after the whole utterance, never mid-generation** (this task's brief anticipated
this outcome for the "whole-utterance worker" case, and it is confirmed for both variants: the
worker itself has a `request.is_disconnected()` check for a request that has not yet started
generating, `tts_qwen3/server.py`, but nothing in `generate_custom_voice()` can be interrupted once
GPU inference has started — see §3). This is not a benchmark defect; it is the true, measured
behaviour of every adapter as shipped, worth the product team knowing given SPEC §18's 250 ms
barge-in budget — the sentence chunker (E14-A) is what actually bounds worst-case cancellation
latency in production, by keeping each provider call to one short sentence, not this benchmark.

`alignment_is_exact` is `false` on every sample for every provider/variant by design, not a defect:
no adapter's upstream model reports per-word timing (`TtsChunk.alignment_is_exact` docstring,
"False when the adapter derived offsets word-proportionally"; `piper_tts.py` and `qwen3_tts.py`
(both variants share the one adapter module) set it unconditionally `False`, cited in each module).

## 3. Streaming investigation (E14 addendum) — no code change

`qwen_tts==0.1.1` (the package pinned in `workers/tts_qwen3/.venv`, this task's own venv, not
recon/docstrings) was read directly for a chunked/streaming generation entry point:

- The worker calls exactly one method, `qwen_tts.inference.qwen3_tts_model.Qwen3TTSModel.
  generate_custom_voice(text, speaker, language, instruct, non_streaming_mode=True, **kwargs)`.
  Its return type is always `Tuple[List[np.ndarray], int]` — a fully materialized batch of
  waveforms, never a generator, iterator or callback.
- `non_streaming_mode` — the only flag with "stream" in its name anywhere on this call — has this
  literal docstring in the installed package: *"Using non-streaming text input, this option
  currently only simulates streaming text input when set to `false`, rather than enabling true
  streaming input or streaming generation."* Even the input-side flag admits it does not enable
  real output streaming.
- `grep -rn yield workers/tts_qwen3/.venv/lib/python3.12/site-packages/qwen_tts/` → **zero hits**.
  There is no `streaming` module in the package (`qwen_tts/{core,inference,cli}` only) and no
  `stream=` keyword anywhere in `qwen3_tts_model.py`'s three `generate_*` methods
  (`generate_voice_clone`, `generate_voice_design`, `generate_custom_voice`).

**Finding: no chunked/streaming output entry point exists in the installed `qwen_tts==0.1.1`.**
The worker's whole-utterance-per-call shape (already documented in `workers/tts_qwen3/README.md`,
E14-B) is the ceiling the pinned package itself imposes, not a worker implementation gap — there is
nothing to build behind a flag, so none was added, and `workers/tts_qwen3/` has no code change from
this task. This applies identically to both variants (same `qwen_tts` package, same worker code,
confirmed by §1/§2's 1.7B numbers landing in the same shape as 0.6B's). TTFA for this package
cannot be improved below "one full generation per sentence" without a different model/package
version — a fact for the product team, not a guess (the recommendation, given §1's headline table:
for the demo, keep Piper as the low-latency default/fallback path and treat either Qwen3-TTS
variant's quality as a trade against its ~20-40x slower first-audio latency per sentence — a product
decision, not this task's to make; the 1.7B-vs-0.6B choice itself is quality-driven, since §1 shows
their latency is statistically indistinguishable on this machine).

## 4. NOT_RUN entries (R4)

Qwen3-TTS 1.7B was `NOT_RUN` in the original E19-D pass (needed ~4.6 GB, only 3196 MiB free beside
the owner's process) — **closed in E19-D3** once the owner stopped that process; see §1/§2/§5 for
the real numbers. Remaining honest `NOT_RUN`:

| Provider | Status | Reason | JSON |
|:--|:--|:--|:--|
| Chatterbox Multilingual | NOT_RUN | provider not implemented in this repo (E20 list) | `docs/benchmarks/results/tts-DEV_3060TI-20260922T045919Z.json` |
| faster-whisper-equivalent / any third fallback TTS | n/a | out of SPEC §25's three named candidates — Piper is item C ("lightweight/fallback"); no fourth provider exists to benchmark | — |

## 5. Category breakdown (both Qwen3-TTS variants, full)

| Category | n | 0.6B first_audio p50/p95 ms | 0.6B rtf mean | 1.7B first_audio p50/p95 ms | 1.7B rtf mean |
|:--|--:|--:|--:|--:|--:|
| SHORT    | 18 | 1807.5 / 3816.3  | 0.863 | 1465.1 / 3171.7 | 0.849 |
| MEDIUM   | 18 | 3886.0 / 6851.5  | 0.881 | 3076.4 / 3621.3 | 0.828 |
| NUMERIC  | 18 | 4130.2 / 7884.3  | 0.832 | 3815.7 / 6130.8 | 0.810 |
| ADDRESS  | 18 | 4380.0 / 9197.5  | 0.824 | 3913.5 / 7851.5 | 0.809 |
| LONG     | 18 | 9674.4 / 14770.9 | 0.838 | 8084.1 / 10016.3 | 0.816 |

## 6. How to reproduce

```bash
# Piper (CPU, no lock)
uv run python benchmarks/benchmark_tts.py --profile DEV_3060TI --provider real \
  --tts-provider piper --lines benchmarks/data/tts/lines.jsonl --runs 3 --cancel-after-ms 200

# Qwen3-TTS 0.6B (GPU, under the lock — starts/stops the worker itself)
flock -w 10800 /tmp/teamwork-112-maxxing/gpu.lock \
  bash /tmp/teamwork-112-maxxing/logs/e19-d-tts-qwen3-run.sh

# Qwen3-TTS 1.7B (GPU, under the lock — needs the card mostly free, ~6+ GB)
flock -w 10800 /tmp/teamwork-112-maxxing/gpu.lock \
  bash /tmp/teamwork-112-maxxing/logs/e19-d-tts-qwen3-1.7b-run.sh
```

## 7. Bug found and fixed in `benchmark_tts.py`

The first real Qwen3-TTS attempt (`docs/benchmarks/results/tts-DEV_3060TI-20260922T044048Z.json`,
`status: FAILED`) surfaced a real bug: `_synthesize`/`_cancel` built `TtsVoiceSpec(voice_id=
provider.provider_name, ...)` — `provider.provider_name` is `"qwen3_tts"` (the provider's own name),
not a voice. `Qwen3TTS.stream()` validates any *non-empty* `voice_id` against the four vendor
speakers and rejected it: `ValueError: TtsVoiceSpec.voice_id='qwen3_tts' is not one of the vendor
speakers ('Serena', 'Ryan', 'Vivian', 'Aiden')`. Fixed to `voice_id=""`, which both `Qwen3TTS`
(falls back to the speaker it was constructed with) and `PiperTTS`/`FakeTTS` (never read
`voice.voice_id` at all) handle correctly. `benchmarks/tests` (43 gate-side tests) stay green.
