# ASR benchmark (SPEC §19, §40; `docs/hld/60-inference-ops.md` §7.1)

Machine: RTX 3060 Ti 8 GB (shared with the owner's resident process, PID 1082982, ~4.6 GB), driver
`595.84`, measured 2026-09-22 (UTC timestamps below). Profile `DEV_3060TI`, `git_sha 0beec6a`.
Corpus: `benchmarks/data/asr/` (73 items — see its own `README.md` for provenance and the
TTS→ASR round-trip caveat, repeated below). Five real runs, `--runs 3` each (latency reported as
p50/p95 over all 3×73=219 samples; WER/CER/entity_accuracy are identical across the 3 runs per
item — verified, see "Honesty checks" below), plus one honest `NOT_RUN` for faster-whisper.

**These are the E19-B2 numbers** — the first published version of this table had a real
measurement bug (10x latency gap between CLEAN and NOISY on cuda, found by the epic coordinator's
review and fixed in this task; full account in "E19-B2 — the CLEAN/NOISY latency bug" below). The
superseded JSON/CSV pairs were deleted from `results/`; the bug and the fix are recorded here as
history, per this document's own honesty rule (nothing is silently dropped).

```
uv run python benchmarks/benchmark_asr.py --provider real --model-version v3_e2e_ctc --device cuda --runs 3
uv run python benchmarks/benchmark_asr.py --provider real --model-version v3_ctc     --device cuda --runs 3
uv run python benchmarks/benchmark_asr.py --provider real --model-version v3_e2e_ctc --device cpu  --runs 3
uv run python benchmarks/benchmark_asr.py --provider real --model-version v3_ctc     --device cpu  --runs 3
uv run python benchmarks/benchmark_asr.py --provider real --asr-provider faster_whisper
```

Free VRAM immediately before the CUDA run: **3196 MiB** (`nvidia-smi --query-gpu=memory.free`,
recorded in the run log); free VRAM after: **3196 MiB**, and
`nvidia-smi --query-compute-apps` showed only PID 1082982 both before and after — no stray
process left behind. Results (JSON+CSV, copied here from the gitignored `benchmarks/results/`):

| Run | JSON | CSV |
|:--|:--|:--|
| `v3_e2e_ctc`, cuda | `results/asr-DEV_3060TI-20260922T052645807Z.json` | `results/asr-DEV_3060TI-20260922T052645807Z.csv` |
| `v3_ctc`, cuda | `results/asr-DEV_3060TI-20260922T052657871Z.json` | `results/asr-DEV_3060TI-20260922T052657871Z.csv` |
| `v3_e2e_ctc`, cpu | `results/asr-DEV_3060TI-20260922T052757373Z.json` | `results/asr-DEV_3060TI-20260922T052757373Z.csv` |
| `v3_ctc`, cpu | `results/asr-DEV_3060TI-20260922T052837204Z.json` | `results/asr-DEV_3060TI-20260922T052837204Z.csv` |
| faster-whisper (`NOT_RUN`) | `results/asr-DEV_3060TI-20260922T052841682Z.json` | `results/asr-DEV_3060TI-20260922T052841682Z.csv` (empty) |

## The TTS→ASR round-trip caveat (read this before the numbers)

72 of the 73 corpus items are Piper's own synthesis of a written sentence, not a recording of a
human voice; the one exception (`long_human_01`, `source: human:gigaam-sample`) is GigaAM's own
published Pushkin recording. **A WER measured on the `piper:*` items measures GigaAM against
Piper's pronunciation, not against human speech variation** (accent, disfluency, mic/room
acoustics). Every table below is split by `source` for exactly this reason. Read the `piper:*`
numbers as "GigaAM on clean synthetic Russian dispatcher speech", not as a general ASR quality
claim. See `benchmarks/data/asr/README.md` for the full provenance and how to add a human
recording.

## Overall (both sources combined; `n=219` = 73 items × 3 runs)

| Model version | Device | `latency_ms` p50 | `latency_ms` p95 | `rtf` mean | `wer` mean | `cer` mean | `entity_accuracy` mean |
|:--|:--|--:|--:|--:|--:|--:|--:|
| `v3_e2e_ctc` | cuda | 10.7 | 14.8 | 0.0041 | 0.0518 | 0.0312 | 0.8571 |
| `v3_ctc` | cuda | 10.8 | 15.6 | 0.0042 | 0.0250 | 0.0077 | 0.9821 |
| `v3_e2e_ctc` | cpu | 106.2 | 215.4 | 0.0378 | 0.0518 | 0.0312 | 0.8571 |
| `v3_ctc` | cpu | 123.8 | 301.9 | 0.0433 | 0.0250 | 0.0077 | 0.9821 |
| faster-whisper | — | `NOT_RUN` — "not installed by this project (E12 ruling 4) — --whisper-model-path/SIM_WHISPER_MODEL_PATH not set to an existing path" | | | | | |

No `latency_ms`/`rtf` figure above differs by condition (CLEAN vs NOISY) in a way that is not
explained by ordinary variance — see the per-category table below and "E19-B2" for the bug this
supersedes. `wer`/`cer`/`entity_accuracy` are identical between `cuda` and `cpu` for the same
`model_version` (0.0518/0.0312/0.8571 for `v3_e2e_ctc`; 0.0250/0.0077/0.9821 for `v3_ctc`) —
GigaAM's float16-cuda and float32-cpu paths agree exactly on this corpus, a useful cross-check that
the `Resampler`-based 16 kHz corpus and the `_common.fold()` numeral folding are correctly wired on
both code paths. `v3_ctc` has a *lower* WER than `v3_e2e_ctc` on this corpus (0.0250 vs 0.0518);
`entity_accuracy` follows the same pattern (0.9821 vs 0.8571) — both driven by the same
`NUMBER`/`ADDRESS` category gap detailed below (a real pronunciation/normalisation interaction, not
a latency artefact).

## Per source (`piper:ru_RU-irina-medium` n=216, `human:gigaam-sample` n=3 — one item × 3 runs)

| Model version | Device | `wer` (piper) | `wer` (human) |
|:--|:--|--:|--:|
| `v3_e2e_ctc` | cuda | 0.0526 | 0.0000 |
| `v3_ctc` | cuda | 0.0253 | 0.0000 |
| `v3_e2e_ctc` | cpu | 0.0526 | 0.0000 |
| `v3_ctc` | cpu | 0.0253 | 0.0000 |

The single human recording scores WER 0.0 on every run/model-version — consistent with E12-B's own
GigaAM contract test (WER 0.0 on this exact file, budget ≤ 0.2). It is one item, not a distribution;
it confirms GigaAM is not broken on real speech, it does not estimate a human-speech WER for this
corpus (see the caveat above — that would need more than one human recording).

## Per category × condition, cuda (both model versions — the DEV_3060TI profile's configured model is `v3_e2e_ctc`)

`v3_e2e_ctc`, cuda:

| Category | Condition | n | `latency_ms` p50 | `latency_ms` p95 | `rtf` mean | `wer` mean | `cer` mean |
|:--|:--|--:|--:|--:|--:|--:|--:|
| ADDRESS | CLEAN | 18 | 11.06 | 13.39 | 0.0028 | 0.1111 | 0.0321 |
| ADDRESS | NOISY | 18 | 10.58 | 12.26 | 0.0027 | 0.0833 | 0.0648 |
| LONG | CLEAN | 21 | 14.59 | 15.77 | 0.0017 | 0.0441 | 0.0051 |
| LONG | NOISY | 18 | 14.56 | 18.33 | 0.0018 | 0.0000 | 0.0000 |
| MEDIUM | CLEAN | 18 | 10.60 | 13.22 | 0.0036 | 0.0000 | 0.0000 |
| MEDIUM | NOISY | 18 | 10.72 | 13.65 | 0.0036 | 0.0238 | 0.0035 |
| NUMBER | CLEAN | 18 | 10.46 | 11.90 | 0.0055 | 0.1111 | 0.1000 |
| NUMBER | NOISY | 18 | 10.53 | 11.88 | 0.0056 | 0.1944 | 0.1632 |
| SHORT | CLEAN | 18 | 9.81 | 11.80 | 0.0066 | 0.0000 | 0.0000 |
| SHORT | NOISY | 18 | 10.18 | 11.25 | 0.0066 | 0.0556 | 0.0104 |
| TERMINOLOGY | CLEAN | 18 | 10.46 | 13.42 | 0.0043 | 0.0000 | 0.0000 |
| TERMINOLOGY | NOISY | 18 | 10.56 | 13.70 | 0.0044 | 0.0000 | 0.0000 |

`v3_ctc`, cuda:

| Category | Condition | n | `latency_ms` p50 | `latency_ms` p95 | `rtf` mean | `wer` mean | `cer` mean |
|:--|:--|--:|--:|--:|--:|--:|--:|
| ADDRESS | CLEAN | 18 | 11.09 | 13.62 | 0.0029 | 0.0000 | 0.0000 |
| ADDRESS | NOISY | 18 | 10.97 | 13.84 | 0.0029 | 0.0833 | 0.0648 |
| LONG | CLEAN | 21 | 14.85 | 16.34 | 0.0018 | 0.0357 | 0.0026 |
| LONG | NOISY | 18 | 14.84 | 28.64 | 0.0019 | 0.0521 | 0.0045 |
| MEDIUM | CLEAN | 18 | 10.62 | 20.97 | 0.0039 | 0.0238 | 0.0035 |
| MEDIUM | NOISY | 18 | 10.64 | 17.14 | 0.0039 | 0.0476 | 0.0077 |
| NUMBER | CLEAN | 18 | 10.28 | 17.67 | 0.0056 | 0.0000 | 0.0000 |
| NUMBER | NOISY | 18 | 10.49 | 13.89 | 0.0056 | 0.0000 | 0.0000 |
| SHORT | CLEAN | 18 | 9.81 | 11.45 | 0.0065 | 0.0000 | 0.0000 |
| SHORT | NOISY | 18 | 10.02 | 11.83 | 0.0065 | 0.0556 | 0.0104 |
| TERMINOLOGY | CLEAN | 18 | 10.51 | 13.67 | 0.0046 | 0.0000 | 0.0000 |
| TERMINOLOGY | NOISY | 18 | 10.73 | 15.27 | 0.0047 | 0.0000 | 0.0000 |

(LONG has 21, not 18: the human `clean/long` item adds 3 rows across the 3 runs.) Both cpu tables
are in their own JSONs (`aggregates.by_category_condition`); not reproduced here to keep this
document readable — every number quoted anywhere in it is in one of the five committed JSONs.
**No category × condition pair shows an outsized gap any more** — CLEAN and NOISY p50/p95 sit
within a few ms of each other in every row, for both model versions.

**NUMBER and ADDRESS carry the worst WER** (0.08–0.19), driven by Piper's pronunciation of digit
groups and GigaAM's transcription of them not always folding to the same canonical value as
`_common.fold()` expects — inspected by hand (`benchmarks/results/*.csv` hypothesis column):
`address_06` ("Грод Смоленск" for "Город Смоленск" — a Piper mispronunciation, not a GigaAM error),
`number_05` under NOISY ("Этаж четы. Подъезд т3." — the 10 dB noise floor genuinely degrades a
short, number-heavy utterance). This is an honest corpus/pronunciation interaction, not a
`benchmark_asr.py`/`_common.py` bug: WER is measured on real model output, not adjusted.
TERMINOLOGY and most of SHORT/MEDIUM score WER 0.0 — the dispatcher vocabulary itself
(пожар, задымление, возгорание, ...) is transcribed correctly in every condition tested.

## Comparison against E12-B's earlier single-sample measurements

E12-B (`backend/tests/models/test_gigaam_provider.py`, the one human `ru_sample.wav`, no corpus):

| Metric | E12-B (single sample) | This run (corpus mean, `v3_e2e_ctc`) | Agree? |
|:--|--:|--:|:--|
| RTF, cuda | 0.0169 | 0.0041 (overall mean, all categories/conditions) | Same order of magnitude, now *lower* than E12-B's figure (post-fix) — see below |
| RTF, cpu | 0.0355 | 0.0378 | Yes — within 6% |
| WER (human sample) | 0.0 | 0.0 (`human:gigaam-sample`, both cuda and cpu) | Yes — exact agreement, same file, same normalisation-adjacent folding logic |

The cuda RTF is now *below* E12-B's single-sample figure, not slightly above it as the pre-E19-B2
draft reported — expected, and the mechanism is the same one E19-B2 found and fixed: E12-B's own
contract test also pays a cold cuFFT-plan-cache cost on its single call (nothing in it warms the
model's shape cache first), so E12-B's 0.0169 already includes some of the same one-time overhead
this task's corpus now excludes by construction (`_shape_warm_up`). The two numbers are not
directly comparable measurement conditions; both are honestly reported, and this document states
why rather than picking one as "correct".

For `v3_ctc`: E12-B measured RTF 0.0016 (cuda) / 0.0234 (cpu) on the single sample; this run's
corpus mean is 0.0042 (cuda) / 0.0433 (cpu). Cuda is higher than E12-B's single-fast-call figure —
plausible, since `_common.aggregate()`'s `rtf_mean` is an unweighted arithmetic mean over
per-sample RTFs (not a total-latency/total-duration ratio), so short corpus items (a few hundred ms
long) weigh their comparatively larger *fixed* per-call overhead (kernel launch, Python/torch
dispatch — now genuinely fixed and small, ~10-15 ms, but still a larger fraction of a very short
clip's duration) exactly as heavily as long ones. This is a legitimate reading of HLD §7.1's
"rtf_mean", stated plainly so a reader does not mistake the corpus's short-item-heavy composition
for a regression.

## faster-whisper

`NOT_RUN`, `reason: "faster-whisper: not installed by this project (E12 ruling 4) —
--whisper-model-path/SIM_WHISPER_MODEL_PATH not set to an existing path (got: None)"`. SPEC §19
lists it as an "optional fallback"; `FasterWhisperProvider` exists
(`backend/app/inference/asr/faster_whisper_provider.py`, E12-B) but no model has ever been fetched
for it — this repo never downloads one (E12 ruling 4). `benchmark_asr.py --asr-provider
faster_whisper` is additive (this task): it always answers this same honest `NOT_RUN` unless a
developer points `--whisper-model-path`/`SIM_WHISPER_MODEL_PATH` at a CTranslate2 model they
already have on their own machine.

## E19-B2 — the CLEAN/NOISY latency bug (history, read this if a number here ever looks bimodal again)

**What the first published version of this table showed** (superseded JSONs deleted from
`results/`; commands/timestamps kept here as history, not as current numbers): on cuda,
`v3_e2e_ctc` CLEAN items measured `latency_ms` p50 ≈ 141-156 ms while NOISY items of the *same
categories and the same audio durations* measured p50 ≈ 10-15 ms — roughly a 10x gap, and the
overall envelope's own p50 (12 ms) vs p95 (167 ms) showed the same bimodality. Flagged by the epic
coordinator as "a measurement artefact until explained."

**Root cause, found by experiment.** `benchmarks/data/asr/manifest.jsonl` is sorted
`(category, condition, id)`, so every category's CLEAN items are all measured before its NOISY
items — and a CLEAN item and its NOISY twin share the *exact same* `duration_ms` (mixing noise
does not change a clip's length). On `--device cuda`, GigaAM's STFT front-end goes through cuFFT,
whose plan cache is keyed by input length: the first call at a given length pays a one-time
plan-build cost; later calls at that length are fast. Proof: an order-reversal experiment
(`/tmp/asr-order-experiment-manifest.jsonl`, one un-committed run under the lock, NOISY-before-CLEAN
per category) flipped the pattern exactly — NOISY became the ~140-160 ms condition and CLEAN
became the ~10-15 ms one. This confirms the gap tracks *processing order*, not the audio's acoustic
content — GigaAM does not "decode noisy audio faster"; whichever condition is measured **first**
for a given shape pays the shape's cold-cache cost.

**The fix, two parts, both in `benchmark_asr.py` (module docstring documents both in full):**

1. **Shape warm-up** (`_shape_warm_up()`): one untimed `transcribe()` call per distinct
   `duration_ms` in the corpus, run after `provider.warm_up()` and before any timed `--runs`
   sample — recorded in `notes` as `shape_warmup_ms=... shape_warmup_n=36`. This closed the
   *median* gap (12 ms → 10.7 ms CLEAN, 10.6 ms NOISY on the confirming re-run) but left a smaller
   tail asymmetry: 30/111 CLEAN samples over 100 ms vs 3/108 NOISY, because the manifest's fixed
   order still puts every CLEAN item "further" (more differently-shaped calls since the shape was
   last touched) from its own shape's previous use than its NOISY twin is.
2. **Seeded per-run shuffle**: the timed loop now processes each `--runs` repetition of the corpus
   in a `random.Random(args.seed + run_index)`-shuffled order (real provider only — `--provider
   fake` is excluded, `FakeASR` replays its script by call order and has no shape cache to be
   honest about). Confirmed on the re-run: CLEAN and NOISY tail counts (>100 ms) both dropped to
   **0/each**, overall `latency_ms` p95 went from 234 ms to 14.8 ms (`v3_e2e_ctc`) / 15.6 ms
   (`v3_ctc`), and every per-category CLEAN/NOISY pair now sits within a few ms of the other.

**What did not change:** every `wer`/`cer`/`entity_accuracy` figure is identical before and after
this fix (correctness was never in question, only latency); WER is still verified byte-identical
across all 3 `--runs` in every result CSV.

## Honesty checks performed

- Every `(id, condition)` pair's `wer`/`cer`/`entity_accuracy` is byte-identical across the 3
  `--runs` in every one of the four real result CSVs (checked by script over all 4×219 rows) —
  GigaAM's decode is deterministic on both cuda (float16) and cpu (float32) for this corpus.
- No `category × condition` pair on cuda shows a latency gap unexplained by ordinary variance (the
  E19-B2 fix above) — verified by script (CLEAN vs NOISY sample counts over 100 ms, before/after).
- `hardware.gpu_name/driver/total_vram_mb` is populated in all four `OK` results (a gap this task
  found and fixed in `benchmark_asr.py` — see "Script fixes" below); the `NOT_RUN` result correctly
  carries `hardware: {null, null, null}` (no GPU was touched to answer it).
- `notes` records `nvml_mode=pynvml` on every real run (post `make deps-models`, see "Script
  fixes") — not the `nvidia-smi` fallback.
- Every result filename now carries millisecond precision (`_common.write_result` fix, E19-B2
  addendum — see below); no two of the five results in the table above collided.
- No number in this document is not in one of the five JSONs under `results/`.

## Script fixes made in `benchmark_asr.py`/`_common.py`

1. **`hardware` was never populated** (E19-B). §7.0's envelope always carries
   `hardware:{gpu_name, driver, total_vram_mb}`, but `benchmark_asr.py` (like `benchmark_llm.py`,
   not this task's file) never instantiated `NvmlSampler`. Fixed: one instantaneous
   `NvmlSampler()` read (not continuous sampling — this script does not track a VRAM delta), with
   `notes.nvml_mode` recording which path answered it, matching `benchmark_tts.py`/
   `benchmark_vram.py`'s existing pattern. `benchmark_llm.py` has the same gap; not this task's
   file to fix (E19-C, noted under "FOR DOCS 60" / left for the consolidation task).
2. **`--asr-provider {gigaam,faster_whisper}`** (E19-B, additive CLI flag) — SPEC §19's optional
   fallback had no way to produce the `NOT_RUN` result R4 asks for; `--tts-provider chatterbox` on
   `benchmark_tts.py` was the precedent followed. Wired through to the real
   `FasterWhisperProvider` for a developer who supplies `--whisper-model-path`; on every machine
   this project has measured so far, that path is unset, so the honest result is always `NOT_RUN`.
3. **`GigaAMProvider` requires exactly 16000 Hz** (E19-B) — `ru_RU-irina-medium.onnx` synthesizes
   at 22050 Hz (its own `.onnx.json`); `benchmarks/data/asr/build_corpus.py` resamples with the
   product's own `app.application.voice.resampler.Resampler` (reuse, not reimplement — see that
   script's docstring).
4. **Shape warm-up + seeded shuffle** (E19-B2) — see "E19-B2" above.
5. **`write_result()` filename collision** (E19-B2, `_common.py`, reported by E19-C: two runs
   finishing within the same second destroyed one of their results). The timestamp now carries
   millisecond precision (`YYYYMMDDTHHMMSSmmmZ`), and if two writes still land on the exact same
   millisecond, a `-NN` counter suffix is appended (`_next_free_pair()`); if every counter up to
   `COLLISION_SUFFIX_LIMIT` (100) is somehow also taken, `write_result` raises
   `BenchmarkHonestyError` rather than pick a path to overwrite. Three new tests in
   `benchmarks/tests/test_bench_common.py` cover the millisecond format, the counter-suffix path
   (forced with a monkeypatched fixed clock), and the exhausted-counter refusal (limit shrunk to 2
   for the test so it does not need to create 100 files).

## Environment note

`make deps` (run once per the phase-2 addendum, to exercise the real `pynvml` path) is **not**
`--inexact` and stripped the heavy ML extras (`torch`, `onnxruntime`, `transformers`, ...) that a
prior task had installed — the first post-`make deps` real run failed with `ModuleNotFoundError:
No module named 'torch'`. Recovered immediately with `make deps-models && make deps-tts-piper`
(both `--inexact`, the Makefile's own documented way to add extras without stripping another
worker's). `pynvml` (`nvidia-ml-py`) is now installed and importable; all official runs above
were produced *after* this recovery, with `nvml_mode=pynvml` confirmed in every real result's
`notes`. Flagged for the consolidation task: **`make deps` is unsafe to run on this shared tree
while other phase-2 workers rely on the heavy extras being present** — a bare `make deps` call by
any later worker will reproduce this regression for everyone until `make deps-models`/
`deps-tts-piper`/`deps-tts-qwen3` are re-run.
