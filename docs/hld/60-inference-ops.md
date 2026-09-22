# HLD 60 — Inference operations: profiles, readiness, preflight, resilience, benchmarks

Elaborates `docs/SPEC.md` §26, §27 and §37–§41 under decisions **D8** (health endpoints), **D9**
(model profiles, VRAM margin, telemetry) and **D1** (compose services) of
`docs/hld/00-decisions.md`. Companion to `docs/hld/50-voice-pipeline.md`, which owns the ports and
the per-turn path; this file owns everything around them: what is loaded, on what hardware, how it
becomes ready, how it fails, and how it is measured.

Nothing here re-decides D1/D8/D9. Facts this document could not confirm against a primary source are
marked **UNVERIFIED** and must be measured before they are relied on; per SPEC §27 no benchmark
number is ever written down before it has been measured.

---

## 1. The dev machine constraint

The development machine is an **RTX 3060 Ti with 8 GB** of VRAM. Whether that card is free or
already shared with the owner's other work is not a constant — this document now ships **two**
DEV profiles for the two states (E18-A, OWNER DECISIONS 2026-09-21):

* **`DEV_3060TI`** assumes a **dedicated** card (nothing else resident) and budgets close to the
  full 8 GB (`vram_budget_mb: 7168`).
* **`DEV_3060TI_SHARED`** (ADDITIVE, not one of SPEC §26's three named profiles) assumes the card
  is already shared with the owner's other work — this machine's actual state as measured on
  2026-09-21 (`nvidia-smi`: ~4.6 GB held by an unrelated process, PID 1082982) — and budgets a much
  smaller, conservative `vram_budget_mb: 3000` with ASR and TTS moved to CPU so the whole profile
  fits without contending for the shared GPU at all.

Either way, the owner's other resident processes must never be killed, restarted or paged out by
anything this project does — `hardware.reserved_by_others_mb` (§2.1) is what each profile declares
it assumes is unavailable, and it is not stable: the owner's usage moves.

Consequences, stated as rules rather than as measurements:

1. **Neither DEV profile attempts full GPU residency by construction — it depends on what else is
   resident.** `DEV_3060TI` runs the LLM (Qwen3.5-2B Q4_K_M, GPU, full offload — OWNER DECISION
   2026-09-21, task reports e13-b3/e13-b4) and, via the separate `tts_qwen3` worker process,
   Qwen3-TTS (**TTS is GPU by default, not CPU** — OWNER DECISION, E14, `docs/hld/90-tbd-epics.md`
   row E14: "use qwen3tts as tts on gpu, I already checked it and it is very good"), with
   `PiperTTS` (CPU) as the configured fallback; ASR (GigaAM) also runs on GPU. `DEV_3060TI_SHARED`
   keeps the LLM on GPU but moves ASR and TTS (`PiperTTS`, no fallback) to CPU, trading model
   quality/latency for fitting a much smaller VRAM budget. VAD runs on **CPU** in both
   (`SileroVAD` via onnxruntime CPU EP) — nothing in this document moves it to GPU.
2. **The budget is declared, not inferred.** Each DEV profile declares
   `vram_budget_mb` as the amount this project is allowed to use, and the preflight (§5) refuses to
   proceed if *measured free* VRAM is below `vram_budget_mb + min_vram_margin_mb`. The project never
   frees memory it did not allocate.
3. **Nothing auto-scales.** There is no code path that lowers `--n-gpu-layers` at runtime to make a
   load succeed. A profile that does not fit is a refusal with a clear message, not a silent
   downgrade (SPEC §26 last line).
4. **`measured_peak_vram_mb` may be null on DEV only.** Config validation allows an unmeasured
   `DEV_3060TI` with a warning; it refuses an unmeasured `FINAL_3080TI_12GB` or
   `FINAL_3080TI_16GB` outright (D9).
5. **The dev latency target is the dev target.** SPEC §27's development-acceptable p50 < 1.5 s /
   p95 < 2.5 s is what `DEV_3060TI` is held to. The final-demo p50 < 1.2 s / p95 < 2.0 s applies to
   the `FINAL_*` profiles on the 3080 Ti.
6. No VRAM figure for any specific model, quantisation or offload split appears in this document.
   Those come from `benchmark_vram.py` (§7.5) and are written into the profile's
   `measured_peak_vram_mb` by a human after a run. **UNVERIFIED** until then, by construction.

---

## 2. Model profiles

Target files (BUILT — E18-A): `backend/app/config/profiles/DEV_3060TI.yaml`,
`backend/app/config/profiles/DEV_3060TI_SHARED.yaml` (ADDITIVE, §1),
`backend/app/config/profiles/FINAL_3080TI_12GB.yaml`,
`backend/app/config/profiles/FINAL_3080TI_16GB.yaml`.
Selected by the repo's existing env var **`SIM_MODEL_PROFILE`** (`Settings.model_profile`,
default `DEV_3060TI`) — this document previously said `MODEL_PROFILE`; corrected here (E18-A).
Loaded and validated by `backend/app/config/profile.py` into the Pydantic model `ModelProfile`
(`extra="forbid"` on every block, so an unknown key anywhere in a profile file is a load-time
refusal, never a silently ignored one).

### 2.0 Precedence: defaults < profile < an explicitly-set env var (R3, E18-A)

`app.config.profile.apply_profile(settings, profile) -> Settings` is the ONE function that
overlays a `ModelProfile`'s `llm`/`asr`/`tts`/`vad`/`voice_turn` blocks onto the matching
`SIM_*` `Settings` fields — used identically by the API (`app.api.container.build_container`) and
the voice-agent (`voice_agent.wiring.VoiceAgentDeps.build_for_startup`), so the two processes can
never overlay a profile two different ways. Precedence is decided **per field**, using
`pydantic-settings`' own `model_fields_set`: a `SIM_*` var that is present in the
environment/`.env` (or an explicit constructor kwarg) is in that set and is left untouched; a
field resting on its class default is not, and is free for the profile to overlay. This is what
keeps the gate's fake-provider selection (`SIM_*_PROVIDER=fake`, D13) working unchanged no matter
which profile `SIM_MODEL_PROFILE` names, and lets an operator override one knob without forking a
whole profile file. Not every profile key has a `Settings` counterpart — launch-flag fields
(`llm.n_gpu_layers`, `n_batch`, `n_ubatch`, `flash_attention`, `kv_cache_type`, `quantization`),
`hardware.*`, `warmup.*`, `latency_targets.*`, and the additive `tts.model_variant`/`health.*`
(below) are read straight off the loaded `ModelProfile` by whichever process needs them (the
llama-server entrypoint, the warm-up sequence, preflight), never through `Settings`.

`ProfileRefused` (§2.5) is fatal at start-up in both processes: it is left to propagate as an
uncaught exception before any port/model is built, which is what gives the process its non-zero
exit code. Never caught and downgraded to a warning; no env var disables it.

### 2.1 Key reference

Every key is required unless marked optional. Types are the Pydantic types.

| Key | Type | Meaning |
|:--|:--|:--|
| `profile_name` | str | must equal the file stem |
| `description` | str | free text |
| `hardware.gpu_name_contains` | str | substring the preflight requires in the detected GPU name |
| `hardware.gpu_total_vram_mb` | int | nominal card size, for reporting |
| `hardware.reserved_by_others_mb` | int | VRAM assumed occupied by unrelated processes |
| `vram_budget_mb` | int | what this project may use |
| `min_vram_margin_mb` | int | required margin between `measured_peak_vram_mb` and `vram_budget_mb` |
| `measured_peak_vram_mb` | int \| null | from `benchmark_vram.py`; null allowed only for DEV |
| `measured_at` | date \| null | when `measured_peak_vram_mb` was produced |
| `llm.provider` | str | `llama_cpp` |
| `llm.model_name` | str | reported in telemetry and `InferenceMetric.model_version` |
| `llm.model_path` | str | GGUF path inside the llama-server container |
| `llm.quantization` | str | e.g. `Q4_K_M` |
| `llm.base_url` | str | must be loopback or compose-internal (SPEC §41) |
| `llm.n_ctx` | int | 4096 (SPEC §22/§26) |
| `llm.n_gpu_layers` | int | `-1` = all; a positive integer = partial offload |
| `llm.n_batch` | int | prompt batch size |
| `llm.n_ubatch` | int | physical batch size |
| `llm.parallel_slots` | int | `--parallel`; total KV budget is `n_ctx`, split across slots |
| `llm.flash_attention` | str | `on` \| `off` \| `auto` |
| `llm.kv_cache_type` | str | e.g. `f16`, `q8_0` |
| `llm.max_response_tokens` | int | 80 (SPEC §22, E13-B4 measured — see `Settings.llm_generator_max_tokens`) |
| `llm.interpreter_max_tokens` | int | 138 (E13-B3 measured p99 + 25%, not the illustrative 200 an earlier revision of this table used) |
| `llm.request_timeout_ms` | int | per-call timeout |
| `llm.thinking_enabled` | bool | must be `false` (SPEC §22); validation rejects `true` |
| `asr.provider` | str | `gigaam` \| `faster_whisper` \| `fake` |
| `asr.model_version` | str | `v3_e2e_ctc` \| `v3_ctc` \| whisper size |
| `asr.model_path` | str | local model directory |
| `asr.device` | str | `cuda` \| `cpu` |
| `asr.compute_type` | str | e.g. `float16`, `int8` |
| `asr.sample_rate` | int | 16000 |
| `tts.provider` | str | `piper` \| `qwen3_tts` \| `chatterbox` \| `fake` |
| `tts.model_path` | str | model / voice file |
| `tts.voice_id` | str | voice selected for the default caller persona |
| `tts.device` | str | `cuda` \| `cpu` |
| `tts.output_sample_rate` | int | provider native rate |
| `tts.max_chunk_ms` | int | 20 (D9, E14 close-out: 40 -> 20 so §6.2's barge-in budget lands under SPEC §18's 250 ms) |
| `tts.fallback_provider` | str | provider used when the primary fails (SPEC §39) |
| `tts.model_variant` | str \| null, optional | ADDITIVE (E18-A, R2): `"0.6B"` \| `"1.7B"` \| `null`; maps to `SIM_TTS_QWEN3_MODEL`, read directly by the separate `tts_qwen3` worker process — `apply_profile` does not overlay it (no `Settings` counterpart) |
| `vad.provider` | str | `silero` \| `energy` |
| `vad.model_path` | str | onnx path (silero) |
| `vad.device` | str | `cpu` |
| `voice_turn.*` | — | the full `VoiceTurnConfig` of `50-voice-pipeline.md` §4.1, overlaid onto the matching `SIM_VOICE_*` fields by `apply_profile` (§2.0) |
| `voice_turn.reconnect_grace_s` | int, optional (default 30) | ADDITIVE (E18-A, R6): §6 row 5 / SPEC §39 item 5's LiveKit-reconnect timeout |
| `warmup.enabled` | bool | true in every real profile |
| `warmup.asr_sample_path` | str | short WAV used for the dummy ASR call |
| `warmup.llm_prompt` | str | tiny prompt for the dummy generation |
| `warmup.tts_text` | str | tiny text for the dummy synthesis |
| `warmup.timeout_ms` | int | per-service warm-up timeout |
| `latency_targets.p50_ms` | int | SPEC §27 target for this profile |
| `latency_targets.p95_ms` | int | SPEC §27 target for this profile |
| `health.failure_threshold` | int, optional (default 3) | ADDITIVE (E18-A, R1): §4.1's READY -> NOT_READY threshold; read by `workers/voice_agent/voice_agent/health.py` (E18-C) |
| `health.rewarm_interval_s` | int, optional (default 30) | ADDITIVE (E18-A, R1): §4.1's periodic re-warm interval; same reader as above |

### 2.2 `DEV_3060TI.yaml` (BUILT — E18-A; a dedicated card)

OWNER DECISIONS 2026-09-21 (task reports e13-b3/e13-b4, e14-d) replaced the earlier partial-offload
Qwen3-4B illustration below with the measured Qwen3.5-2B choice, and the stale, never-measured
`vram_budget_mb: 2800`/`n_gpu_layers: 20` this section used to show (SUPERSEDED, E14-B) is removed
— see §2.0's precedence paragraph and §10 open item 2 for the history. Full file:

```yaml
profile_name: DEV_3060TI
description: >
  Development profile for a DEDICATED RTX 3060 Ti 8 GB (nothing else resident on the card).
  LLM: Qwen3.5-2B Q4_K_M on GPU, one llama-server serving both the interpreter (slot 0) and the
  generator (slot 1) via --parallel 2 (OWNER DECISION 2026-09-21, task reports e13-b3/e13-b4).
  ASR: GigaAM v3_e2e_ctc on GPU. TTS: Qwen3-TTS on GPU (OWNER DECISION, E14), PiperTTS (CPU) as
  the configured fallback. For a card another process already occupies — this machine's actual
  state today, ~4.6 GB held by the owner — use DEV_3060TI_SHARED instead (§2.2a).

hardware:
  gpu_name_contains: "3060 Ti"
  gpu_total_vram_mb: 8192
  reserved_by_others_mb: 512      # dedicated-card assumption; DEV_3060TI_SHARED is the ~4.6 GB one

vram_budget_mb: 7168
min_vram_margin_mb: 512
# UNMEASURED as a COMBINED peak — DEV-only warning branch of validate_vram_margin (§2.5), never
# the FINAL_* refusal branch. LLM (1558 MB, task report e13-b4), GigaAM ASR (~1336 MiB, task
# report e14-d) and Qwen3-TTS 0.6B (~2746 MiB, task report e14-d) were each measured SEPARATELY
# and sum to ~5640 MiB, but nobody has run all three loaded simultaneously — that assumption is
# not written here as measured_peak_vram_mb (SPEC §27). TODO(E19): measure the real combined peak.
measured_peak_vram_mb: null
measured_at: null

llm:
  provider: llama_cpp
  model_name: Qwen3.5-2B          # ran GPU_FULL(999) in both measurements below, hence n_gpu_layers: -1
  model_path: /models/llm/Qwen3.5-2B-Q4_K_M.gguf
  quantization: Q4_K_M
  base_url: http://llama-server:8080/v1
  n_ctx: 4096
  n_gpu_layers: -1
  n_batch: 512
  n_ubatch: 256
  parallel_slots: 2               # one interpreter call and one generation call in flight
  flash_attention: "on"
  kv_cache_type: q8_0
  max_response_tokens: 80         # E13-B4 measured (Settings.llm_generator_max_tokens)
  interpreter_max_tokens: 138     # E13-B3 measured p99 + 25% (Settings.llm_interpreter_max_tokens)
  request_timeout_ms: 3000
  thinking_enabled: false
  # SPEC §26's "local Qwen3-4B quantized" stays a SUPPORTED choice (commented alternative,
  # measured interpret-only p50 1174 ms / p95 3718 ms, task report e13-b3; its generator call
  # OOM'd under --parallel 2, task report e13-b4, so it is not this profile's default):
  #   model_name: Qwen3-4B, model_path: /models/llm/Qwen3-4B-Q4_K_M.gguf, n_gpu_layers: 32

asr:
  provider: gigaam
  model_version: v3_e2e_ctc
  model_path: /models/asr/gigaam-v3-e2e-ctc
  device: cuda
  compute_type: float16
  sample_rate: 16000

tts:
  provider: qwen3_tts              # OWNER DECISION (E14): GPU default for every profile, DEV incl.
  model_path: /models/tts/qwen3-tts           # BASE dir, SIM_TTS_QWEN3_MODEL_DIR; the tts_qwen3
                                               # worker appends the variant's own subdirectory (E14-D)
  voice_id: Serena                 # vendor CustomVoice speaker (recon §1.1) — not a free voice id
  device: cuda
  output_sample_rate: 24000
  max_chunk_ms: 20
  fallback_provider: piper         # PiperTTS, CPU — the configured fallback (D9)
  fallback_model_path: /models/tts/piper/ru_RU-irina-medium.onnx
  fallback_voice_id: ru_RU-irina-medium
  fallback_output_sample_rate: 22050
  # ADDITIVE (E18-A, §2.1), maps to SIM_TTS_QWEN3_MODEL (read directly by the tts_qwen3 worker
  # process): "0.6B" MEASURED peak ~2746 MiB, RTF mean 0.831 (task report e14-d); "1.7B" is the
  # owner's evaluated checkpoint but is still NOT_RUN on this machine (§10 open item 6). null =
  # the worker's own default (1.7B) until a combined-load measurement (E19) sets one explicitly.
  model_variant: null

vad:
  provider: silero
  model_path: /models/vad/silero_vad.onnx
  device: cpu

voice_turn:
  speech_start_threshold: 0.55
  speech_end_threshold: 0.35
  speech_start_min_ms: 96
  endpoint_silence_ms: 300
  pre_roll_ms: 300
  barge_in_min_speech_ms: 120
  max_turn_ms: 30000
  min_turn_ms: 200
  vad_frame_ms: 32
  outbound_queue_ms: 200
  tts_chunk_ms: 20
  partial_asr_enabled: true
  partial_interval_ms: 500
  reconnect_grace_s: 30            # ADDITIVE (E18-A, R6): §6 row 5 / SPEC §39 item 5 default

warmup:
  enabled: true
  asr_sample_path: /models/warmup/warmup_ru.wav
  llm_prompt: "Скажи одно слово."
  tts_text: "Проверка."
  timeout_ms: 60000

latency_targets:
  p50_ms: 1500
  p95_ms: 2500

health:                            # ADDITIVE (E18-A, R1) — both are the schema defaults
  failure_threshold: 3
  rewarm_interval_s: 30
```

### 2.2a `DEV_3060TI_SHARED.yaml` (BUILT — E18-A; ADDITIVE, not one of SPEC §26's three)

For a card another process already occupies — this machine's actual, measured state (§1). LLM
stays on GPU (same measured Qwen3.5-2B choice as `DEV_3060TI`); ASR and TTS move to CPU so the
whole profile fits the much smaller remaining budget without a fallback:

```yaml
profile_name: DEV_3060TI_SHARED
hardware:
  reserved_by_others_mb: 4700      # OWNER DECISION 2026-09-21: this machine's measured owner-
                                    # process residency (nvidia-smi 4646 MiB used)
vram_budget_mb: 3000
min_vram_margin_mb: 512
measured_peak_vram_mb: 1558        # MEASURED (task report e13-b4): the LLM is the ONLY GPU
measured_at: 2026-09-21            # resident on this profile, so this is a true combined peak

llm: { model_name: Qwen3.5-2B, n_gpu_layers: -1, parallel_slots: 2 }   # same as DEV_3060TI
asr: { provider: gigaam, device: cpu, compute_type: float32 }          # MEASURED RTF 0.036 (CPU)
tts: { provider: piper, device: cpu, fallback_provider: none }         # MEASURED RTF 0.023-0.052
```

(Full file: `backend/app/config/profiles/DEV_3060TI_SHARED.yaml`; the excerpt above shows only what
differs in kind from `DEV_3060TI`, not every key — every key `ModelProfile`/`extra="forbid"`
requires is present in the real file.) Margin: `3000 - 1558 = 1442 >= 512` — passes
`validate_vram_margin` outright, no DEV-only warning needed, since this profile's peak actually is
measured.

### 2.3 `FINAL_3080TI_12GB.yaml` (BUILT — E18-A; refused today, §2.5: no measurement exists yet)

```yaml
profile_name: FINAL_3080TI_12GB
description: >
  Demo profile for an RTX 3080 Ti 12 GB. Qwen3-8B Q4_K_M only if the VRAM benchmark passes with the
  configured margin; otherwise config validation refuses the profile and DEV_3060TI is used.

hardware:
  gpu_name_contains: "3080 Ti"
  gpu_total_vram_mb: 12288
  reserved_by_others_mb: 0

vram_budget_mb: 11000
min_vram_margin_mb: 1024
measured_peak_vram_mb: null      # must be measured; null is REFUSED for FINAL_* profiles
measured_at: null

llm:
  provider: llama_cpp
  model_name: Qwen3-8B
  model_path: /models/llm/Qwen3-8B-Q4_K_M.gguf
  quantization: Q4_K_M
  base_url: http://llama-server:8080/v1
  n_ctx: 4096
  n_gpu_layers: -1
  n_batch: 1024
  n_ubatch: 512
  parallel_slots: 2
  flash_attention: "on"
  kv_cache_type: f16
  max_response_tokens: 80          # E13-B4 measured (Settings.llm_generator_max_tokens)
  interpreter_max_tokens: 138      # E13-B3 measured p99 + 25%, reused rather than an illustrative
                                    # 200 not itself measured on this model (Settings docstring)
  request_timeout_ms: 3000
  thinking_enabled: false

asr:
  provider: gigaam
  model_version: v3_e2e_ctc
  model_path: /models/asr/gigaam-v3-e2e-ctc
  device: cuda
  compute_type: float16
  sample_rate: 16000

tts:
  provider: qwen3_tts
  # FIXED (E14-B): was "/models/tts/qwen3-tts-0.6b" — a size mismatch against the owner's actually
  # evaluated/verified checkpoint (recon §1.1, this task's report): 1.7B CustomVoice, not 0.6B.
  # E14-D: this path is now the BASE dir (SIM_TTS_QWEN3_MODEL_DIR) either way — the worker appends
  # the configured variant's own subdirectory (SIM_TTS_QWEN3_MODEL, default 1.7B, unchanged here).
  model_path: /models/tts/qwen3-tts
  voice_id: Serena                # vendor CustomVoice speaker (recon §1.1) — not a free voice id
  device: cuda
  output_sample_rate: 24000
  max_chunk_ms: 20
  fallback_provider: piper
  model_variant: null              # ADDITIVE (E18-A) — UNVERIFIED on a 3080 Ti, not this task's to invent

vad:
  provider: silero
  model_path: /models/vad/silero_vad.onnx
  device: cpu

voice_turn:
  speech_start_threshold: 0.55
  speech_end_threshold: 0.35
  speech_start_min_ms: 96
  endpoint_silence_ms: 300
  pre_roll_ms: 300
  barge_in_min_speech_ms: 120
  max_turn_ms: 30000
  min_turn_ms: 200
  vad_frame_ms: 32
  outbound_queue_ms: 200
  tts_chunk_ms: 20
  partial_asr_enabled: true
  partial_interval_ms: 500
  reconnect_grace_s: 30            # ADDITIVE (E18-A, R6) default

warmup:
  enabled: true
  asr_sample_path: /models/warmup/warmup_ru.wav
  llm_prompt: "Скажи одно слово."
  tts_text: "Проверка."
  timeout_ms: 60000

latency_targets:
  p50_ms: 1200
  p95_ms: 2000

health:                            # ADDITIVE (E18-A, R1) — both are the schema defaults
  failure_threshold: 3
  rewarm_interval_s: 30
```

### 2.4 `FINAL_3080TI_16GB.yaml`

Identical to `FINAL_3080TI_12GB.yaml` except:

```yaml
profile_name: FINAL_3080TI_16GB
hardware:
  gpu_total_vram_mb: 16384
vram_budget_mb: 15000
min_vram_margin_mb: 1536
llm:
  kv_cache_type: f16
  parallel_slots: 4
tts:
  provider: chatterbox           # or qwen3_tts; whichever the TTS benchmark prefers
  model_path: /models/tts/chatterbox-multilingual
  voice_id: ru_female_calm       # UNVERIFIED
  device: cuda
  output_sample_rate: 24000
  fallback_provider: piper
```

`n_ctx` stays 4096 initially in both FINAL profiles (SPEC §26).

### 2.5 The VRAM-margin refusal rule (D9)

`backend/app/config/profile.py::validate_vram_margin(profile)` runs at process start, in the backend
and in the voice-agent, before any model is loaded:

```
margin_mb = vram_budget_mb - measured_peak_vram_mb

if measured_peak_vram_mb is None:
    if profile_name.startswith("FINAL_"):
        raise ProfileRefused(
            "FINAL profile <name> has no measured_peak_vram_mb; "
            "run benchmarks/benchmark_vram.py and record the result")
    else:
        log.warning("DEV profile <name> is unmeasured; VRAM margin cannot be checked")
elif margin_mb < min_vram_margin_mb:
    raise ProfileRefused(
        "profile <name>: measured peak <X> MB leaves margin <margin> MB, "
        "below min_vram_margin_mb <Y> MB — SPEC §26 forbids it")
```

`ProfileRefused` is fatal at start-up: the process exits non-zero. It is never downgraded to a
warning, and there is no env var that disables it. This is the mechanism behind SPEC §26's "never
choose a profile whose measured peak VRAM leaves essentially zero safety margin".

The preflight (§5) additionally compares `vram_budget_mb + min_vram_margin_mb` against the **free**
VRAM reported by the driver at that moment, which is what catches the dev machine's moving 5 GB.

---

## 3. `InferenceMetric` — SPEC §27 field to column mapping

Table `inference_metrics` (SPEC §30). The dataclass is defined in `50-voice-pipeline.md` §2.6; this
is the persistence contract. ORM class `backend/app/db/models/inference_metric.py::InferenceMetricRow`.

| SPEC §27 field | Column | Type | Null | Note |
|:--|:--|:--|:--|:--|
| — | `id` | `UUID` PK | no | uuid4 |
| — | `session_id` | `UUID` FK → `simulation_sessions.id` | no | indexed |
| — | `turn_id` | `UUID` | yes | null for warm-up and benchmark calls |
| request id | `request_id` | `TEXT` | no | unique per call; `{turn_id}:{stage}:{attempt}` |
| — | `stage` | `TEXT` | no | `ASR` \| `LLM_INTERPRET` \| `LLM_GENERATE` \| `TTS` |
| model/provider | `provider` | `TEXT` | no | `gigaam`, `llama_cpp`, `piper`, … |
| model version | `model_version` | `TEXT` | no | `v3_e2e_ctc`, `Qwen3-8B-Q4_K_M`, … |
| input tokens | `input_tokens` | `INTEGER` | yes | LLM stages |
| input duration | `input_audio_ms` | `INTEGER` | yes | ASR stage |
| output tokens | `output_tokens` | `INTEGER` | yes | LLM stages |
| output audio duration | `output_audio_ms` | `INTEGER` | yes | TTS stage |
| start timestamp | `started_at` | `TIMESTAMPTZ` | no | |
| first-output timestamp | `first_output_at` | `TIMESTAMPTZ` | yes | first token / first audio chunk |
| finish timestamp | `finished_at` | `TIMESTAMPTZ` | yes | null if cancelled before completion |
| TTFT | `ttft_ms` | `INTEGER` | yes | `first_output_at - started_at` |
| total latency | `total_latency_ms` | `INTEGER` | yes | `finished_at - started_at` |
| tokens per second | `tokens_per_second` | `DOUBLE PRECISION` | yes | `output_tokens / (finished-first)` |
| realtime factor | `realtime_factor` | `DOUBLE PRECISION` | yes | ASR: `total_latency_ms / input_audio_ms`; TTS: `total_latency_ms / output_audio_ms` |
| GPU memory measurement | `gpu_memory_used_mb` | `INTEGER` | yes | sampled at `finished_at` when NVML is available |
| fallback count | `fallback_count` | `INTEGER` | no | default 0 |
| retry count | `retry_count` | `INTEGER` | no | default 0 |
| — | `status` | `TEXT` | no | `OK` \| `TIMEOUT` \| `ERROR` \| `CANCELLED` |
| — | `error_kind` | `TEXT` | yes | exception class name, never a stack trace |
| — | `created_at` | `TIMESTAMPTZ` | no | |

Indexes: `(session_id, started_at)`, `(stage, started_at)`, `UNIQUE(request_id)`.

The SPEC §27 **critical product metric** is not a row here: `speech_end_to_first_audio_ms` is stored
on the turn record (column `dialogue_turns.speech_end_to_first_audio_ms`, `INTEGER`, null when the
turn produced no audio) and written through `MetricsRecorder.record_turn_latency`. Keeping it off
`inference_metrics` is deliberate — it spans four stages and belongs to the turn, and the report's
latency panel (SPEC §29) reads it per turn.

Writes are asynchronous and **never** block the turn: `MetricsRecorder` implementations push onto a
bounded queue (`metrics_queue_depth`, default 1000) drained by a background task; on overflow the
oldest row is dropped and a counter is logged. Losing a metric must never delay audio, and it must
never fail a turn.

---

## 4. Warm-up and readiness (SPEC §37)

### 4.1 State model

```
NOT_READY  process is up, the service has not been warmed (or a warm-up failed and may be retried)
WARMING    warm-up is running
READY      warm-up completed successfully within warmup.timeout_ms
FATAL      unrecoverable: GPU OOM, model file missing, CUDA unavailable. Never auto-retried.
```

Transitions:

| From | Event | To |
|:--|:--|:--|
| NOT_READY | warm-up started | WARMING |
| WARMING | warm-up succeeded | READY |
| WARMING | warm-up failed, recoverable (timeout, connection refused) | NOT_READY |
| WARMING | warm-up failed, unrecoverable (OOM, missing model, no CUDA) | FATAL |
| READY | N consecutive runtime failures (`health.failure_threshold`, default 3) | NOT_READY |
| READY | GPU OOM at runtime | FATAL |
| NOT_READY | periodic re-warm (`health.rewarm_interval_s`, default 30) | WARMING |
| FATAL | — | nothing; only a process restart leaves FATAL |

One state per service: `llm`, `asr`, `tts`, `vad`, plus the infrastructure checks `postgres`,
`redis`, `livekit` which the backend owns (D8).

**Where it lives (E18-C).** The table above is `voice_agent.health.ServiceHealth`, one instance per
service, collected in `InferenceHealth`. It is a **pure** state machine: no Redis, no clock, no I/O
at all. Every method returns a `HealthTransition` (`{service, from_state, to_state, detail}`) or
`None` when the event changed nothing, and the caller — `voice_agent.main.VoiceAgent` — is what
turns a transition into the three Redis writes of §4.3. That split is what makes every row of the
table a unit test with no process (`workers/voice_agent/tests/test_health_state_machine.py`).

`health.failure_threshold` and `health.rewarm_interval_s` come from the active profile's `health`
block (`app.config.profile.HealthProfile`, E18-A); they have no `SIM_*` counterpart, so
`apply_profile` does not touch `Settings` for them and the state machine reads the profile directly.

The **periodic re-warm** (row 7) rides the heartbeat rather than owning a timer of its own: the
heartbeat is already this process's one periodic task, and `ServiceHealth.due_for_rewarm(now_s)` is
what decides whether `rewarm_interval_s` has elapsed. A FATAL service is never due, which is row 8
expressed as a branch rather than as a flag somebody has to remember to check. A service that has
never been warmed is due immediately, so a first attempt never waits out the interval.

Cancellation is **not** a failure: `asyncio.CancelledError` is how a barge-in stops an in-flight
stage (§6.1 of `50-voice-pipeline.md`), and it never counts toward `failure_threshold`.

### 4.2 Warm-up sequence

Run by the voice-agent at start-up, sequentially (not concurrently — concurrent loads on a
memory-tight GPU is exactly how the dev machine OOMs):

1. **VAD** — load the onnx session, `reset()`, `process()` one frame of
   `VADProvider.frame_samples` zeros. Cheapest, first, so a broken onnxruntime is found immediately.
2. **ASR** — load the model, `transcribe(warmup.asr_sample_path)`. A short real Russian WAV, not
   silence: silence can take a degenerate path through a CTC decoder and prove nothing.
3. **LLM** — `complete([system, user=warmup.llm_prompt], max_tokens=8, response_format=None)` against
   llama-server, after polling `GET {base_url}/models` until it answers or `warmup.timeout_ms`
   elapses. A second call is made **with** a trivial `json_schema` response format so that the
   grammar path is warm too — the interpreter's first real call must not be the first grammar
   compile.
4. **TTS** — `stream(warmup.tts_text, default voice)` drained to completion. For the out-of-process
   Qwen3-TTS worker this means `POST /warm_up` on `workers/tts_qwen3`, which **loads the model and
   then runs one real generation of a short Russian text, discarding the audio** (E18-C). Loading
   the weights leaves the CUDA graphs, the kernel autotuning and the tokenizer's first pass cold:
   E14-D measured **13.1 s** for the first synthesis after a load-only warm-up, and that cost
   belongs to the warm-up rather than to the first caller line. The response reports
   `output_audio_ms` and `generate_ms` so a caller can tell a real warm-up from a load-only one.

Each step records an `InferenceMetric` with `turn_id = NULL` and `request_id = "warmup:{stage}"`, so
warm-up cost is visible in the same table as everything else. Each step publishes its state
transition as it happens, so the UI shows progress rather than a single long NOT_READY.

A warm-up failure is classified, not merely logged (§4.1 rows 3 and 4): `InferenceOutOfMemoryError`
and `ModelNotAvailableError` are **unrecoverable** and go straight to FATAL, because no amount of
re-warming every 30 seconds fixes a missing file or a full card. Everything else — a timeout, a
connection refused, a worker that is not up yet — is recoverable and becomes NOT_READY with a
re-warm clock running.

**Model identity is read, never assumed.** `Qwen3TTS.model_version` reports what the worker's
`/health` says it actually serves (`SIM_TTS_QWEN3_MODEL` picks 1.7B or 0.6B **in the worker's
process**), cached at warm-up. Before the first `/health`, and if it cannot be reached, the adapter's
pinned constants remain the answer — the port's `model_version` is a synchronous property and an
adapter must not do I/O inside one. Writing a configured guess into `CALLER_TTS_STARTED.tts_model`
and `inference_metrics.model_version` is what SPEC §27 does not allow.

**The warmed providers are reachable for §5's checks 5 and 6.** After the warm-up sequence
completes, the voice-agent binds a tiny loopback HTTP server —
`voice_agent.preflight_http.PreflightHttpServer`, `SIM_VOICE_AGENT_HTTP_PORT` (default **8113**),
stdlib `asyncio` only — serving exactly two routes:

| route | does | answers |
|:--|:--|:--|
| `GET /preflight/asr` | transcribes the warm-up sample with the **already loaded** provider | `{"text", "latency_ms", "provider", "model_version"}` |
| `GET /preflight/tts` | synthesises `warmup.tts_text` | `{"output_audio_ms", "latency_ms", "provider", "model_version"}` |

Neither route loads anything: a component that has not been warmed answers **503** with an RFC
7807-shaped problem document, which is the truthful "ASR does not respond" rather than a lazy load
that would make the preflight the slowest thing in the stack and could OOM the very card it exists
to protect. It binds **after** the warm-up for the same reason — a socket that answered 503 for the
whole warm-up is noise, not information. A non-loopback `bind_host` raises at construction
(`NonLoopbackBindError`), the compose service publishes no host port (R10), and the container's
`healthcheck:` asks the same port through `python -m voice_agent.cli health`, which checks that the
endpoint is listening and exits 0/1 without spending GPU time on every tick.

### 4.3 How the voice-agent publishes readiness

Redis, written by the voice-agent, read by the backend (D8's `/api/v1/health/ready` aggregates them):

- Key `voice:health:{service}` for `service ∈ {llm, asr, tts, vad}`, a JSON string:

  ```json
  {
    "state": "READY",
    "profile": "DEV_3060TI",
    "provider": "gigaam",
    "model_version": "v3_e2e_ctc",
    "updated_at": "2026-09-19T10:00:00Z",
    "detail": null,
    "warmup_ms": 4210
  }
  ```

- Written with `SET voice:health:{service} <json> EX 15` and refreshed by a heartbeat every
  5 seconds. A **missing key is NOT_READY**, not READY: the backend treats absence as
  `{"state": "NOT_READY", "detail": "no heartbeat from voice-agent"}`. This is what makes a crashed
  voice-agent visible without any extra liveness protocol.
- Every transition is also published on the pub/sub channel `voice:health` as
  `{"service": "...", "from": "...", "to": "...", "detail": "...", "at": "..."}`; the backend turns
  each message into an `INFERENCE_HEALTH_CHANGED` session event on every ACTIVE session and pushes it
  over the session WebSocket so the instructor sees it live.
- The FATAL state is additionally mirrored to `voice:health:fatal` (no expiry) so that a restart loop
  cannot make a fatal condition look transient; the key is deleted only by an explicit
  `POST /api/v1/admin/inference/clear-fatal` (**ADMIN**, manager ruling R4 of E18 — `openapi.yaml`'s
  summary line still reads "INSTRUCTOR / ADMIN"; its machine-readable part defines only `401`/`403`,
  so the narrower gate satisfies the contract) or by a clean warm-up after a manual restart.
  Its value is a JSON object carrying at least `{"service": "...", "detail": "..."}` — the service
  the fatal condition belongs to, so the other three keep reporting their own heartbeat.

**The backend side (E18-B), `backend/app/infrastructure/health/voice_health.py`:**

| reader | what it is | rule |
|--|--|--|
| `VoiceHealthProbe(client, service)` | the `HealthProbe` for one of `llm`/`asr`/`tts`/`vad` | `voice:health:fatal` covering this service ⇒ `FATAL`; else the frame's `state`; a **missing key, an unparsable value or an unknown `state` ⇒ `NOT_READY`**, never `READY`; an unreachable Redis ⇒ `NOT_READY` with the reason (a probe never raises) |
| `RedisInferenceReadiness` | the `InferenceReadiness` port `startSession` consults (D8) | `True` only when all four services read `READY` |
| `RedisInferenceFatalLatch` | what `clearInferenceFatal` calls | deletes `voice:health:fatal` and publishes `{"service", "from": "FATAL", "to": "NOT_READY", "detail", "at"}` on `voice:health`, so an admin's click reaches the session log through the same path a voice-agent transition does (`openapi.yaml`'s `x-emits`). Clearing never makes anything `READY`: the next heartbeat decides that |
| `VoiceHealthSubscriber` + `app.application.inference_health.AppendInferenceHealthChanged` | the `voice:health` tail, started and stopped by the API lifespan next to the `SimulationRunner` and gated on the same `SIM_RUNNER_ENABLED` | one `INFERENCE_HEALTH_CHANGED` (`SYSTEM` actor, §10.13's payload) per **ACTIVE** session, in its own Unit of Work; no ACTIVE session ⇒ no write; a malformed message is logged and dropped; `simulation_sessions.state` is never written (SPEC §39) |

A `voice:health:fatal` value the backend cannot parse, or one that names no `service`, latches
**every** service: a latch that cannot be read is exactly the condition that must not be hidden.
`HealthReadyResponse.model_profile` is the active profile's name — `load_profile` refuses a file
whose `profile_name` differs from its filename, so it equals `SIM_MODEL_PROFILE` by construction.

`POST /api/v1/sessions/{id}/start` returns 503 `INFERENCE_NOT_READY` while any required service is
not READY and `REQUIRE_INFERENCE_READY=true` (default true; tests set it false explicitly) — D8.
The UI disables the start button from `/api/v1/health/ready`, satisfying SPEC §37's "the UI must not
allow a final demo session to begin while a required inference service reports not-ready".

### 4.4 GPU OOM → FATAL without touching session state (SPEC §39)

The rule: **an OOM changes health, never simulation state.** Concretely, in
`workers/voice_agent/voice_agent/health.py`:

1. Every model call is wrapped by `guard_inference(stage)` — as shipped (E18-C),
   `voice_agent.health.InferenceHealthGuard`, reached from the pipeline through the application
   port `app.application.ports.inference_guard.InferenceGuard`
   (`async def run(stage, call, *, fallback)`). The adapters already normalise the platform's many
   spellings of an allocation failure — `torch.cuda.OutOfMemoryError`, a `RuntimeError` whose
   message contains `out of memory`, and the llama-server / Qwen3-TTS HTTP responses that report
   one — into the single `app.inference.errors.InferenceOutOfMemoryError`, which is what the guard
   keys off.
2. On catch, the **health** half is the guard's: it transitions that service to **FATAL** and
   publishes it (§4.3). The **turn** half stays where it already was, in the stage: the
   `InferenceMetric` with `status = "ERROR"`, `error_kind = "OOM"`, the
   `MODEL_ERROR {session_id, turn_id, stage, error_kind: "OOM", recoverable: false}` append, and
   the stage's deterministic fallback — the interpreter's `UNINTELLIGIBLE`, the validator's
   template (`50-voice-pipeline.md` §5.1, §7.8), `TtsSpeechSink`'s configured fallback provider and
   then its silent-but-complete ending — so the turn finishes with a spoken caller line where it
   can. The guard therefore **re-raises** by default and the stage's existing ladder runs unchanged;
   its `fallback` argument exists for the one stage with no ladder of its own, VAD, whose
   deterministic answer is "this frame is not speech" (a failing VAD degrades to "nobody is
   speaking", never to a phantom turn).
3. It does **not** call any session use case, does not abort the session, does not roll back the
   incident, does not clear the card, and does not touch `simulation_sessions.state`. The session
   stays ACTIVE; the trainee can keep filling the card; every event already written stays written
   (SPEC §42 test 14).
4. `torch.cuda.empty_cache()` is called once after the transition to FATAL, and no model is reloaded.
   Reloading into a fragmented, contended 8 GB card is how one OOM becomes a loop. It is called
   **only if `torch` is importable**: the gate runs entirely on fake providers in a venv with no
   torch (D13), where this must be a no-op rather than an `ImportError`. A second OOM on an
   already-FATAL service publishes nothing and empties nothing — FATAL is terminal.
5. The instructor UI shows the FATAL banner; starting a **new** session is refused while FATAL holds.

**Which call sites are guarded, and how.** VAD at `TurnPipeline`, ASR at `AsrTurnResponder`, TTS at
`TtsSpeechSink` — each takes an `InferenceGuard` whose default is `NoOpInferenceGuard`, so a process
with no health registry (every existing unit test, the backend container) behaves exactly as it did
before. The **LLM** is the exception: its two call sites, `DialogueInterpreter` and
`CallerResponseGenerator`, live in `app.application.dialogue`, which knows nothing about health and
must keep knowing nothing (D2/D3). Both share one `LLMClient`, so the voice-agent wraps that one
object in `voice_agent.health.GuardedLLMClient` — both stages are behind the guard without a line of
dialogue code changing. A streaming call is guarded at its **first** delta, which is where
llama-server's allocation failure actually arrives.

`app.application` may not import `app.inference` (D2, enforced by `backend/tools/check_imports.py`),
yet the stages must still tell an allocation failure from an ordinary provider error to choose
`error_code`/`recoverable`. `app.application.ports.inference_guard.is_out_of_memory(exc)` is that
bridge: it recognises `InferenceOutOfMemoryError` by class name over the whole MRO, the same
boundary problem `app.application.ports.tts` solved by defining `TtsTimeoutError` in the port.
`MODEL_ERROR` carries **both** spellings — `error_code` (the §10.13 catalogued key) and `error_kind`
(this document's) — exactly as it already carries both `component` and `stage`.

The same guard converts a non-OOM CUDA error into `NOT_READY` (recoverable) with
`MODEL_ERROR {..., recoverable: true}`, which the failure-threshold rule of §4.1 then escalates if it
keeps happening.

---

## 5. Preflight (SPEC §38)

Command: `python -m app.cli preflight [--profile NAME] [--json] [--skip-audio-devices]`.
Target file: `backend/app/cli/preflight.py`. It loads the profile but **loads no ML model**: it
probes services and files, so it is fast and can run in CI against fakes.

| # | SPEC §38 check | How it is performed | PASS when |
|:--|:--|:--|:--|
| 1 | CUDA/GPU available | `pynvml.nvmlInit()`; fall back to `nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits` | the call succeeds and reports ≥ 1 device |
| 2 | expected GPU detected | device name contains `hardware.gpu_name_contains`; free VRAM read from the same source | name matches **and** `free_mb >= vram_budget_mb + min_vram_margin_mb` |
| 3 | required model files exist | `os.path.exists` + non-zero size for `llm.model_path`, `asr.model_path`, `tts.model_path`, `vad.model_path`, `warmup.asr_sample_path` | every path exists and is non-empty |
| 4 | LLM responds | `GET {llm.base_url}/models`, then one `complete(max_tokens=4)` with a 10 s timeout | HTTP 200 and non-empty text, and the reported model id contains `llm.model_name` |
| 5 | ASR responds | out-of-process: `GET` the voice-agent's `/preflight/asr`, which transcribes `warmup.asr_sample_path` | HTTP 200 and non-empty text |
| 6 | TTS responds | voice-agent `/preflight/tts`, synthesising `warmup.tts_text` | HTTP 200 and `output_audio_ms > 0` |
| 7 | PostgreSQL responds | `SELECT 1` on the configured DSN, plus `SELECT count(*) FROM alembic_version` | both succeed and exactly one migration head is present |
| 8 | Redis responds | `PING`, then `SET`/`GET`/`DEL` of `preflight:probe` | both succeed |
| 9 | LiveKit responds | `GET {LIVEKIT_URL}/` health path, plus a `livekit-api` `ListRooms` with the configured key/secret | HTTP 200 and the API call authenticates |
| 10 | scenario validation passes | runs the same loader the gate uses over `scenarios/examples/**/v*.yaml` | every file validates; count reported |
| 11 | audio devices accessible | only when `--skip-audio-devices` is absent and `AUDIO_DEVICE_CHECK=true`: enumerate input devices via `sounddevice.query_devices()` and open the configured device at 16 kHz mono for 100 ms | the device opens; otherwise the row is `SKIP` (never `FAIL` — a headless demo box with no configured microphone is not a preflight failure) |
| 12 | `llama_server_binary` (additive, R7, E18-D) | when `SIM_LLAMA_SERVER_BIN` is set: the file exists, is executable, and `--version` exits 0 | those three, in order; unset is `SKIP` — the Qwen3.5 GGUFs this profile uses need a newer llama.cpp than the one already on `~/.local/share/llama.cpp`, so this cannot assume a pinned binary is configured yet. Check 4's "model id contains `llm.model_name`" is the real proof the binary can load *this* GGUF, once the server is actually up |

Implemented (E18-D): `backend/app/cli/preflight.py`, unit-tested with a `PASS` and a `FAIL` per
check against fakes (`backend/tests/unit/cli/test_preflight.py`) — every check is a pure decision
over an injected probe callable, so none of the twelve ever touches a real GPU, model server,
database or LiveKit instance in the test run. The real, network-touching probes live in that same
module's `build_real_checks`. The row/field names below (`id`, `measured`, dotted check ids like
`gpu.available`) are this design sketch's own shorthand; the shipped CLI's actual shape is
`{number, name, status, detail}` per check (`name` matching this table's row, e.g.
`cuda_gpu_available`, `expected_gpu_detected`) — see `render_table`/`render_json` in that module for
the literal output.

Output format (human, one line per check, fixed 4-character status column):

```
112-maxxing preflight — profile DEV_3060TI — 2026-09-19T10:00:00Z

PASS  gpu.available          NVIDIA GeForce RTX 3060 Ti
PASS  gpu.expected           matches "3060 Ti"; free 3072 MB >= budget 2800 + margin 512? no
FAIL  gpu.vram_margin        free 3072 MB < required 3312 MB
PASS  models.files           5/5 present
PASS  llm.responds           Qwen3-4B, 412 ms
SKIP  audio.devices          --skip-audio-devices
...

11 checks: 9 PASS, 1 FAIL, 1 SKIP
FAIL: gpu.vram_margin
```

`--json` emits, to stdout:

```json
{
  "schema_version": 1,
  "profile": "DEV_3060TI",
  "started_at": "2026-09-19T10:00:00Z",
  "finished_at": "2026-09-19T10:00:07Z",
  "checks": [
    {"id": "gpu.available", "status": "PASS", "detail": "NVIDIA GeForce RTX 3060 Ti",
     "duration_ms": 12, "measured": {"device_count": 1}}
  ],
  "summary": {"total": 11, "pass": 9, "fail": 1, "skip": 1},
  "overall": "FAIL"
}
```

`status ∈ {PASS, FAIL, SKIP}`. Exit codes: **0** = every non-skipped check passed; **1** = at least
one FAIL; **2** = the preflight itself could not run (profile missing, config invalid, unreadable
`.env`). A SKIP never changes the exit code. `infra/scripts/preflight.sh` wraps the command for the
compose stack and is what a demo operator runs.

---

## 6. Resilience (SPEC §39) → mechanism

| SPEC §39 requirement | Mechanism | Where |
|:--|:--|:--|
| Browser refresh: restore active session | REST snapshot (`GET /api/v1/sessions/{id}`) + WebSocket `{"type":"resume","after_seq_no":N}`; the server replays `session_events` from PostgreSQL then tails Redis. Nothing lives only in the browser (D8). The `SimulationRunner` re-adopts ACTIVE sessions on backend start and derives sim time from persisted `started_at` plus paused intervals (D7), so a refresh or a restart never resets the clock. | backend WS handler, `SimulationRunner` |
| TTS failure: log and use configured fallback | `guard_inference("TTS")` catches the failure, records the metric with `status = "ERROR"`, emits `MODEL_ERROR {stage: "TTS"}`, sets that provider NOT_READY, and re-synthesises the same validated text through `tts.fallback_provider`. The turn continues; the trainee hears the line in the fallback voice. If the fallback also fails, the turn ends with `CALLER_UTTERANCE_INTERRUPTED`-shaped bookkeeping (`delivered_audio_ms = 0`) and no `FACTS_DELIVERED`. | `TurnPipeline`, `workers/voice_agent/health.py` |
| Invalid LLM structured output: one repair retry, then safe fallback | Interpreter: schema validation → one repair prompt → `speech_act = UNINTELLIGIBLE` + `MODEL_FALLBACK_USED`. Generator: `ResponseValidator` → one regeneration → deterministic template from the gate-outcome table + `MODEL_FALLBACK_USED`. Exactly one retry in both places. | `50-voice-pipeline.md` §5.1, §7.7, §7.8 |
| ASR failure: do not corrupt state | ASR runs before any state write. On failure the pipeline emits `MODEL_ERROR {stage: "ASR"}`, writes **no** `ASR_FINAL`, writes **no** `transcript_segments` row, and the caller speaks the "please repeat" fallback. The audio segment is still written (the recording is evidence regardless). No card field, no fact, no state machine trigger depends on ASR (SPEC §9, §42 test 4). | `TurnPipeline` |
| LiveKit temporary reconnect: session/domain state survives | `LiveKitCallTransport` surfaces `RECONNECTING`/`RECONNECTED` as `TransportEvent`s; `TurnPipeline` emits `TRANSPORT_DISCONNECTED` / `TRANSPORT_RECONNECTED`, cancels any in-flight playback as a non-barge-in cancellation (no `CALLER_UTTERANCE_INTERRUPTED`, since nobody interrupted), resets the `TurnDetector`, and resumes. The session stays ACTIVE; PostgreSQL state is untouched; the runner keeps ticking. A disconnect longer than `transport.reconnect_grace_s` (default 30) emits `CALL_ENDED {reason: "TRANSPORT_LOST"}` and leaves the session for the instructor to decide. **The timer lives in `TurnPipeline`, never in the SDK wrapper** (E18-C): the transport's job is to report what the media plane did, and "how long a disconnect may last before the call is over" is configured product rule (SPEC §17), armed on `TRANSPORT_DISCONNECTED` and disarmed on `TRANSPORT_RECONNECTED`. A reconnect inside the grace period leaves exactly the two transport events behind and nothing else; beyond it, the call ends through the ordinary call-end path (`stop(reason)` → `_close_call()` → one `CALL_ENDED`), which is why no second code path can write session state. `CALL_ENDED.reason` is a free `str` in §10.13, so `TRANSPORT_LOST` needed no catalog change. | `TurnPipeline`, `LiveKitCallTransport` |
| GPU OOM: fatal inference health error, preserve session state | §4.4 above. | `workers/voice_agent/voice_agent/health.py`, `app.application.ports.inference_guard` |
| Never silently reset the simulation | There is no code path that writes `simulation_sessions.state` from the voice-agent: the worker has no session-state use case injected, in the same structural way the DDS services have no WorldTruth repository (D3). Session state changes only through backend use cases fired by a trainee, an instructor, or the world engine. Every abort is an explicit `SESSION_ABORTED` event with an actor. | D2/D3 wiring, enforced by `check_imports.py` |

---

## 7. Benchmarks (SPEC §40)

Target files (SPEC §35 names, literally): `benchmarks/benchmark_asr.py`,
`benchmarks/benchmark_llm.py`, `benchmarks/benchmark_tts.py`, `benchmarks/benchmark_e2e.py`,
`benchmarks/benchmark_vram.py`. Shared helpers in `benchmarks/_common.py`
(profile loading, NVML sampling, percentile computation, result writing).

### 7.0 Common contract

- Every script takes `--profile NAME` (default `$MODEL_PROFILE`), `--out DIR`
  (default `benchmarks/results/`), `--runs N`, `--seed N` and `--tag TEXT`.
- Every script writes **two** files: `{out}/{name}-{profile}-{timestamp}.json` and a flat
  `{out}/{name}-{profile}-{timestamp}.csv` of the per-sample rows (SPEC §40 "export to JSON/CSV").
- Every JSON has the same envelope:

  ```json
  {
    "schema_version": 1,
    "benchmark": "asr",
    "status": "OK",
    "profile": "DEV_3060TI",
    "git_sha": "…",
    "started_at": "…", "finished_at": "…",
    "hardware": {"gpu_name": "…", "driver": "…", "total_vram_mb": 8192},
    "config": { "…the relevant profile subtree…" },
    "samples": [ … per-sample rows … ],
    "aggregates": { … },
    "notes": []
  }
  ```

- **`status` is `OK`, `PARTIAL`, `FAILED` or `NOT_RUN`.** A benchmark that did not run writes
  `status: "NOT_RUN"`, a `reason` string, `samples: []` and `aggregates: {}` — it **never** writes a
  number. There is no default, no estimate and no carried-over figure. `_common.write_result()` is
  the only writer and it refuses to emit an aggregate when `status != "OK"` and `samples` is empty.
  This is the mechanical form of SPEC §27's "do not fake or hard-code benchmark values".
- Percentiles are computed with the nearest-rank method over the raw samples and every aggregate
  carries its `n`.

### 7.1 `benchmark_asr.py`

**Corpus** `benchmarks/data/asr/` with a manifest `manifest.jsonl`, one JSON object per line:

```json
{"id": "addr_003", "path": "clean/addr_003.wav", "reference": "улица Ленина дом двадцать семь квартира пять",
 "category": "ADDRESS", "condition": "CLEAN", "duration_ms": 4120}
```

```
benchmarks/data/asr/
  manifest.jsonl
  clean/     short/ medium/ long/ utterances, WAV 16 kHz mono
  noisy/     the same utterances mixed with room/street noise at a recorded SNR
  README.md  how the corpus was recorded; licence of every sample
```

`category ∈ {SHORT, MEDIUM, LONG, ADDRESS, NUMBER, TERMINOLOGY}` covers SPEC §40's "several
utterance lengths / addresses / numbers / emergency terminology";
`condition ∈ {CLEAN, NOISY}` covers clean/noisy.

**Measured:** per sample — `latency_ms`, `rtf` (= `latency_ms / duration_ms`), `wer`, `cer`,
`entity_accuracy` (fraction of reference numbers/addresses/names present in the hypothesis after the
Russian numeral folding of `50-voice-pipeline.md` §7.2, so «27» and «двадцать семь» count as equal).
**Aggregates:** per `category` × `condition` and overall — `n`, `latency_p50_ms`, `latency_p95_ms`,
`rtf_mean`, `wer_mean`, `cer_mean`, `entity_accuracy_mean`.
Run once per `asr.model_version` so `v3_e2e_ctc` and `v3_ctc` are comparable (SPEC §19).

### 7.2 `benchmark_llm.py`

**Inputs:** `benchmarks/data/llm/interpreter_cases.jsonl` (utterance + fact catalog + expected
`speech_act` and expected `requested_facts`), `benchmarks/data/llm/dialogue_cases.jsonl` (multi-turn
scripts for consistency), and the §43 adversarial question matrix, which this script reuses from
`backend/tests/adversarial/` rather than duplicating (D13).

**Measured per sample:** `ttft_ms`, `total_latency_ms`, `output_tokens`, `tokens_per_second`,
`structured_output_valid` (bool — parsed, schema-valid, `extra="forbid"` clean),
`repair_used` (bool), `forbidden_fact_leak` (bool — the `50-voice-pipeline.md` §7.6 world-value leak
check run over the response), `validator_failure_codes` (list).
**Aggregates:** `ttft_p50_ms`, `ttft_p95_ms`, `tokens_per_second_mean`,
`structured_output_validity_rate`, `repair_rate`, **`forbidden_fact_leak_rate`** (SPEC §43; the
deterministic-boundary target is 0), `dialogue_consistency_rate` (fraction of multi-turn scripts in
which no later caller turn contradicts an earlier delivered value, checked by exact canonical-value
comparison, not by a model).

### 7.3 `benchmark_tts.py`

**Inputs:** `benchmarks/data/tts/lines.jsonl` — `{id, text, category}` with
`category ∈ {SHORT, MEDIUM, LONG, NUMERIC, ADDRESS}`, Russian caller-style lines.
**Measured per sample:** `first_audio_latency_ms` (request → first `TtsChunk`),
`total_synthesis_latency_ms`, `output_audio_ms`, `rtf` (= `total_synthesis_latency_ms /
output_audio_ms`), `peak_vram_mb` (NVML sampled every 100 ms during the call), and for the
cancellation sub-suite `cancel_latency_ms` (`cancel()` call → generator actually stopped),
`chunks_after_cancel` (must be 0 or 1) and `alignment_is_exact`.
**Aggregates:** per category — `first_audio_p50_ms`, `first_audio_p95_ms`, `rtf_mean`,
`peak_vram_mb_max`; plus `cancel_latency_p95_ms` and `chunks_after_cancel_max` over the cancellation
sub-suite. Run once per configured TTS provider so Qwen3-TTS 1.7B CustomVoice, Chatterbox
Multilingual and Piper are comparable (SPEC §25).

### 7.4 `benchmark_e2e.py`

**Input:** a scenario slug plus `benchmarks/data/e2e/turns.jsonl` — pre-recorded trainee WAV turns
played into a real LiveKit room by a headless client, so the measurement includes VAD, the transport
and the browser-equivalent path, not just model time.
**Measured precisely from `USER_SPEECH_ENDED` to the first emitted/played caller audio** (SPEC §40),
taken from the session event log itself so the benchmark and the product metric cannot diverge:
`speech_end_to_first_audio_ms` per turn, plus the stage split `asr_ms`, `interpret_ms`, `gate_ms`,
`generate_ms`, `validate_ms`, `tts_first_chunk_ms`, `transport_ms` reconstructed from
`inference_metrics` rows sharing the `turn_id`.
The barge-in sub-suite additionally reports `cutoff_latency_ms` per interruption (the §6.2 budget of
`50-voice-pipeline.md`) with `p50`/`p95` and a `over_250ms_count`.
**Aggregates:** `n`, `p50_ms`, `p95_ms`, `p99_ms`, the per-stage `p50`, and
`meets_target` — a bool comparing `p50`/`p95` against the active profile's `latency_targets`.

### 7.5 `benchmark_vram.py`

**Measures** idle model residency and peak during a realistic sequence (SPEC §40).
**Sequence:** start with nothing loaded → load VAD → load ASR → load TTS → wait for llama-server →
sample idle → run `--turns N` (default 20) realistic turns (ASR + interpret + generate + TTS
concurrently as the pipeline does, with `parallel_slots` respected) → sample peak → idle again.
NVML is sampled every 100 ms for the whole run; when NVML is unavailable the script writes
`status: "NOT_RUN"`, `reason: "NVML unavailable"` and no numbers.
**Reported:** `baseline_used_mb` (before this project loads anything — on the dev machine this is the
owner's ~5 GB), `idle_after_load_mb`, `peak_mb`, `project_peak_mb` (= `peak_mb - baseline_used_mb`),
`free_min_mb`, and per-service deltas `vad_delta_mb`, `asr_delta_mb`, `tts_delta_mb`, `llm_delta_mb`.
`project_peak_mb` is the value a human copies into the profile's `measured_peak_vram_mb`, together
with `measured_at`; the script prints that line ready to paste but **never edits the profile file
itself** — a measurement entering configuration is a human decision.

---

## 8. llama-server launch flags

Run inside the `llama-server` compose service; `SIM_MODEL_PROFILE` selects which line is used
(computed, not stored: `infra/scripts/llama-server-entrypoint.sh`, E18-E, reads the
`SIM_LLAMA_*` env vars `make profile-env`/`app.config.profile_env --emit-env` derive from the
active profile's `llm.*` block, and builds the flag line below itself — no profile YAML restates
it). Flags are llama.cpp server flags; the exact set available depends on the build, so any flag
that a given build rejects is reported at start-up rather than silently dropped.

**Image pin (E18-E, 2026-09-22):** `infra/docker-compose.yml`'s `llama-server` service pins
`ghcr.io/ggml-org/llama.cpp:server-cuda-b11065` (override with `LLAMA_CPP_IMAGE`) — confirmed to
exist via `docker manifest inspect ghcr.io/ggml-org/llama.cpp:server-cuda-b11065` (read-only, no
pull; resolved to a two-platform, amd64+arm64, OCI image index). **UNVERIFIED still:** the precise
flag spelling this specific tag accepts — no pull was done (E18 forbids GPU work/model downloads;
`TODO(E19)`: run `llama-server --help` against the pinned tag for real and reconcile any flag this
document gets wrong before the first real launch).

**DEV — Qwen3-4B on the 3060 Ti (partial offload, CPU-heavy):**

```
llama-server \
  --model /models/llm/Qwen3-4B-Q4_K_M.gguf \
  --alias Qwen3-4B \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 4096 \
  --parallel 2 \
  --n-gpu-layers 20 \
  --batch-size 512 --ubatch-size 256 \
  --flash-attn on \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --threads 8 \
  --jinja \
  --chat-template-kwargs '{"enable_thinking": false}' \
  --no-warmup=false \
  --metrics
```

**FINAL — Qwen3-8B Q4_K_M on the 3080 Ti (full offload):**

```
llama-server \
  --model /models/llm/Qwen3-8B-Q4_K_M.gguf \
  --alias Qwen3-8B \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 4096 \
  --parallel 2 \
  --n-gpu-layers -1 \
  --batch-size 1024 --ubatch-size 512 \
  --flash-attn on \
  --cache-type-k f16 --cache-type-v f16 \
  --threads 8 \
  --jinja \
  --chat-template-kwargs '{"enable_thinking": false}' \
  --metrics
```

Notes that matter for this project:

- `--ctx-size` is the **total** KV budget shared across `--parallel` slots, so `4096` with
  `--parallel 2` gives each slot ~2048. Our prompt budget of 2700 tokens
  (`50-voice-pipeline.md` §5.3) therefore requires either `--parallel 1`, or `--ctx-size 8192` with
  `--parallel 2`. **Decision for this HLD:** `--ctx-size` is set to
  `n_ctx * parallel_slots` at launch and the profile's `n_ctx: 4096` remains the **per-request**
  context that SPEC §22/§26 mandates. The launch script computes it; the profile does not restate it.
- `--jinja` is required for the Qwen3 chat template to be applied server-side, which is what makes
  `chat_template_kwargs.enable_thinking=false` effective. The `/no_think` prefix (D10) is kept as a
  belt-and-braces measure for builds that ignore the kwarg.
- `--flash-attn on` is enabled on both profiles; if the build reports it unsupported for the card,
  the launch script falls back to `auto` and logs it.
- No flag exposes the server outside the compose network: `--host 0.0.0.0` is bound inside the
  network only and the service publishes **no** host port (SPEC §41).
- `--metrics` exposes llama.cpp's own Prometheus endpoint for debugging. It is not the source of
  `InferenceMetric`: that comes from `MetricsRecorder` on our side of the port, so the numbers in the
  report are the numbers the application actually experienced.

---

## 9. Docker compose service notes (BUILT — E18-E)

`infra/docker-compose.yml` now has all eight: the SPEC §36 seven, named exactly — `postgres`,
`redis`, `livekit`, `backend`, `frontend`, `llama-server`, `voice-agent` — plus the additive eighth,
`tts-qwen3`, gated behind `profiles: ["qwen3-tts"]` so a plain `docker compose up` (or `make up`)
starts exactly the SPEC seven; `TTS_COMPOSE_PROFILE=qwen3-tts make up` (or
`docker compose --profile qwen3-tts up`) opts into the eighth. `make compose-check` (wired into
`gate-backend`) renders the whole file — all eight service definitions, via
`--profile qwen3-tts config -q` — against `infra/compose.check.env`'s throwaway (>= 32-byte)
placeholder secrets, building and pulling nothing, so the gate catches a YAML/interpolation mistake
without a real `.env` or Docker Hub/GHCR access.

### `llama-server`

- Image: **pinned** `ghcr.io/ggml-org/llama.cpp:server-cuda-b11065` (override via
  `LLAMA_CPP_IMAGE`), never `:latest`. Confirmed to exist with `docker manifest inspect` (read-only,
  no pull) on 2026-09-22 — resolves to an amd64+arm64 OCI image index. The exact **flag spelling**
  this tag's binary accepts is still **UNVERIFIED** (no pull was done; `TODO(E19)`, see §8).
- `runtime: nvidia` / `deploy.resources.reservations.devices` with `capabilities: [gpu]`;
  `NVIDIA_VISIBLE_DEVICES` from `.env` so the dev machine can pin a device.
- Volumes: `${MODELS_DIR}:/models:ro`, plus `infra/scripts/llama-server-entrypoint.sh` bind-mounted
  in (the pinned image has no Python to read a profile YAML itself). Models are never baked into an
  image and never downloaded at start-up (SPEC §41: everything local).
- `entrypoint:` is `infra/scripts/llama-server-entrypoint.sh` (E18-E, built), which reads the
  `SIM_LLAMA_*` env vars `env_file: infra/.env.profile` supplies and computes the §8 flag line,
  including `--ctx-size = n_ctx * parallel_slots`. That file is generated by `make profile-env`
  (new `backend/app/config/profile_env.py --emit-env`, E18-E) from the active profile's `llm.*`
  block — gitignored, regenerated on every `make up` / `make run-llama-server`, never hand-edited.
  `make run-llama-server` runs the identical script on the **host** (loopback, `LLAMA_SERVER_PORT`
  default 8180 — never 8000/8001/8011/8012/8016) with `SIM_LLAMA_SERVER_BIN` pointed at a real
  `llama-server` build.
- Healthcheck: `curl -fsS http://localhost:8080/health`; `start_period: 300s` (model load can be
  minutes on a busy card), `retries: 30`, `interval: 10s`.
- No `ports:` mapping. Reachable only as `http://llama-server:8080` inside the network, which is
  exactly what `LlamaCppClient`'s loopback/compose-internal `base_url` validation expects.
- `restart: unless-stopped`.

### `backend`, `frontend` (BUILT — E18-E; `docker compose build backend frontend` proved both, see
this task's report for the timed result)

- `backend`: `backend/Dockerfile`, repo-root build context (uv workspace — `sim-backend` needs every
  member's `pyproject.toml` to resolve against the shared `uv.lock`), no ML extras (the API process
  never loads a model itself). Healthcheck: `GET /api/v1/health/live`. Publishes `8100`.
- `frontend`: `frontend/Dockerfile`, runs the Vite **dev** server (`--host 0.0.0.0`), not a
  production build — this is the local dev/demo stack. `VITE_API_PROXY_TARGET=http://backend:8100`
  overrides the host-oriented default so the in-container proxy reaches the compose-internal
  backend. Publishes `5173` (the repo's existing dev port).
- Both `env_file: ../.env` with `required: false`, so `make compose-check` renders with no `.env`
  present; a real `up` still needs one (`cp .env.example .env`).

### `voice-agent` (Dockerfile written, UNVERIFIED-BUILD — no GPU work in E18, E19 builds/runs it)

- Built from `workers/voice_agent/Dockerfile`; installs the uv workspace with the extras the profile
  needs (`asr-gigaam`, `vad-silero`, `tts-piper`, …) as a comma-separated `VOICE_AGENT_EXTRAS` build
  arg — heavy extras stay a build-time choice so the DEV image does not carry GPU TTS stacks it will
  not use (D1). **`tts-qwen3` is never one of these extras** (E14-B): Qwen3-TTS lives in the
  separate `tts_qwen3` worker process/venv below, never imported by `voice-agent` itself
  (`backend/tools/check_imports.py`).
- `runtime: nvidia` with the same device pinning; on DEV the GPU is used for the ASR model and, via
  the separate `tts_qwen3` worker process (not this container's own process), TTS — OWNER DECISION,
  E14. VAD still runs on CPU (§1). Does **not** hard-depend on `tts-qwen3` in compose (that service
  is the profiled eighth; a plain `up` never starts it) — `Qwen3TTS`'s httpx client simply fails its
  calls if unreachable, the same as any other TTS-provider failure (SPEC §39 #2).
- Publishes no port; `SIM_VOICE_AGENT_HTTP_PORT` (default 8113, R7 of the E18 brief) is reachable
  only from other containers on the compose network, never published to the host.
- Healthcheck: `python -m voice_agent.cli health`, per this document's own long-standing spec —
  **not built yet** as of E18-E (`workers/voice_agent/voice_agent/cli.py` does not exist; owned by
  a different E18 slice). The compose healthcheck is written to match this document exactly and
  will start passing once that CLI lands; until then the container correctly shows "unhealthy"
  rather than silently green.
- `restart: unless-stopped`, but **no** automatic restart loop around a FATAL state: the health key
  `voice:health:fatal` survives a container restart (§4.3), so a restarted agent comes back FATAL
  until a human clears it.

### `tts-qwen3` worker (E14-B; now its own compose service, E18-E — additive eighth, `profiles:
["qwen3-tts"]`; Dockerfile written, UNVERIFIED-BUILD, same posture as `voice-agent` above)

- Standalone package `workers/tts_qwen3/` (own `pyproject.toml`, own venv — `qwen-tts==0.1.1` pins
  `torch==2.14.0`, outside the `asr-gigaam` extra's `torch<2.9` ceiling, so it cannot share a venv
  with `backend`/`voice-agent`; see `workers/tts_qwen3/README.md`). `workers/tts_qwen3/Dockerfile`
  builds it self-contained (own build context, not the uv workspace).
- `Qwen3TTS` (`backend/app/inference/tts/qwen3_tts.py`) is the only caller: an `httpx` client whose
  `base_url` is validated loopback/compose-internal at construction (SPEC §41), mirroring
  `LlamaCppClient`'s `validate_llm_base_url`.
- Health: `GET /health` -> `{status, model, revision, device, loaded}` — a simpler shape than the
  `voice:health:{service}` Redis contract §4.3 describes for `llm`/`asr`/`vad`/`tts`; **the
  `voice:health:tts` heartbeat key itself is still owned by `voice-agent`'s own warm-up sequence
  (§4.2 step 4), not by this worker** — `voice-agent` polls this worker's `/health` (and drives
  `POST /warm_up`) the way it drives every other provider's `warm_up()`, then publishes
  `voice:health:tts` itself, same as every other service in §4.3's table.
- **KNOWN GAP (E18-E's report, "HLD gaps"):** `workers/tts_qwen3/tts_qwen3/__main__.py` hard-codes
  `uvicorn.run(..., host="127.0.0.1", ...)`. Inside its own container that binds the worker to its
  OWN loopback interface only — `voice-agent` (a different container) cannot actually reach it at
  `http://tts-qwen3:8112` as this section promises, even though no host port is published either
  way. Fixing the bind (e.g. an env-overridable host, defaulting to loopback for the bare-metal
  `make run-tts-qwen3` path) is outside E18-E's file ownership (`__main__.py` belongs to E14-B's
  slice) — flagged here rather than worked around.
- `depends_on`: `redis` (service_started), `postgres` (service_healthy), `livekit`
  (service_started), `llama-server` (service_healthy). It tolerates llama-server being slow anyway —
  the warm-up polls (§4.2) — but the ordering keeps the logs readable.
- Volumes: `${MODELS_DIR}:/models:ro` and `${DATA_DIR}:/data`.
- Env: `SIM_TTS_QWEN3_MODEL` (variant, default `1.7B`), `SIM_TTS_QWEN3_MODEL_DIR`,
  `SIM_TTS_QWEN3_PORT`. No secret; nothing in source (SPEC §41).
- It publishes no port; it is a pure client of nothing (no outbound dependency besides its own
  model files) and is itself dialled by `voice-agent`, subject to the KNOWN GAP above.

Shared: `backend`/`voice-agent` get `.env` via `env_file` (`required: false`, so `make compose-check`
needs no real `.env`), GPU services use the NVIDIA runtime, `${DATA_DIR}`/`${MODELS_DIR}` default to
the repo-root `data/`/`models/` directories and are never baked into an image, and the test stack
(`infra/docker-compose.test.yml`, ports 55432 / 56379, tmpfs) contains only `postgres` and `redis`
because the gate runs entirely on fake providers (D1, D13).

---

## 10. Open items for the manager

1. Every VRAM number in every profile is `null` and every profile is therefore **unmeasured**; the
   FINAL profiles are refused by `validate_vram_margin` until `benchmark_vram.py` has been run. That
   is the intended state, not an omission.
2. **Resolved, E18-A:** `DEV_3060TI.llm.n_gpu_layers: 20` and `vram_budget_mb: 2800` (both
   never-measured starting points) are gone — OWNER DECISIONS 2026-09-21 replaced the LLM with the
   measured Qwen3.5-2B choice (`n_gpu_layers: -1`, task reports e13-b3/e13-b4) and
   `vram_budget_mb: 7168` assumes a dedicated card (§1, §2.2); `DEV_3060TI_SHARED` (§2.2a) is the
   additive profile for this machine's actual shared-card state. `measured_peak_vram_mb` is still
   `null` on `DEV_3060TI` itself (a COMBINED three-model peak has never been run) — `TODO(E19)`.
3. **Partially resolved, E18-E:** the llama.cpp tag is now pinned
   (`ghcr.io/ggml-org/llama.cpp:server-cuda-b11065`, confirmed to exist via `docker manifest
   inspect`, read-only, no pull) and `infra/scripts/llama-server-entrypoint.sh` computes the §8 flag
   line from the active profile. The exact spelling of `--chat-template-kwargs` / `--flash-attn on`
   this specific tag's binary accepts is still UNVERIFIED — no pull was done (E18 forbids GPU work);
   `TODO(E19)`: run it for real and reconcile.
4. Voice ids: Piper's is now pinned and measured (`ru_RU-irina-medium`, `make models-piper`, §11's
   model table — no longer a placeholder). Qwen3-TTS's is a real vendor CustomVoice speaker name
   (`Serena`, one of the closed four `Serena`/`Ryan`/`Vivian`/`Aiden` — E14-B recon §1.1), not a
   free-form Russian voice id at all; which of the four "sounds best" for the demo's caller persona
   is still UNVERIFIED (no listening evaluation has been done). Chatterbox's remains an UNVERIFIED
   placeholder — out of E14-B's scope (E14-B built `Qwen3TTS`/`PiperTTS` only).

   **E14 close-out (item 7): Piper's real contract run, measured** — `SIM_RUN_MODEL_TESTS=1 uv run
   pytest backend/tests/models/test_tts_contract.py -k piper -s`, real `piper-tts==1.8.0` (installed
   by the new `make deps-tts-piper` target) + real GigaAM v3 e2e CTC ASR (`device=cuda`), on
   `andreipc-B660M-DS3H-DDR4` (RTX 3060 Ti 8 GB, the same dev machine `DEV_3060TI` describes),
   2026-09-21. This surfaced and fixed a real adapter bug, not a config gap: `piper_tts.py` called
   `PiperVoice.synthesize_stream_raw()`, an API the installed `piper-tts>=1.2,<2` range no longer
   has (it exposes `synthesize(text) -> Iterable[AudioChunk]` instead, `AudioChunk.audio_int16_bytes`
   the s16le PCM) — the extra had never actually been installed anywhere before this task, so this
   was never run against the real package (E14-B's report, "what was NOT run"). Fixed to call the
   real API; behaviour (bounded, cancellable drain via `asyncio.to_thread(next, ...)`) unchanged.
   Five Russian dispatcher-style sentences, all passed (`wer <= 0.6` for every row):

   | sentence | first_chunk_ms | total_ms | rtf | sample_rate | wer |
   |:--|--:|--:|--:|--:|--:|
   | «Служба сто двенадцать, что у вас случилось?» | 153.6 | 153.6 | 0.052 | 22050 | 0.286 |
   | «Назовите, пожалуйста, точный адрес происшествия.» | 98.8 | 98.9 | 0.023 | 22050 | 0.0 |
   | «Есть ли пострадавшие, нуждающиеся в помощи?» | 87.1 | 87.1 | 0.027 | 22050 | 0.0 |
   | «Оставайтесь на линии, я направляю к вам бригаду.» | 81.5 | 81.5 | 0.024 | 22050 | 0.0 |
   | «Повторите, пожалуйста, номер телефона ещё раз.» | 99.9 | 100.0 | 0.026 | 22050 | 0.0 |

   `first_chunk_ms == total_ms` on every row because `_measure_provider` buffers Piper's whole
   sentence before its first `TtsChunk` (`piper_tts.py`'s documented "HLD gap": re-chunking is
   post-hoc, not incremental) — a measurement, not a target; §7.3's `benchmark_tts.py` is the
   target-bearing benchmark. The one non-zero WER (0.286, «Служба сто двенадцать» → GigaAM heard
   «Служба 112») is GigaAM normalising the digits, not a Piper intelligibility defect.
   `nvidia-smi --query-compute-apps` before and after: only the owner's PID 1082982 at 4638 MiB,
   unchanged — GigaAM ran on GPU (~1.3 GB, fits the ~3.2 GB free) without touching that PID.
5. `--ctx-size` vs `--parallel` (§8, first note) is the one place this document had to choose a
   mechanism the frame did not name; it is listed for ratification in the task report.
6. **E14-D: the model variant is now a config choice** (`SIM_TTS_QWEN3_MODEL` = `1.7B` default |
   `0.6B`, `workers/tts_qwen3/tts_qwen3/server.py`'s `MODEL_VARIANTS`; `Makefile`'s
   `QWEN3_TTS_VARIANT` for `models-tts-qwen3`/`run-tts-qwen3`) — this also fixed a latent bug the
   worker never actually had exercised for real before: `create_app()` used to pass
   `SIM_TTS_QWEN3_MODEL_DIR` straight to `Qwen3TTSModel.from_pretrained()`, but that directory is
   the *parent* both checkpoints' own subdirectories share (`make models-tts-qwen3`'s own download
   layout) — `from_pretrained()` needs the directory that directly holds `config.json`/
   `model.safetensors`. Neither variant had ever actually been loaded by this worker before this
   task (E14-B/E14-C both measured free VRAM too low to try the 1.7B); this task's own real run of
   0.6B is what surfaced it, fixed by resolving `SIM_TTS_QWEN3_MODEL_DIR / MODEL_VARIANTS[variant]
   .subdirectory` inside `create_app()` — covered by new unit tests (default-variant-resolves-the-
   1.7B-subdirectory, 0.6B-resolves-its-own-subdirectory), so the 1.7B path is provably correct too,
   even though this machine still cannot load it to prove that end-to-end.

   **1.7B: still NOT_RUN.** Free VRAM measured live at the start of this task (2026-09-22,
   `andreipc-B660M-DS3H-DDR4`, RTX 3060 Ti 8 GB): **3196 MB**, below the ~4.6 GB the 1.7B checkpoint
   needs (bf16 residency, E14-B recon §1.1) — the owner's other resident process (PID 1082982,
   Higgs-TTS, 4638 MiB) holds the rest of the 8 GB card. Unchanged since E14-B/E14-C; this task did
   not attempt the 1.7B.

   **0.6B: real run, measured** (`SIM_TTS_QWEN3_MODEL=0.6B`, worker started by hand on port 8112,
   loopback only; `uv run python benchmarks/tts_qwen3_0_6b_real_run.py synth`/`asr`, same machine,
   2026-09-22). Checkpoint `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice@85e237c12c027371202489a0ec509ded6
   7b5e4b5` (revision verified against every `.cache/huggingface/download/*.metadata` first line
   under the already-downloaded checkpoint — all agree; not this task's own guess). Load time
   **10.66 s**; worker peak VRAM **~2746 MiB** (sampled after each of the 20 calls below via
   `nvidia-smi --query-compute-apps`, not a continuous sampler — a *lower bound* on the true peak,
   noted as such, not invented as exact). `nvidia-smi --query-compute-apps` before/during/after:
   only the owner's PID 1082982 at 4638 MiB throughout, plus the worker's own PID while it ran —
   never touched, confirmed clean after every step.

   20/20 syntheses through the real `Qwen3TTS` adapter succeeded (2 vendor speakers — `Serena`,
   `Ryan` — x 2 emotions — `CALM`, `PANICKED`, via `TtsVoiceSpec.emotion` — x the same 5 Russian
   sentences item 4's Piper table uses), saved as WAVs, then (worker stopped first, to free VRAM
   before loading GigaAM — this task's brief, "TTS + ASR together may not fit the free VRAM")
   transcribed by real GigaAM `v3_e2e_ctc` (load 7.38 s) for WER. Full 20-row table:
   `benchmarks/results/tts_eval/20260921T222848Z/results.{json,md}` (gitignored, this checkout).
   Aggregates: RTF mean **0.831** (min 0.802, max 0.881) excluding one 4.316 first-call outlier
   (the very first `/synthesize` after `/warm_up`, consistent with a one-time CUDA
   kernel-autotune/cache-fill cost, not a per-call cost — every subsequent call, across both
   speakers and both emotions, landed in the same 0.80-0.88 band); mean WER **0.115** (`CALM` 0.077,
   `PANICKED` 0.152, max 0.571) — all comfortably under the `wer <= 0.6` bar item 4's Piper table
   uses. Time-to-first-audio-frame (which, for this whole-utterance-per-call provider, equals total
   synth time — the same documented `Qwen3TTS`/HLD gap the module's docstring already states) mean
   **~3.66 s** excluding the outlier: far past any per-turn first-chunk budget, expected given the
   architecture (this is why the sentence chunker splits a turn into short units before calling this
   provider at all, D9 §2.4), not a 0.6B-specific regression versus the (never-run) 1.7B.

   **`instruct`/emotion:** the 0.6B checkpoint accepts the same `instruct` field the 1.7B API takes
   and visibly responds to it — every `PANICKED`-emotion row's GigaAM transcript contains an
   emotional interjection the *reference* sentence does not ("Ха-ха.", "А-э-а.", "А!" — e.g. Ryan/
   panicked/sentence 1: reference «Служба сто двенадцать, что у вас случилось?», GigaAM heard
   «Ха-ха. Служба 112, что у вас случилось?», `wer=0.571`), while every `CALM`-row transcript has no
   such interjection. This is the checkpoint following the emotional instruct, not an intelligibility
   defect — it is exactly why `PANICKED`'s mean WER (0.152) is higher than `CALM`'s (0.077): the
   *reference* text is what the operator would need transcribed, and the model is (correctly, per
   its instruction) adding non-lexical vocalisations a strict word-level WER penalises. No adapter
   or worker code change was needed for this to work; nothing paved over.

   **Does 0.6B fit `DEV_3060TI` beside GigaAM + the LLM, by simple measured arithmetic?** 0.6B TTS
   (~2746 MiB, this task) + GigaAM (~1336 MiB, per this document's own item-4 close-out measurement
   rounded) + a `llama-server` Qwen3.5-2B (~1558 MiB, as given) = **~5640 MiB**, comfortably under
   an *unshared* RTX 3060 Ti's 8192 MiB (~2552 MiB margin). It does **not** fit *this specific dev
   machine as currently configured*: the owner's own unrelated 4638 MiB resident process leaves only
   ~3554 MiB nominal / ~3196 MiB measured free, well under the ~5640 MiB the three simulator
   components alone would need running together. Whether to change any profile's default variant
   from these numbers is a manager decision (this task changed no profile default).

---

## 11. Model sources, pinned revisions and licences (E12)

Additive to §2's `asr.model_path` / `vad.model_path` keys — this table is where each path's
provenance is recorded, since the profile itself only points at a directory. Fuller detail (exact
URLs, sha256, `make` target) lives in `models/README.md`; this table is the cross-reference SPEC §41
("everything local, nothing downloaded at runtime") expects a reader of this document to find.

| Model | `model_version` | Source | Pinned revision | Licence | Fetched by |
|:--|:--|:--|:--|:--|:--|
| Silero VAD | (`vad.provider: silero`) | `github.com/snakers4/silero-vad`, `src/silero_vad/data/silero_vad.onnx` | tag `v5.1.2` (the v5 model interface this port's `SileroVAD` is written against — `v6.x` changed the graph) | MIT | `make models-silero`, sha256-checked |
| GigaAM Conformer-CTC | `v3_e2e_ctc` (primary, SPEC §19) | local HF-format checkpoint (owner-provided; exact upstream repo/revision UNVERIFIED by this task — see `models/README.md`) | n/a — files placed manually, not re-fetched by any `make` target | MIT (per the checkpoint's own `README.md`) | manual; `models/` is gitignored (SPEC §41) |
| GigaAM Conformer-CTC | `v3_ctc` (benchmarked alternative, SPEC §19) | same as above | same as above | MIT | manual |
| faster-whisper (optional) | whisper size per `SIM_WHISPER_MODEL_PATH` | not fetched by this project at all (E12 ruling 4) | n/a | n/a | never — a developer points `SIM_WHISPER_MODEL_PATH` at a CTranslate2 model they already have |
| Qwen3-4B (LLM, `llm.provider: llama_cpp`, DEV_3060TI, SPEC §22) | `Qwen3-4B-Q4_K_M` | `huggingface.co/Qwen/Qwen3-4B-GGUF`, file `Qwen3-4B-Q4_K_M.gguf` | HF repo `main` at fetch time; file identity is the sha256 below, not a git commit (E13-B1 measured 2026-09-21: 2 497 280 256 bytes, sha256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` — matches the HF repo's own LFS `sha256` for this file, queried via `HfApi.model_info(files_metadata=True)`) | Apache-2.0 (per the repo's own licence file) | `make models-llm` (`hf download`, `curl -C -` fallback), sha256 not re-verified by the target itself — see this task's report |
| Qwen3-TTS 1.7B CustomVoice (`tts.provider: qwen3_tts`, GPU default incl. DEV_3060TI, OWNER DECISION E14) | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice@0c0e3051f131929182e2c023b9537f8b1c68adfe` | `huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | pinned commit `0c0e3051f131929182e2c023b9537f8b1c68adfe` (owner-evaluated, E14-B recon §1.1) | see the repo's own licence file | `make models-tts-qwen3` (`hf download`, only when >= 12 GB disk is free — NOT_RUN otherwise); loaded by the standalone `workers/tts_qwen3` worker, never by `backend`/`voice-agent` directly |
| Qwen3-TTS-Tokenizer-12Hz (paired with the checkpoint above) | n/a | `huggingface.co/Qwen/Qwen3-TTS-Tokenizer-12Hz` | pinned commit `7dd38ad4e9bad454aae9cd937d0cd577604fe229` (owner-evaluated, E14-B recon §1.1) | see the repo's own licence file | `make models-tts-qwen3` |
| Piper `ru_RU-irina-medium` (`tts.provider: piper`, CPU, the configured fallback) | `ru_RU-irina-medium` | `huggingface.co/rhasspy/piper-voices`, path `ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx` (+ `.onnx.json`) | HF repo `main` at fetch time; file identity is the sha256 recorded by this task's report (measured, not pinned in advance — same posture as the Qwen3-4B GGUF row above) | MIT (per `rhasspy/piper-voices`) | `make models-piper` (`curl -C -`, retried) |

`GigaAMProvider` (`backend/app/inference/asr/gigaam_provider.py`) loads the local directory with
`AutoModel.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True)` and
`HF_HUB_OFFLINE=1`, and never calls the checkpoint's own `transcribe()` — see that module's
docstring for the ffmpeg/pyannote reasons and for the long-audio window-splitting it does instead.

---

## 12. Score explanation (E16-B, SPEC §2, §29, D11)

A second, independent `LLMClient` — not the interpreter/generator's `SIM_LLM_*` one above. It is
built and called by the **backend** process itself
(`app.inference.llm.explanation_client.build_explanation_llm_client`), never by the voice-agent
worker: `generateReportExplanation`/`getReportExplanation` are backend HTTP routes, not turn-loop
calls (D9). `SIM_EXPLANATION_LLM_PROVIDER` (`fake` | `llama_cpp`) selects the same two adapter
classes §8's client uses (`FakeLLM`, `LlamaCppClient`) — a second instance, its own
`SIM_EXPLANATION_LLM_BASE_URL` (loopback/compose-internal only, SPEC §41, validated at
construction exactly as §8's client is), model alias, `max_tokens`, `temperature` and
`timeout_ms`; `fake` is what `make gate` runs (D13), matching every other model call in this
project.

**Prompt inputs (the whole of it — R8's whitelist).** `app.application.reports.explanation.prompt.
build_messages` takes exactly a `ScoreReport`, the scenario's `rule_id -> name_ru` mapping and an
`audience` (`TRAINEE` | `INSTRUCTOR`). No transcript, no `WorldTruth`, no `OperatorCard` — the
function has no parameter that could carry one, which is checked at the type level, not by
convention (`backend/tests/unit/application/reports/explanation/test_prompt.py`). The system
prompt instructs the model to cite rule titles and the awarded/max points **exactly as given**,
never a different number, and never invent a fact about the call; `TRAINEE` reads supportive and
didactic, `INSTRUCTOR` concise and analytic.

**Limits.** `SIM_EXPLANATION_MAX_TOKENS` defaults to 400 (a few short paragraphs of prose, not a
JSON turn); `SIM_EXPLANATION_TEMPERATURE` defaults to `0.2` (lower than the caller generator's
`0.7` — an explanation cites given numbers rather than improvising a persona); `SIM_EXPLANATION_
TIMEOUT_MS` defaults to 8000.

**Failure behaviour (SPEC §26, §41 — "the core works without it").** The explanation is generated
only from an already-persisted `ScoreReport`; a session that is not `COMPLETED` or has no stored
score is refused with the same `409 REPORT_NOT_READY` the report itself uses (R1). A second
`POST` without `regenerate: true` is `409 EXPLANATION_ALREADY_EXISTS`. An LLM timeout, an
unreachable server, or a completion with no usable text is `503 LLM_UNAVAILABLE`; nothing is
stored, and the report — scores, evidence, timeline, everything SPEC §29 asks for — is entirely
unaffected, because the explanation use case never holds a write path to the score tables at all
(structural guarantee, `backend/tests/invariants/test_explanation_cannot_write_scores.py`).

`TODO(E19)`: a `requires_models` latency benchmark for the explanation call (comparable to the
interpreter/generator eval harnesses of §7) is not part of this task — no real-model timing number
for `SIM_EXPLANATION_*` appears anywhere in this document, by the same "never fake a benchmark
value" rule §7 states for everything else (SPEC §27).
