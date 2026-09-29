"""Model profiles (SPEC §26, HLD `docs/hld/60-inference-ops.md` §2, D9).

"Create configuration profiles instead of editing code" (SPEC §26). A profile is a YAML file under
`backend/app/config/profiles/`, loaded and validated into `ModelProfile` (`extra="forbid"` on
every block, so a typo'd key is a load-time refusal, never a silently ignored one) and selected by
`Settings.model_profile` (env `SIM_MODEL_PROFILE`).

Two entry points other epics import (R1's committed-first-minutes interface — see the E18-A task
report):

* `active_profile(settings) -> ModelProfile` — `load_profile(settings.model_profile)`, the one
  place a caller needs to know the setting's name at all;
* `validate_vram_margin(profile) -> None` — HLD 60 §2.5's refusal rule, called once at process
  start-up (both the API container and the voice-agent) before any model is loaded.
  `ProfileRefused` is fatal: it is left to propagate out of start-up as an uncaught exception,
  which is what gives the process its non-zero exit code. It is never downgraded to a warning and
  no env var disables it (SPEC §26's "never choose a profile whose measured peak VRAM leaves
  essentially zero safety margin").

`apply_profile(settings, profile) -> Settings` (R3) is the third piece: it overlays the profile's
`llm`/`asr`/`tts`/`vad`/`voice_turn` values onto the *existing* `SIM_*` `Settings` fields they
correspond to, but only for a field the caller never set explicitly (env var, `.env`, or an
explicit constructor kwarg — see its own docstring for the precedence mechanism and exactly which
profile keys have no `Settings` counterpart and are read straight off `ModelProfile` instead).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    # pragma: no cover - import cycle guard only, matches app.application.voice.config
    from app.config.settings import Settings

__all__ = [
    "PROFILES_DIR",
    "TEMPO_EMOTION_KEYS",
    "TEMPO_VOICE_STYLE_KEYS",
    "AsrProfile",
    "HardwareProfile",
    "HealthProfile",
    "LatencyTargetsProfile",
    "LlmProfile",
    "ModelProfile",
    "ProfileRefused",
    "TtsProfile",
    "TtsSeedMode",
    "VadProfile",
    "VoiceTurnProfile",
    "VoipProfile",
    "WarmupProfile",
    "active_profile",
    "apply_profile",
    "load_profile",
    "validate_tempo_by_emotion",
    "validate_vram_margin",
]

logger = logging.getLogger(__name__)

#: `backend/app/config/profiles/` — resolved from this file's location, never the process cwd, so
#: `load_profile` works the same whether it is called from `make run-api`, a test, or a REPL.
PROFILES_DIR = Path(__file__).resolve().parent / "profiles"

_FINAL_PREFIX = "FINAL_"
_KNOWN_TTS_VARIANTS = ("0.6B", "1.7B")
#: I8 V0: the keys `tts.tempo_by_emotion` accepts — every `app.domain.enums.EmotionLabel` value
#: (all required when the table is given) and every `CallerVoiceStyle` value (optional). Literals,
#: not an import: `app.config` depends on nothing in `app` (a unit test pins them to the enums).
TEMPO_EMOTION_KEYS: tuple[str, ...] = (
    "CALM",
    "WORRIED",
    "FRIGHTENED",
    "PANICKED",
    "ANGRY",
    "CONFUSED",
    "APATHETIC",
)
TEMPO_VOICE_STYLE_KEYS: tuple[str, ...] = ("PAIN",)
#: I8 V0: `tts.seed_mode`. `off` — no seed is sent (the library's own random sampling, the
#: behaviour before I8); `derived` — a per-unit seed derived from the session's
#: `deterministic_seed`, the turn and the unit (I8 A1 §2.2; consumed from I8 V1).
TtsSeedMode = Literal["off", "derived"]


class ProfileRefused(Exception):
    """Fatal at process start-up (HLD 60 §2.5). Never caught and downgraded to a warning."""


class HardwareProfile(BaseModel):
    """`hardware.*` (HLD 60 §2.1) — reporting only; `preflight` (E18's CLI task) is the real check
    against the driver's reported name and free VRAM, not this block."""

    model_config = ConfigDict(extra="forbid")

    gpu_name_contains: str
    gpu_total_vram_mb: int
    reserved_by_others_mb: int


class LlmProfile(BaseModel):
    """`llm.*` (HLD 60 §2.1). Launch-flag fields (`n_gpu_layers`, `n_batch`, `n_ubatch`,
    `flash_attention`, `kv_cache_type`, `quantization`) have no `Settings` counterpart: the
    llama-server entrypoint script (E18-E) reads them straight off the loaded `ModelProfile`."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model_name: str
    model_path: str
    quantization: str
    base_url: str
    n_ctx: int
    n_gpu_layers: int
    n_batch: int
    n_ubatch: int
    parallel_slots: int
    flash_attention: str
    kv_cache_type: str
    max_response_tokens: int
    interpreter_max_tokens: int
    request_timeout_ms: int
    thinking_enabled: bool

    @field_validator("thinking_enabled")
    @classmethod
    def _thinking_must_stay_off(cls, value: bool) -> bool:
        """SPEC §22: thinking is never enabled for the interpreter/generator calls."""
        if value:
            raise ValueError("llm.thinking_enabled must be false (SPEC §22)")
        return value


class AsrProfile(BaseModel):
    """`asr.*` (HLD 60 §2.1)."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model_version: str
    model_path: str
    device: str
    compute_type: str
    sample_rate: int


class TtsProfile(BaseModel):
    """`tts.*` (HLD 60 §2.1) plus the `fallback_*` triple and `model_variant` the DEV YAML already
    carries (HLD 60 §2.2) — `extra="forbid"` means every key a real profile file uses must be
    declared here, not just the ones in the §2.1 summary table.

    `model_variant` is ADDITIVE (E18-A, R2): `"0.6B" | "1.7B" | None`, maps to
    `SIM_TTS_QWEN3_MODEL` — an env var the separate `workers/tts_qwen3` worker process (its own
    venv, `os.environ.get("SIM_TTS_QWEN3_MODEL", ...)`) reads directly. E20-E R11:
    `apply_profile` now overlays it onto `Settings.tts_model_variant`, which is aliased onto that
    SAME env name (`config/settings.py`) — the backend/voice-agent side of the process and the
    standalone worker read one name, not two.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    model_path: str
    voice_id: str
    device: str
    output_sample_rate: int
    max_chunk_ms: int
    fallback_provider: str
    fallback_model_path: str | None = None
    fallback_voice_id: str | None = None
    fallback_output_sample_rate: int | None = None
    model_variant: str | None = None
    #: ADDITIVE (E20-G/G6). Logical -> native voice table for THIS profile's PRIMARY `provider`:
    #: the scenario's `caller_profile.voice_id` is a logical casting decision (HLD 30) and only the
    #: profile knows what a provider calls its voices. Overlaid onto `Settings.tts_voice_map`.
    voice_map: dict[str, str] = Field(default_factory=dict)
    #: ADDITIVE (E20-G/G6). The provider-native voice every unmapped logical id resolves to;
    #: `None` means "`voice_id` above". Overlaid onto `Settings.tts_default_voice`.
    default_voice: str | None = None
    #: ADDITIVE (E20-I). The speech sink's guard on the FIRST audio chunk of one unit, and on every
    #: later pull (`Settings.tts_first_chunk_timeout_ms` / `tts_timeout_ms`). `None` keeps the
    #: Settings defaults (1500 / 8000 ms, sized for a streaming provider). A whole-utterance
    #: provider (Qwen3-TTS: `qwen_tts` has no streaming API) produces its first chunk only when the
    #: whole unit is synthesised, so its profile MUST size these from its measured first-audio
    #: distribution or every turn is a guaranteed `MODEL_ERROR{TIMEOUT}` (E20-I, a silent caller).
    first_chunk_timeout_ms: int | None = None
    timeout_ms: int | None = None
    #: ADDITIVE (I8 V0). `split_for_tts`'s unit length for this profile, overlaid onto
    #: `Settings.tts_max_unit_chars`; `None` keeps the Settings default (120). The owner's lab
    #: found 60-80-character units keep Qwen3-TTS from degenerating on long segments.
    max_unit_chars: int | None = Field(default=None, ge=20, le=400)
    #: ADDITIVE (I8 V0). Silence between two synthesised units, overlaid onto
    #: `Settings.tts_inter_unit_pause_ms`; `None` keeps the Settings default (0 = none). Consumed
    #: by the chunked stream from I8 V1.
    inter_unit_pause_ms: int | None = Field(default=None, ge=0, le=1000)
    #: ADDITIVE (I8 V0). Post-synthesis tempo factor per caller emotion (and per scenario voice
    #: style), overlaid onto `Settings.tts_tempo_by_emotion`. Empty = no tempo change. When given,
    #: every `EmotionLabel` must have a factor. Consumed by the Qwen3-TTS adapter from I8 V1.
    tempo_by_emotion: dict[str, float] = Field(default_factory=dict)
    #: ADDITIVE (I8 V0). How the per-unit synthesis seed is chosen (`TtsSeedMode`), overlaid onto
    #: `Settings.tts_seed_mode`; `None` keeps the Settings default (`off`). Consumed from I8 V1.
    seed_mode: TtsSeedMode | None = None

    @field_validator("tempo_by_emotion")
    @classmethod
    def _complete_tempo_table(cls, value: dict[str, float]) -> dict[str, float]:
        return validate_tempo_by_emotion(value, what="tts.tempo_by_emotion")

    @field_validator("model_variant")
    @classmethod
    def _known_variant(cls, value: str | None) -> str | None:
        if value is not None and value not in _KNOWN_TTS_VARIANTS:
            raise ValueError(
                f"tts.model_variant={value!r} must be one of {_KNOWN_TTS_VARIANTS} or null"
            )
        return value


def validate_tempo_by_emotion(value: dict[str, float], *, what: str) -> dict[str, float]:
    """I8 V0: an empty table, or one factor in `[0.5, 2.0]` for every `EmotionLabel` (plus, if
    wanted, a `CallerVoiceStyle`) and no other key. Shared by `TtsProfile` and `Settings`."""
    if not value:
        return value
    allowed = set(TEMPO_EMOTION_KEYS) | set(TEMPO_VOICE_STYLE_KEYS)
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{what}: unknown key(s) {unknown}; allowed {sorted(allowed)}")
    missing = [key for key in TEMPO_EMOTION_KEYS if key not in value]
    if missing:
        raise ValueError(f"{what}: every emotion needs a factor; missing {missing}")
    out_of_range = sorted(key for key, factor in value.items() if not 0.5 <= factor <= 2.0)
    if out_of_range:
        raise ValueError(f"{what}: factor(s) outside [0.5, 2.0] for {out_of_range}")
    return value


class VadProfile(BaseModel):
    """`vad.*` (HLD 60 §2.1)."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model_path: str
    device: str


class VoiceTurnProfile(BaseModel):
    """`voice_turn.*` (HLD 60 §2.1): the full `VoiceTurnConfig` of `50-voice-pipeline.md` §4.1,
    overlaid onto the matching `SIM_VOICE_*` `Settings` fields by `apply_profile` (R3).

    `reconnect_grace_s` is ADDITIVE (E18-A, R6/DO item 1): HLD 60 §6 row 5 / SPEC §39 item 5's
    LiveKit-reconnect timeout. The timer itself lives in the application pipeline (E18-C); this is
    only where the number is declared and overlaid, same as every other `voice_turn.*` key.
    """

    model_config = ConfigDict(extra="forbid")

    speech_start_threshold: float
    speech_end_threshold: float
    speech_start_min_ms: int
    endpoint_silence_ms: int
    pre_roll_ms: int
    barge_in_min_speech_ms: int
    max_turn_ms: int
    min_turn_ms: int
    vad_frame_ms: int
    outbound_queue_ms: int
    tts_chunk_ms: int
    partial_asr_enabled: bool
    partial_interval_ms: int
    reconnect_grace_s: int = Field(default=30, ge=0)


class WarmupProfile(BaseModel):
    """`warmup.*` (HLD 60 §2.1, §4.2). Read straight off `ModelProfile` by the voice-agent's
    warm-up sequence (already built, `workers/voice_agent/voice_agent/main.py`) — no `Settings`
    counterpart."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    asr_sample_path: str
    llm_prompt: str
    tts_text: str
    timeout_ms: int


class LatencyTargetsProfile(BaseModel):
    """`latency_targets.*` (HLD 60 §2.1, SPEC §27). Read by the report/benchmark code that
    compares a measured latency against the active profile's target — no `Settings` counterpart."""

    model_config = ConfigDict(extra="forbid")

    p50_ms: int
    p95_ms: int


class VoipProfile(BaseModel):
    """`voip.*` (I3 E6f, HLD 80 §80.8.3). Read straight off `ModelProfile` by report/audit code —
    no `Settings` counterpart, no provider reads it. Every field is `None` until
    `benchmarks/benchmark_voip.py` actually measures it (SPEC §27's "no number a script did not
    produce"); this block exists so that measured number, once it exists, has one committed home
    instead of living only in `docs/benchmarks/voip.md` prose."""

    model_config = ConfigDict(extra="forbid")

    one_way_delay_ms_p50: float | None = None
    one_way_delay_ms_p95: float | None = None
    concurrent_calls_measured: int | None = None


class HealthProfile(BaseModel):
    """ADDITIVE (E18-A, R1/DO item 1): HLD 60 §4.1's `health.failure_threshold` /
    `health.rewarm_interval_s`, read directly off `ModelProfile` by
    `workers/voice_agent/voice_agent/health.py` (E18-C's state machine) — no `SIM_*`/`Settings`
    counterpart exists, so `apply_profile` does not touch either field."""

    model_config = ConfigDict(extra="forbid")

    failure_threshold: int = Field(default=3, ge=1)
    rewarm_interval_s: int = Field(default=30, ge=1)


class ModelProfile(BaseModel):
    """The full profile (HLD 60 §2.1). `extra="forbid"` at every level: an unknown key anywhere in
    the file is a `pydantic.ValidationError` at `load_profile`, not a silently ignored one."""

    model_config = ConfigDict(extra="forbid")

    profile_name: str
    description: str
    hardware: HardwareProfile
    vram_budget_mb: int
    min_vram_margin_mb: int
    measured_peak_vram_mb: int | None = None
    measured_at: date | None = None
    llm: LlmProfile
    asr: AsrProfile
    tts: TtsProfile
    vad: VadProfile
    voice_turn: VoiceTurnProfile
    warmup: WarmupProfile
    latency_targets: LatencyTargetsProfile
    health: HealthProfile = Field(default_factory=HealthProfile)
    voip: VoipProfile = Field(default_factory=VoipProfile)


def load_profile(name: str) -> ModelProfile:
    """Load and validate `backend/app/config/profiles/{name}.yaml`.

    Raises `ProfileRefused` when the file does not exist or its `profile_name` does not match the
    filename; raises the underlying `pydantic.ValidationError` for anything else malformed (an
    unknown key, a wrong type, a missing required key, `llm.thinking_enabled: true`, ...) —
    `extra="forbid"` is what makes a typo a load-time refusal.
    """
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.is_file():
        raise ProfileRefused(
            f"model profile {name!r} has no file at {path} "
            f"(SIM_MODEL_PROFILE names a profile that does not exist)"
        )
    with path.open("r", encoding="utf-8") as handle:
        data: Any = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ProfileRefused(f"model profile {name!r}: {path} is not a YAML mapping")
    profile = ModelProfile(**data)
    if profile.profile_name != name:
        raise ProfileRefused(
            f"model profile file {path} declares profile_name={profile.profile_name!r}, which "
            f"does not match its filename {name!r}"
        )
    return profile


def active_profile(settings: Settings) -> ModelProfile:
    """`load_profile(settings.model_profile)` — the active profile for this process."""
    return load_profile(settings.model_profile)


def validate_vram_margin(profile: ModelProfile) -> None:
    """HLD 60 §2.5's refusal rule, verbatim:

    ```
    margin_mb = vram_budget_mb - measured_peak_vram_mb

    if measured_peak_vram_mb is None:
        if profile_name.startswith("FINAL_"):
            raise ProfileRefused(...)
        else:
            log.warning(...)
    elif margin_mb < min_vram_margin_mb:
        raise ProfileRefused(...)
    ```

    Called once at start-up, in the backend and in the voice-agent, before any model is loaded.
    """
    if profile.measured_peak_vram_mb is None:
        if profile.profile_name.startswith(_FINAL_PREFIX):
            raise ProfileRefused(
                f"FINAL profile {profile.profile_name} has no measured_peak_vram_mb; run "
                f"benchmarks/benchmark_vram.py and record the result"
            )
        logger.warning(
            "DEV profile %s is unmeasured; VRAM margin cannot be checked", profile.profile_name
        )
        return
    margin_mb = profile.vram_budget_mb - profile.measured_peak_vram_mb
    if margin_mb < profile.min_vram_margin_mb:
        raise ProfileRefused(
            f"profile {profile.profile_name}: measured peak {profile.measured_peak_vram_mb} MB "
            f"leaves margin {margin_mb} MB, below min_vram_margin_mb {profile.min_vram_margin_mb} "
            f"MB — SPEC §26 forbids it"
        )


#: `TtsProfile.provider` values with a real, distinct `Settings` field for their model path/voice
#: id (`workers/voice_agent/voice_agent/providers.py`'s `TTS_QWEN3`/`TTS_PIPER`, repeated here as
#: literals rather than imported — `app.config` must not depend on `voice_agent`).
_TTS_QWEN3_PROVIDER = "qwen3_tts"
_TTS_PIPER_PROVIDER = "piper"


#: `apply_profile`'s field mapping: `Settings` attribute name -> `ModelProfile` accessor. Every
#: profile key with an existing `SIM_*`/`Settings` counterpart a provider actually reads today is
#: listed here (E18-A2, R3's "every existing field they have a counterpart for"); a profile key
#: left out — `hardware.*`, `warmup.*`, `latency_targets.*`, llama-server launch flags
#: (`n_gpu_layers`/`n_batch`/`n_ubatch`/`flash_attention`/`kv_cache_type`/`quantization`),
#: `asr.sample_rate`, `tts.max_chunk_ms`, and `llm.thinking_enabled` — has **no** `Settings` field
#: today and no provider constructor reads one; each is read straight off `ModelProfile` by
#: whichever process needs it (preflight, the warm-up sequence, the llama-server entrypoint) or,
#: for `thinking_enabled`, refused outright at profile load by `LlmProfile`'s own validator. See
#: the E18-A task report's "HLD gaps" (and E18-A2's addendum) for the reasoning behind each
#: omission. `tts.device`/`output_sample_rate`, `tts.model_variant` and `vad.device` USED to be on
#: this list too (E18-A2's ruling that a field is added only when a provider reads it today); E20-E
#: R11 added `Settings.tts_device`/`tts_output_sample_rate`/`tts_model_variant`/`vad_device` and
#: they are overlaid below like every other field.
def _direct_mapping(profile: ModelProfile) -> dict[str, Any]:
    mapping: dict[str, Any] = {
        "llm_provider": profile.llm.provider,
        "llm_model_name": profile.llm.model_name,
        "llm_model_path": profile.llm.model_path,
        "llm_base_url": profile.llm.base_url,
        "llm_n_ctx": profile.llm.n_ctx,
        "llm_interpreter_max_tokens": profile.llm.interpreter_max_tokens,
        "llm_generator_max_tokens": profile.llm.max_response_tokens,
        # E18-A2: llm.request_timeout_ms has no finer-grained interpreter/generator split of its
        # own in ModelProfile, so it overlays BOTH existing Settings timeout fields (ruling R3).
        "llm_interpreter_timeout_ms": profile.llm.request_timeout_ms,
        "llm_generator_timeout_ms": profile.llm.request_timeout_ms,
        "asr_provider": profile.asr.provider,
        "asr_model_version": profile.asr.model_version,
        "asr_model_dir": profile.asr.model_path,
        "asr_device": profile.asr.device,
        "asr_compute_type": profile.asr.compute_type,
        "tts_provider": profile.tts.provider,
        "tts_fallback_provider": profile.tts.fallback_provider,
        # E20-E R11: previously read straight off ModelProfile only (no Settings counterpart).
        "tts_device": profile.tts.device,
        "tts_output_sample_rate": profile.tts.output_sample_rate,
        "tts_model_variant": profile.tts.model_variant,
        # E20-G R/G6: the logical -> native voice table and its default. `default_voice` falls back
        # to the profile's own `tts.voice_id`, which is already the provider-native id every
        # profile names (a vendor speaker for qwen3_tts, a Piper voice for piper) — so a profile
        # that declares neither new key behaves exactly as before.
        "tts_voice_map": dict(profile.tts.voice_map),
        "tts_default_voice": profile.tts.default_voice or profile.tts.voice_id,
        "vad_provider": profile.vad.provider,
        "vad_model_path": profile.vad.model_path,
        "vad_device": profile.vad.device,
        # voice_turn.* -> the SIM_VOICE_* fields VoiceTurnConfig is built from (R3).
        "voice_speech_start_threshold": profile.voice_turn.speech_start_threshold,
        "voice_speech_end_threshold": profile.voice_turn.speech_end_threshold,
        "voice_speech_start_min_ms": profile.voice_turn.speech_start_min_ms,
        "voice_endpoint_silence_ms": profile.voice_turn.endpoint_silence_ms,
        "voice_pre_roll_ms": profile.voice_turn.pre_roll_ms,
        "voice_barge_in_min_speech_ms": profile.voice_turn.barge_in_min_speech_ms,
        "voice_max_turn_ms": profile.voice_turn.max_turn_ms,
        "voice_min_turn_ms": profile.voice_turn.min_turn_ms,
        "voice_vad_frame_ms": profile.voice_turn.vad_frame_ms,
        "voice_outbound_queue_ms": profile.voice_turn.outbound_queue_ms,
        "voice_tts_chunk_ms": profile.voice_turn.tts_chunk_ms,
        "voice_partial_asr_enabled": profile.voice_turn.partial_asr_enabled,
        "voice_partial_interval_ms": profile.voice_turn.partial_interval_ms,
        "voice_reconnect_grace_s": profile.voice_turn.reconnect_grace_s,
    }
    # E18-A2: tts.model_path and tts.voice_id each map to a DIFFERENT Settings field depending on
    # which TTS provider is actually selected — Qwen3TTS and PiperTTS are keyed differently
    # (a base model directory + vendor speaker name vs. a single .onnx voice file, which ignores
    # voice_id entirely, `backend/app/inference/tts/piper_tts.py`). Mapping either field
    # unconditionally would silently write the wrong provider's Settings field.
    if profile.tts.provider == _TTS_QWEN3_PROVIDER:
        mapping["tts_qwen3_model_dir"] = profile.tts.model_path
        mapping["tts_qwen3_speaker"] = profile.tts.voice_id
    elif profile.tts.provider == _TTS_PIPER_PROVIDER:
        mapping["tts_piper_voice_path"] = profile.tts.model_path
        mapping["tts_voice_id"] = profile.tts.voice_id
    # E20-I: a Piper FALLBACK behind a Qwen3-TTS primary needs its voice file too. Without this
    # the fallback kept `Settings`' host-relative default (`models/piper/...`), which does not
    # exist inside the voice-agent container, so INV 14's retry had no warmed provider.
    if (
        profile.tts.provider != _TTS_PIPER_PROVIDER
        and profile.tts.fallback_provider == _TTS_PIPER_PROVIDER
        and profile.tts.fallback_model_path
    ):
        mapping["tts_piper_voice_path"] = profile.tts.fallback_model_path
    if profile.tts.first_chunk_timeout_ms is not None:
        mapping["tts_first_chunk_timeout_ms"] = profile.tts.first_chunk_timeout_ms
    if profile.tts.timeout_ms is not None:
        mapping["tts_timeout_ms"] = profile.tts.timeout_ms
    # I8 V0: overlaid only when the profile names them, so a profile without the keys keeps the
    # Settings defaults (today's behaviour) exactly.
    if profile.tts.max_unit_chars is not None:
        mapping["tts_max_unit_chars"] = profile.tts.max_unit_chars
    if profile.tts.inter_unit_pause_ms is not None:
        mapping["tts_inter_unit_pause_ms"] = profile.tts.inter_unit_pause_ms
    if profile.tts.tempo_by_emotion:
        mapping["tts_tempo_by_emotion"] = dict(profile.tts.tempo_by_emotion)
    if profile.tts.seed_mode is not None:
        mapping["tts_seed_mode"] = profile.tts.seed_mode
    mapping["tts_warmup_timeout_ms"] = profile.warmup.timeout_ms
    return mapping


def apply_profile(settings: Settings, profile: ModelProfile) -> Settings:
    """Overlay `profile` onto `settings`, field by field, without disturbing a field the caller
    set explicitly (R3's precedence: defaults < profile < an explicitly-set `SIM_*` var).

    Precedence is decided per field via `settings.model_fields_set`: `pydantic-settings` only adds
    a field name to that set when some source — an environment variable, `.env`, or an explicit
    constructor keyword argument — actually supplied a value for it; a field left at its class
    default is absent from the set. So a field present in `model_fields_set` was set on purpose
    and is left untouched here, and everything else is free for the profile to overlay. This is
    what keeps `make gate`'s `SIM_TTS_PROVIDER=fake` (and every other explicit gate override)
    working unchanged no matter which profile `SIM_MODEL_PROFILE` names, and lets an operator
    override one knob without forking a whole profile file.

    Used identically by the API container (`app.api.container.build_container`) and the
    voice-agent (`voice_agent.wiring.VoiceAgentDeps.build`) — one function, so the two processes
    can never overlay a profile two different ways.
    """
    fields_set = settings.model_fields_set
    update = {
        field: value for field, value in _direct_mapping(profile).items() if field not in fields_set
    }
    if not update:
        return settings
    return settings.model_copy(update=update)
