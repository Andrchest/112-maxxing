"""Process configuration.

All settings are read from the environment (and `.env` in local dev) with the `SIM_` prefix, per
D1/D8. `.env.example` documents every variable with a fake-but-shaped default value; no real secret
ever gets a default here.
"""

from __future__ import annotations

import secrets
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROCESS_INSTANCE_ID: str = secrets.token_hex(8)
"""This process's identity, drawn once at import.

`SimulationRunner` writes it into `lock:session:{id}:runner` (§40.6) and compares against it on
every refresh and release, so "the owning backend instance" is a real per-process value and two
instances on one machine can never mistake each other's lock for their own. `SIM_INSTANCE_ID`
overrides it when a deployment wants a stable, human-readable name.
"""


class Settings(BaseSettings):
    """Backend process configuration, sourced from environment variables prefixed `SIM_`."""

    model_config = SettingsConfigDict(env_prefix="SIM_", env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    jwt_secret: str
    #: Loopback by default (SPEC §41, "local operation"): the API is not exposed to the network
    #: unless a deployment says so. Ports 8000/8001 on the developer machine belong to another
    #: project, so the default is 8100 — see this repository's E7-A task report.
    api_host: str = "127.0.0.1"
    api_port: int = 8100
    #: D8's bearer-token lifetime. Twelve hours: longer than the longest training day, so a
    #: session is never interrupted by a re-login, and short enough that a leaked token expires.
    jwt_ttl_minutes: int = 720
    #: The Vite dev server (D12). The compose deployment serves the frontend from the same
    #: origin, so this list is a development affordance, not a production one.
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    #: Which `CallTransportStatus` adapter the composition root wires (D9).
    #: `"livekit"` arrives in E11; until then it raises a `NotImplementedError` naming that epic.
    call_transport: str = "fake"
    #: D7's "one task per ACTIVE session". API tests set it false and drive `tick_session`
    #: explicitly, so no background task can outlive a test.
    runner_enabled: bool = True
    data_dir: str = "data"
    require_inference_ready: bool = True
    sim_tick_ms: int = 500
    sim_runner_lock_ttl_s: int = 30
    sim_runner_lock_refresh_s: int = 10
    #: `IDEMPOTENCY_TTL_S` of §40.6: how long `idempotency:{user_id}:{client_command_id}` keeps
    #: the first response body of a command, so a retried `setCardField` is a no-op rather than a
    #: second revision. Losing the key only re-evaluates the command (§40.6), never corrupts it.
    idempotency_ttl_s: int = 300
    instance_id: str = Field(default_factory=lambda: _PROCESS_INSTANCE_ID)
    #: `WS_REPLAY_MAX_EVENTS` (§40.3 "Replay bounds"): rows per replay page. There is no upper
    #: bound on the total replayed — a client away for the whole session gets the whole session;
    #: this only bounds one page, so a long replay never blocks the event loop.
    ws_replay_max_events: int = 5000
    #: §40.2 `heartbeat`: "Every 15 seconds when no event was pushed."
    ws_heartbeat_s: int = 15
    #: §40.2 client→server frames: "more than 10 frames per second closes the socket (`4429`)".
    ws_max_frames_per_s: int = 10
    #: `SESSION_CACHE_TTL_S` (§40.6): the TTL of `session:{id}:last_seq_no` and
    #: `session:{id}:call_state`. Both are read caches; losing them costs one PostgreSQL read.
    session_cache_ttl_s: int = 3600
    model_profile: str = "DEV_3060TI"
    recording_retention_days: int = 30
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    llm_base_url: str
    # -- the voice turn path (HLD `50-voice-pipeline.md` §4.1, D9, SPEC §17) ------------------
    # SPEC §17: "Make this configuration, not a hard-coded magic value." Every key of §4.1's
    # table gets one `SIM_VOICE_*` variable; `app.application.voice.config.VoiceTurnConfig`
    # validates the ranges and the cross-field rules, and the `TurnDetector` reads nothing else.
    # TODO(E18): the active model profile's `voice_turn.*` block overlays this env block.
    # Profiles (`backend/app/config/profiles/*.yaml`, `60-inference-ops.md` §2) are E18's epic;
    # until one is loaded the env block is the whole of the configuration.
    voice_speech_start_threshold: float = 0.55
    voice_speech_end_threshold: float = 0.35
    voice_speech_start_min_ms: int = 96
    voice_endpoint_silence_ms: int = 300
    voice_pre_roll_ms: int = 300
    voice_barge_in_min_speech_ms: int = 120
    voice_max_turn_ms: int = 30000
    voice_min_turn_ms: int = 200
    voice_vad_frame_ms: int = 32
    voice_trailing_pad_ms: int = 100
    voice_outbound_queue_ms: int = 200
    voice_tts_chunk_ms: int = 20
    voice_partial_asr_enabled: bool = True
    voice_partial_interval_ms: int = 500
    voice_sample_rate: int = 16000
    #: `VOICE_JOIN_RETRY_MS` of §40.6: how often the backend re-publishes `voice:join` while a
    #: call is RINGING (D9, E11-B). The default is §40.6's, literally.
    voice_join_retry_ms: int = 2000
    #: How long the voice agent's `voice:health:{service}` heartbeat key lives (HLD 60 §4.3).
    voice_health_heartbeat_s: int = 5
    voice_health_ttl_s: int = 15
    # -- E12: which VAD and ASR the voice agent loads (`60-inference-ops.md` §1, SPEC §19) -----
    # SPEC §19: "Domain code must not depend on a specific model." These keys are the *only*
    # place a model is named; `voice_agent.providers` turns them into a port implementation and
    # nothing above that seam ever sees the value. `energy` + `fake` is the gate's selection
    # (D13); every model profile selects `silero` + `gigaam`.
    #: `energy` | `silero`.
    vad_provider: str = "energy"
    vad_model_path: str = "models/silero-vad/silero_vad.onnx"
    #: `fake` | `gigaam` | `faster_whisper`.
    asr_provider: str = "fake"
    #: GigaAM v3: `v3_e2e_ctc` (primary, emits punctuation) or `v3_ctc` (benchmarked). The
    #: version and the directory travel together — `v3_ctc` pairs with `models/gigaam-v3-ctc`.
    asr_model_version: str = "v3_e2e_ctc"
    asr_model_dir: str = "models/gigaam-v3-e2e_ctc"
    asr_device: str = "cuda"
    asr_compute_type: str = "float16"
    #: How long one `transcribe()` may take before the turn ends with `MODEL_ERROR{TIMEOUT}`
    #: (SPEC §42 item 14). §8 budgets 250 ms for ASR at RTF ≤ 0.08, so 4 s is "the model is
    #: wedged", not "the model is slow today".
    asr_timeout_ms: int = 4000
    #: A real Russian WAV the ASR warm-up transcribes (`60-inference-ops.md` §4.2: "a real RU
    #: WAV, not silence"). Empty means "synthesise one second of tone", which warms the graph
    #: without shipping an audio file the repository has no other use for.
    asr_warmup_sample_path: str = ""
    # -- E13: the local LLM — interpreter + (E13-B2) generator (`60-inference-ops.md` §1, D10,
    # SPEC §20-§22, §41) -------------------------------------------------------------------------
    #: `fake` | `llama_cpp`. `fake` is what `make gate` runs (D13); every model profile selects
    #: `llama_cpp`.
    llm_provider: str = "fake"
    llm_model_name: str = "Qwen3-4B"
    llm_n_ctx: int = 4096
    #: The local `models/*.gguf` path `LlamaCppClient`'s launcher (not this client itself, which
    #: only ever dials `llm_base_url`) and `make models-llm` agree on.
    llm_model_path: str = "models/Qwen3-4B-Q4_K_M.gguf"
    #: Compose-internal service names `validate_llm_base_url` (SPEC §41) accepts besides loopback.
    llm_allowed_internal_hosts: list[str] = Field(default_factory=lambda: ["llama-server"])
    #: §5.1/§5.3 interpreter call params not fixed by the HLD text itself.
    #: E13-B3, CHANGE item 4: 200 -> 138. Measured: with compact-JSON + GBNF-grammar output, the
    #: eval set's completion-token count across all 4 models run
    #: (`benchmarks/results/interpreter_eval/20260921T180708Z/`, n=148 calls) has p99 = 110.3
    #: tokens (max observed 132); 110.3 * 1.25 = 137.9, rounded up to 138. See this task's report.
    llm_interpreter_max_tokens: int = 138
    llm_interpreter_timeout_ms: int = 2500
    #: E13-B3, CHANGE item 1: GBNF `grammar` (generated, `app.application.dialogue.grammar`) when
    #: true (the default); `response_format=json_schema` when false. Both are enforced compact
    #: JSON on the wire; this only chooses the mechanism.
    llm_interpreter_use_grammar: bool = True
    #: §5.2/§5.3 caller-generator call params (E13-B2 reads these; E13-B1 only declares them so
    #: `.env.example` documents the whole `SIM_LLM_*` family in one place).
    #: E13-B4, CHANGE item 3: measured, not changed. The 42-case eval set's completion-token count
    #: across 3 real models (`benchmarks/results/caller_eval/`, n=126 calls, max_tokens=200
    #: headroom) has p99 = 167.5, but that number is inflated by 2 degenerate `SCHEMA_INVALID`
    #: completions from the smallest model that ran to the cap regardless of its size (garbage
    #: output, not genuine content — Qwen3.5-2B/4B never came close to 200 tokens on any of the 42
    #: cases). Excluding those 2: n=124, max=70, p99=57.5, `57.5 * 1.25 = 71.9` — already *below*
    #: 80. See this task's report; `80` is kept.
    llm_generator_max_tokens: int = 80
    llm_generator_timeout_ms: int = 3000
    llm_generator_temperature: float = 0.7
    llm_generator_top_p: float = 0.9
    #: E13-B4, CHANGE item 3: GBNF `grammar` (generated, `app.application.dialogue.grammar.
    #: build_caller_response_grammar`) when true (the default); `response_format=json_schema` when
    #: false — the same lever `llm_interpreter_use_grammar` is for the interpreter.
    llm_generator_use_grammar: bool = True
    # -- E14-A: the TTS stage (`60-inference-ops.md` §1, §2.1, D9, SPEC §18, §19, §25) --------
    # SPEC §19 again: the provider is the only place a TTS model is named, and nothing above
    # `voice_agent.providers.build_tts` ever sees the value. `fake` is what `make gate` runs
    # (D13); the GPU default and the CPU fallback are E14-B's providers.
    #: `fake` | `qwen3_tts` | `piper` — `SIM_TTS_PROVIDER`.
    tts_provider: str = "fake"
    #: The provider the whole utterance is retried on once after a failure (INV 14, §6/D9's
    #: "configured fallback"). `none` means "no retry": the turn then ends silent but complete,
    #: which is the gate's selection — a fallback that is itself a fake would make INV 14's
    #: second failure untestable.
    tts_fallback_provider: str = "none"
    #: `TtsVoiceSpec.voice_id` when a session's scenario has no `CallerProfile` to read it from.
    #: UNVERIFIED as a real voice id (`60-inference-ops.md` §10 open item 4) — it is a default,
    #: not a measured binding.
    tts_voice_id: str = "ru_female_1"
    #: `TtsVoiceSpec.speaking_rate`'s default; 1.0 is "the provider's own".
    tts_speaking_rate: float = 1.0
    #: How long one whole utterance may take before the turn ends with `MODEL_ERROR{TIMEOUT}`.
    #: §8 budgets 200 ms to the *first* chunk; this is "the provider is wedged", not "slow".
    tts_timeout_ms: int = 8000
    #: The tighter guard on §8 row 8 — first audio. A provider that has produced nothing after
    #: this long has already lost the turn's latency budget.
    tts_first_chunk_timeout_ms: int = 1500
    #: `split_for_tts`'s `max_unit_chars` (`app.application.voice.sentence_chunker`): the length
    #: above which a sentence is subdivided at clause separators so the first chunk of audio is
    #: not held hostage by a run-on sentence (§2.4, §8 lever 1).
    tts_max_unit_chars: int = 120
    # -- E14-B: the real TTS providers (OWNER DECISION: Qwen3-TTS GPU default; `PiperTTS` CPU
    # fallback). `voice_agent.providers.build_tts`/`build_tts_fallback` are the only readers.
    #: `Qwen3TTS`'s httpx client target — the standalone `workers/tts_qwen3` worker on loopback,
    #: never the LiveKit/compose-internal network (SPEC §41,
    #: `app.inference.tts.qwen3_tts.validate_tts_qwen3_base_url`).
    tts_qwen3_base_url: str = "http://127.0.0.1:8112"
    #: `SIM_TTS_QWEN3_MODEL_DIR` — the worker process (a separate venv/program, `workers/
    #: tts_qwen3`) reads this directly; the backend never opens the model file itself, only
    #: documents/validates the path exists when the profile requires it (E18).
    tts_qwen3_model_dir: str = "models/qwen3-tts"
    #: The vendor CustomVoice speaker `Qwen3TTS` falls back to when `TtsVoiceSpec.voice_id` is
    #: empty (recon §1.1: `"Serena" | "Ryan" | "Vivian" | "Aiden"` only — the generic
    #: `tts_voice_id` default above is not one of them and is rejected, not substituted, when a
    #: caller passes it explicitly; see E14-B's report, "HLD gaps").
    tts_qwen3_speaker: str = "Serena"
    #: `PiperTTS`'s `.onnx` voice file (+ sibling `.onnx.json`), `models/piper/` (gitignored),
    #: fetched by `make models-piper`.
    tts_piper_voice_path: str = "models/piper/ru_RU-irina-medium.onnx"
    # -- E13-B2: the caller prompt builder and the response validator (§5.2, §5.3, §7) --------
    #: §5.2's turn window: "the last 6 turns … but never drops below 4" (valid 4-6, SPEC §22).
    dialogue_window_turns: int = 6
    #: §7.1's character guard, which is also `CALLER_JSON_SCHEMA`'s `maxLength`.
    caller_max_chars: int = 400
    #: §7.1 names no sentence limit; SPEC §23's "ОДНОЙ короткой репликой" is what this bounds.
    #: See the HLD gap in `app.application.dialogue.validator`.
    caller_max_sentences: int = 3
    #: §5.3's `prompt_token_budget` — a hard refusal, not a truncation.
    caller_prompt_token_budget: int = 2700
    # -- E11-B: the LiveKit access tokens the backend mints (D9, `openapi.yaml`) ---------------
    #: `createVoiceToken` lifetime. Ten minutes: long enough to join a call that is still ringing,
    #: short enough that a leaked token is worthless. The token is re-minted, not refreshed.
    livekit_token_ttl_minutes: int = 10
    #: The URL a BROWSER dials, which is not always the one this process dials. Under
    #: `infra/docker-compose.yml` the backend and the voice-agent reach the SFU at its
    #: compose-internal name (`SIM_LIVEKIT_URL`, e.g. `ws://livekit:7880`) while the trainee's
    #: browser must be told a URL that resolves on their machine (`ws://localhost:7880`).
    #: `VoiceTokenResponse.livekit_url` carries this one; the readiness probe and the voice-agent
    #: keep using `livekit_url`. Empty (the default) means "they are the same", which is what a
    #: plain local run wants — see `livekit_browser_url`.
    livekit_public_url: str = ""

    # -- E16-B: the optional score-explanation LLM call (`60-inference-ops.md` §1, D11, SPEC §2,
    # §29, §41) -------------------------------------------------------------------------------
    # A second, independent `LLMClient` from the interpreter/generator's `SIM_LLM_*` family above:
    # this one is built and called by the BACKEND process itself (`app.inference.llm.
    # explanation_client.build_explanation_llm_client`), not the voice-agent worker, because
    # `generateReportExplanation` is a backend HTTP route, not a voice-agent turn-loop call (D9).
    #: `fake` | `llama_cpp`. `fake` is what `make gate` runs (D13); a model profile may select
    #: `llama_cpp` and point it at the same or a different local llama.cpp server than §5.1's.
    explanation_llm_provider: str = "fake"
    #: Loopback/compose-internal only (SPEC §41), validated at construction like `llm_base_url`.
    explanation_llm_base_url: str = "http://127.0.0.1:8080/v1"
    explanation_llm_model_name: str = "Qwen3-4B"
    #: One explanation is a few short paragraphs of prose, not a JSON turn — a smaller cap than
    #: the interpreter's/generator's is deliberate.
    explanation_max_tokens: int = 400
    #: Lower than the caller generator's 0.7 (§5.2): an explanation cites given numbers rather
    #: than improvising a persona, so R8 asks for a more deterministic register (DO item 1).
    explanation_temperature: float = 0.2
    explanation_timeout_ms: int = 8000

    @property
    def livekit_browser_url(self) -> str:
        """`SIM_LIVEKIT_PUBLIC_URL` when it is set, else `SIM_LIVEKIT_URL` (see that field)."""
        return self.livekit_public_url or self.livekit_url


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide, cached `Settings` instance."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment
