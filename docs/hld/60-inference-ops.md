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

The development machine is an **RTX 3060 Ti with 8 GB** of VRAM, of which roughly **5 GB is already
occupied by the owner's unrelated processes**. Those processes must never be killed, restarted or
paged out by anything this project does. The usable budget on the dev machine is therefore around
**3 GB**, not 8 GB, and it is not stable: the owner's usage moves.

Consequences, stated as rules rather than as measurements:

1. **`DEV_3060TI` does not attempt full GPU residency.** It runs the LLM with **partial GPU offload**
   (`--n-gpu-layers` set to a value that fits the measured free VRAM, not `-1`), TTS on **CPU**
   (`PiperTTS`), and VAD on **CPU** (`SileroVAD` via onnxruntime CPU EP). Only the LLM and the ASR
   model may hold GPU memory, and ASR may be moved to CPU by profile key if a measurement says it
   must be.
2. **The budget is declared, not inferred.** `DEV_3060TI` declares
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

Target files: `backend/app/config/profiles/DEV_3060TI.yaml`,
`backend/app/config/profiles/FINAL_3080TI_12GB.yaml`,
`backend/app/config/profiles/FINAL_3080TI_16GB.yaml`.
Selected by the env var `MODEL_PROFILE`; loaded and validated by
`backend/app/config/profile.py` into the Pydantic model `ModelProfile` (`extra="forbid"`).

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
| `llm.max_response_tokens` | int | 80 (SPEC §22) |
| `llm.interpreter_max_tokens` | int | 200 |
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
| `tts.max_chunk_ms` | int | 40 (D9) |
| `tts.fallback_provider` | str | provider used when the primary fails (SPEC §39) |
| `vad.provider` | str | `silero` \| `energy` |
| `vad.model_path` | str | onnx path (silero) |
| `vad.device` | str | `cpu` |
| `voice_turn.*` | — | the full `VoiceTurnConfig` of `50-voice-pipeline.md` §4.1 |
| `warmup.enabled` | bool | true in every real profile |
| `warmup.asr_sample_path` | str | short WAV used for the dummy ASR call |
| `warmup.llm_prompt` | str | tiny prompt for the dummy generation |
| `warmup.tts_text` | str | tiny text for the dummy synthesis |
| `warmup.timeout_ms` | int | per-service warm-up timeout |
| `latency_targets.p50_ms` | int | SPEC §27 target for this profile |
| `latency_targets.p95_ms` | int | SPEC §27 target for this profile |

### 2.2 `DEV_3060TI.yaml`

```yaml
profile_name: DEV_3060TI
description: >
  Development profile for an RTX 3060 Ti 8 GB whose memory is mostly occupied by unrelated
  processes that must never be killed. LLM runs with partial GPU offload; TTS and VAD run on CPU.

hardware:
  gpu_name_contains: "3060 Ti"
  gpu_total_vram_mb: 8192
  reserved_by_others_mb: 5120

vram_budget_mb: 2800
min_vram_margin_mb: 512
measured_peak_vram_mb: null      # UNVERIFIED — set by benchmarks/benchmark_vram.py
measured_at: null

llm:
  provider: llama_cpp
  model_name: Qwen3-4B
  model_path: /models/llm/Qwen3-4B-Q4_K_M.gguf
  quantization: Q4_K_M
  base_url: http://llama-server:8080/v1
  n_ctx: 4096
  n_gpu_layers: 20               # partial offload; raise only after a VRAM measurement
  n_batch: 512
  n_ubatch: 256
  parallel_slots: 2              # one interpreter call and one generation call in flight
  flash_attention: "on"
  kv_cache_type: q8_0
  max_response_tokens: 80
  interpreter_max_tokens: 200
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
  provider: piper                # lowest-risk TTS profile (SPEC §26), CPU only
  model_path: /models/tts/piper/ru_RU-model.onnx
  voice_id: ru_RU-default        # UNVERIFIED — pin a measured Russian Piper voice
  device: cpu
  output_sample_rate: 22050
  max_chunk_ms: 40
  fallback_provider: fake

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
  tts_chunk_ms: 40
  partial_asr_enabled: true
  partial_interval_ms: 500

warmup:
  enabled: true
  asr_sample_path: /models/warmup/warmup_ru.wav
  llm_prompt: "Скажи одно слово."
  tts_text: "Проверка."
  timeout_ms: 60000

latency_targets:
  p50_ms: 1500
  p95_ms: 2500
```

### 2.3 `FINAL_3080TI_12GB.yaml`

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
  max_response_tokens: 80
  interpreter_max_tokens: 200
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
  model_path: /models/tts/qwen3-tts-0.6b
  voice_id: ru_female_calm       # UNVERIFIED — pin a measured voice id
  device: cuda
  output_sample_rate: 24000
  max_chunk_ms: 40
  fallback_provider: piper

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
  tts_chunk_ms: 40
  partial_asr_enabled: true
  partial_interval_ms: 500

warmup:
  enabled: true
  asr_sample_path: /models/warmup/warmup_ru.wav
  llm_prompt: "Скажи одно слово."
  tts_text: "Проверка."
  timeout_ms: 60000

latency_targets:
  p50_ms: 1200
  p95_ms: 2000
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
4. **TTS** — `stream(warmup.tts_text, default voice)` drained to completion.

Each step records an `InferenceMetric` with `turn_id = NULL` and `request_id = "warmup:{stage}"`, so
warm-up cost is visible in the same table as everything else. Each step publishes its state
transition as it happens, so the UI shows progress rather than a single long NOT_READY.

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
  `POST /api/v1/admin/inference/clear-fatal` (instructor/admin) or by a clean warm-up after a manual
  restart.

`POST /api/v1/sessions/{id}/start` returns 503 `INFERENCE_NOT_READY` while any required service is
not READY and `REQUIRE_INFERENCE_READY=true` (default true; tests set it false explicitly) — D8.
The UI disables the start button from `/api/v1/health/ready`, satisfying SPEC §37's "the UI must not
allow a final demo session to begin while a required inference service reports not-ready".

### 4.4 GPU OOM → FATAL without touching session state (SPEC §39)

The rule: **an OOM changes health, never simulation state.** Concretely, in
`workers/voice_agent/health.py`:

1. Every model call is wrapped by `guard_inference(stage)`, which catches
   `torch.cuda.OutOfMemoryError`, `RuntimeError` whose message contains `out of memory`, and the
   llama-server HTTP responses that report an allocation failure.
2. On catch it: records the `InferenceMetric` with `status = "ERROR"`, `error_kind = "OOM"`;
   transitions that service to **FATAL** and publishes it (§4.3); emits
   `MODEL_ERROR {session_id, turn_id, stage, error_kind: "OOM", recoverable: false}` into
   `session_events`; and **returns the deterministic fallback for that stage** — the interpreter
   fallback (`UNINTELLIGIBLE`) or the validator fallback template
   (`50-voice-pipeline.md` §5.1, §7.8) — so the turn finishes with a spoken caller line where it can.
3. It does **not** call any session use case, does not abort the session, does not roll back the
   incident, does not clear the card, and does not touch `simulation_sessions.state`. The session
   stays ACTIVE; the trainee can keep filling the card; every event already written stays written
   (SPEC §42 test 14).
4. `torch.cuda.empty_cache()` is called once after the transition to FATAL, and no model is reloaded.
   Reloading into a fragmented, contended 8 GB card is how one OOM becomes a loop.
5. The instructor UI shows the FATAL banner; starting a **new** session is refused while FATAL holds.

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
| 11 | audio devices accessible | only when `--skip-audio-devices` is absent and `AUDIO_DEVICE_CHECK=true`: enumerate input devices via `sounddevice.query_devices()` and open the configured device at 16 kHz mono for 100 ms | the device opens; otherwise the row is `SKIP` |

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
| LiveKit temporary reconnect: session/domain state survives | `LiveKitCallTransport` surfaces `RECONNECTING`/`RECONNECTED` as `TransportEvent`s; `TurnPipeline` emits `TRANSPORT_DISCONNECTED` / `TRANSPORT_RECONNECTED`, cancels any in-flight playback as a non-barge-in cancellation (no `CALLER_UTTERANCE_INTERRUPTED`, since nobody interrupted), resets the `TurnDetector`, and resumes. The session stays ACTIVE; PostgreSQL state is untouched; the runner keeps ticking. A disconnect longer than `transport.reconnect_grace_s` (default 30) emits `CALL_ENDED {reason: "TRANSPORT_LOST"}` and leaves the session for the instructor to decide. | `TurnPipeline`, `LiveKitCallTransport` |
| GPU OOM: fatal inference health error, preserve session state | §4.4 above. | `workers/voice_agent/health.py` |
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
sub-suite. Run once per configured TTS provider so Qwen3-TTS 0.6B, Chatterbox Multilingual and Piper
are comparable (SPEC §25).

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

Run inside the `llama-server` compose service; `$MODEL_PROFILE` selects which line is used. Flags are
llama.cpp server flags; the exact set available depends on the build, so any flag that a given build
rejects is reported at start-up rather than silently dropped. **UNVERIFIED:** the precise flag
spelling for the pinned llama.cpp tag — pin a tag in `infra/docker-compose.yml` and confirm against
`llama-server --help` of that tag before first run.

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

## 9. Docker compose service notes

`infra/docker-compose.yml`, services named exactly as SPEC §36 / D1: `postgres`, `redis`, `livekit`,
`backend`, `frontend`, `llama-server`, `voice-agent`.

### `llama-server`

- Image: a pinned `ggml-org/llama.cpp` CUDA server tag — **pinned**, never `:latest`, because a flag
  change upstream silently alters the launch line of §8.
- `runtime: nvidia` / `deploy.resources.reservations.devices` with `capabilities: [gpu]`;
  `NVIDIA_VISIBLE_DEVICES` from `.env` so the dev machine can pin a device.
- Volumes: `${MODELS_DIR}:/models:ro`. Models are never baked into an image and never downloaded at
  start-up (SPEC §41: everything local).
- `command:` is `infra/scripts/llama-server-entrypoint.sh`, which reads `MODEL_PROFILE` and emits the
  §8 line. Keeping the flags in a script, not in compose YAML, is what lets the profile own them.
- Healthcheck: `curl -fsS http://localhost:8080/health`; `start_period` generous (model load on a
  partially offloaded 4B is minutes on a busy card), `retries` high, `interval: 10s`.
- No `ports:` mapping. Reachable only as `http://llama-server:8080` inside the network, which is
  exactly what `LlamaCppClient`'s loopback/compose-internal `base_url` validation expects.
- `restart: unless-stopped`.

### `voice-agent`

- Built from `workers/voice_agent/Dockerfile`; installs the uv workspace with the extras the profile
  needs (`asr-gigaam`, `vad-silero`, `tts-piper`, …) — heavy extras are image build args so the DEV
  image does not carry the GPU TTS stacks it will not use (D1).
- `runtime: nvidia` with the same device pinning; on DEV the GPU is used for the ASR model only,
  TTS and VAD run on CPU (§1), so `cpus`/`mem_limit` matter as much as the GPU reservation.
- `depends_on`: `redis` (service_started), `postgres` (service_healthy), `livekit`
  (service_started), `llama-server` (service_healthy). It tolerates llama-server being slow anyway —
  the warm-up polls (§4.2) — but the ordering keeps the logs readable.
- Volumes: `${MODELS_DIR}:/models:ro` and `${DATA_DIR}:/data` (recordings are written here and read
  by `backend` over the same mount, which is why both services mount it).
- Env: `MODEL_PROFILE`, `DATABASE_URL`, `REDIS_URL`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
  `LIVEKIT_API_SECRET`, `DATA_DIR`, `RECORDING_RETENTION_DAYS`, `REQUIRE_INFERENCE_READY`.
  All from `.env`; none in source (SPEC §41).
- `LIVEKIT_URL` is the URL a *server process* dials (compose-internal, e.g. `ws://livekit:7880`).
  `LIVEKIT_PUBLIC_URL` (E11) is the URL a *browser* dials, e.g. `ws://localhost:7880`; it is what
  `VoiceTokenResponse.livekit_url` carries, and it defaults to `LIVEKIT_URL` when unset. The
  readiness probe and the voice-agent always use `LIVEKIT_URL`.
- Healthcheck: `python -m voice_agent.cli health`, which returns 0 only when every
  `voice:health:{service}` key it owns is READY or WARMING — a FATAL service makes the container
  unhealthy and visible, without restarting it into the same OOM.
- `restart: unless-stopped`, but **no** automatic restart loop around a FATAL state: the health key
  `voice:health:fatal` survives a container restart (§4.3), so a restarted agent comes back FATAL
  until a human clears it.
- It publishes no port; it is a pure client of livekit, redis, postgres and llama-server.

Shared: every service gets `.env` via `env_file`, GPU services use the NVIDIA runtime, and the test
stack (`infra/docker-compose.test.yml`, ports 55432 / 56379, tmpfs) contains only `postgres` and
`redis` because the gate runs entirely on fake providers (D1, D13).

---

## 10. Open items for the manager

1. Every VRAM number in every profile is `null` and every profile is therefore **unmeasured**; the
   FINAL profiles are refused by `validate_vram_margin` until `benchmark_vram.py` has been run. That
   is the intended state, not an omission.
2. `DEV_3060TI.llm.n_gpu_layers: 20` and `vram_budget_mb: 2800` are **starting points chosen to be
   conservative on a card with ~3 GB free**, not measurements. They must be re-set from a
   `benchmark_vram.py` run before the demo.
3. The llama.cpp tag and the exact spelling of `--chat-template-kwargs` / `--flash-attn on` are
   UNVERIFIED against a pinned build (§8).
4. The Russian voice ids for Piper, Qwen3-TTS and Chatterbox are UNVERIFIED placeholders.
5. `--ctx-size` vs `--parallel` (§8, first note) is the one place this document had to choose a
   mechanism the frame did not name; it is listed for ratification in the task report.

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

`GigaAMProvider` (`backend/app/inference/asr/gigaam_provider.py`) loads the local directory with
`AutoModel.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True)` and
`HF_HUB_OFFLINE=1`, and never calls the checkpoint's own `transcribe()` — see that module's
docstring for the ffmpeg/pyannote reasons and for the long-audio window-splitting it does instead.
