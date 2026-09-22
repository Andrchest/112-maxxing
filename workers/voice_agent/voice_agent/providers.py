"""Provider selection for the voice agent (`60-inference-ops.md` §1, D1, D13).

One function per capability, and each one is a flat branch on the `SIM_*` setting that names the
provider. Two rules shape them:

* **The heavy import is inside the branch.** `torch`, `onnxruntime`, `faster_whisper` and the
  rest are optional extras (D1); `import voice_agent.providers` must work in a plain dev venv
  with none of them installed, or `make gate` would need a GPU. The fake and energy branches
  therefore import eagerly (they have nothing to defer) and every real branch imports where it is
  selected.
* **An unknown provider is refused, not defaulted.** A typo in `SIM_ASR_PROVIDER` that silently
  fell back to the fake would mean a training session run against a scripted transcript, which is
  worse than a process that does not start.

The gate's selection is `SIM_VAD_PROVIDER=energy` + `SIM_ASR_PROVIDER=fake` (D13); every model
profile selects `silero` + `gigaam` (§10).

**Every model path goes through `host_model_path` (E20 R15).** A profile names container paths
(`/models/vad/silero_vad.onnx`), which is where compose mounts them and where a host run has
nothing at all: before E20 a host-run agent opened those paths verbatim, every warm-up raised
`ModelNotAvailableError`, all four components went FATAL and the agent served no call while
reporting itself healthy (E19-E2/E3, measured). `app.config.model_paths.resolve_model_path` maps a
profile path onto `SIM_MODELS_ROOT` — `/models` by default, so compose is unchanged — and it is the
same mapping the five benchmark scripts use, not a second copy of it.
"""

from __future__ import annotations

from app.application.ports.asr import ASRProvider
from app.application.ports.llm import LLMClient
from app.application.ports.tts import TTSProvider
from app.application.ports.vad import VADProvider
from app.application.voice.config import VoiceTurnConfig, voice_turn_config_from_settings
from app.config.model_paths import host_model_path
from app.config.settings import Settings

__all__ = [
    "ASR_FAKE",
    "ASR_FASTER_WHISPER",
    "ASR_GIGAAM",
    "LLM_FAKE",
    "LLM_LLAMA_CPP",
    "TTS_FAKE",
    "TTS_NONE",
    "TTS_PIPER",
    "TTS_QWEN3",
    "VAD_ENERGY",
    "VAD_SILERO",
    "build_asr",
    "build_llm",
    "build_tts",
    "build_tts_fallback",
    "build_vad",
]

#: `SIM_VAD_PROVIDER` values (§1). `energy` is the gate's and the documented fallback.
VAD_ENERGY = "energy"
VAD_SILERO = "silero"

#: `SIM_ASR_PROVIDER` values (§1). `gigaam` is every profile's; `fake` is the gate's.
ASR_FAKE = "fake"
ASR_GIGAAM = "gigaam"
ASR_FASTER_WHISPER = "faster_whisper"

#: `SIM_LLM_PROVIDER` values (E13, D10). `llama_cpp` is every profile's; `fake` is the gate's.
LLM_FAKE = "fake"
LLM_LLAMA_CPP = "llama_cpp"

#: `SIM_TTS_PROVIDER` / `SIM_TTS_FALLBACK_PROVIDER` values (E14-A/E14-B, D9). `qwen3_tts` is the
#: OWNER DECISION's GPU default for every profile incl. `DEV_3060TI`; `piper` is the CPU fallback;
#: `fake` is the gate's provider (D13). `none` is `SIM_TTS_FALLBACK_PROVIDER`-only: "no fallback".
TTS_FAKE = "fake"
TTS_QWEN3 = "qwen3_tts"
TTS_PIPER = "piper"
TTS_NONE = "none"


def build_vad(settings: Settings, config: VoiceTurnConfig | None = None) -> VADProvider:
    """The `VADProvider` named by `SIM_VAD_PROVIDER`.

    `config` is optional so that a caller which already built the turn config does not build a
    second one; without it the config is loaded from the same `Settings`, which is what makes the
    single-argument form of this factory meaningful.
    """
    resolved = config or voice_turn_config_from_settings(settings)
    provider = settings.vad_provider
    if provider == VAD_ENERGY:
        from app.inference.vad.energy_vad import EnergyVAD

        return EnergyVAD(
            frame_samples=resolved.frame_samples, required_sample_rate=resolved.sample_rate
        )
    if provider == VAD_SILERO:
        # Lazy: `onnxruntime` is the `vad-silero` extra.
        from app.inference.vad.silero_vad import SileroVAD

        return SileroVAD(
            model_path=host_model_path(settings.vad_model_path, settings.models_root),
            threshold_hint=resolved.speech_start_threshold,
        )
    raise ValueError(
        f"SIM_VAD_PROVIDER={provider!r} is not a VAD provider; use {VAD_ENERGY!r} or {VAD_SILERO!r}"
    )


def build_asr(settings: Settings) -> ASRProvider:
    """The `ASRProvider` named by `SIM_ASR_PROVIDER` (§1, SPEC §19)."""
    provider = settings.asr_provider
    if provider == ASR_FAKE:
        from app.inference.asr.fake_asr import FakeASR

        return FakeASR()
    if provider == ASR_GIGAAM:
        # Lazy: `gigaam` + `torch` are the `asr-gigaam` extra.
        from app.inference.asr.gigaam_provider import GigaAMProvider

        return GigaAMProvider(
            model_dir=host_model_path(settings.asr_model_dir, settings.models_root),
            model_version=settings.asr_model_version,
            device=settings.asr_device,
            compute_type=settings.asr_compute_type,
        )
    if provider == ASR_FASTER_WHISPER:
        # Lazy: `faster-whisper` is the `asr-whisper` extra.
        from app.inference.asr.faster_whisper_provider import FasterWhisperProvider

        return FasterWhisperProvider(
            model_path=host_model_path(settings.asr_model_dir, settings.models_root),
            device=settings.asr_device,
            compute_type=settings.asr_compute_type,
        )
    raise ValueError(
        f"SIM_ASR_PROVIDER={provider!r} is not an ASR provider; "
        f"use {ASR_FAKE!r}, {ASR_GIGAAM!r} or {ASR_FASTER_WHISPER!r}"
    )


def build_llm(settings: Settings) -> LLMClient:
    """The `LLMClient` named by `SIM_LLM_PROVIDER` (E13, D10, SPEC §41).

    `llama_cpp` validates `SIM_LLM_BASE_URL` at construction (loopback/compose-internal only,
    `validate_llm_base_url`) — a misconfigured host is a start-up error here, not a runtime one.
    """
    provider = settings.llm_provider
    if provider == LLM_FAKE:
        from app.inference.llm.fake_llm import FakeLLM

        return FakeLLM()
    if provider == LLM_LLAMA_CPP:
        from app.inference.llm.llama_cpp_client import LlamaCppClient

        return LlamaCppClient(
            base_url=settings.llm_base_url,
            model_name=settings.llm_model_name,
            n_ctx=settings.llm_n_ctx,
            default_timeout_ms=settings.llm_interpreter_timeout_ms,
            allowed_internal_hosts=settings.llm_allowed_internal_hosts,
        )
    raise ValueError(
        f"SIM_LLM_PROVIDER={provider!r} is not an LLM provider; "
        f"use {LLM_FAKE!r} or {LLM_LLAMA_CPP!r}"
    )


def _build_named_tts(provider: str, settings: Settings, *, primary: bool = True) -> TTSProvider:
    """The `TTSProvider` named by `provider` — the shared branch `build_tts`/`build_tts_fallback`
    both dispatch through, so a provider name always means the same construction regardless of
    which of the two slots (primary/fallback) it fills (E14-B).

    `primary` selects who gets the profile's logical -> native voice table (E20-G/G6):
    `tts.voice_map`/`tts.default_voice` describe the profile's PRIMARY provider, and a
    `default_voice` naming a Qwen3-TTS vendor speaker is meaningless to a Piper fallback. The
    fallback therefore resolves against its own natural default (its loaded voice file), which is
    exactly what the ruling's "`default_voice` = the downloaded ru_RU-irina-medium" asks for.
    """
    voice_map = settings.tts_voice_map if primary else None
    default_voice = settings.tts_default_voice if primary else None
    if provider == TTS_FAKE:
        from app.inference.tts.fake_tts import FakeTTS

        return FakeTTS()
    if provider == TTS_QWEN3:
        # Lazy: this only imports `httpx` (a hard dependency already) — never `qwen-tts`/
        # `torch==2.14.0`, which live in the separate `workers/tts_qwen3` worker process/venv.
        from app.inference.tts.qwen3_tts import Qwen3TTS

        return Qwen3TTS(
            base_url=settings.tts_qwen3_base_url,
            speaker=settings.tts_qwen3_speaker,
            timeout_ms=settings.tts_timeout_ms,
            warmup_timeout_ms=settings.tts_warmup_timeout_ms,
            voice_map=voice_map,
            default_voice=default_voice,
        )
    if provider == TTS_PIPER:
        # Lazy: `piper-tts` is the `tts-piper` extra.
        from app.inference.tts.piper_tts import PiperTTS

        return PiperTTS(
            voice_path=host_model_path(settings.tts_piper_voice_path, settings.models_root),
            voice_map=voice_map,
            default_voice=default_voice,
        )
    raise ValueError(
        f"{provider!r} is not a TTS provider; use {TTS_FAKE!r}, {TTS_QWEN3!r} or {TTS_PIPER!r}"
    )


def build_tts(settings: Settings) -> TTSProvider:
    """The primary `TTSProvider` named by `SIM_TTS_PROVIDER` (E14-A/E14-B, D9, SPEC §18, §19).

    `qwen3_tts` is an `httpx` client of the standalone `workers/tts_qwen3` worker process
    (`SIM_TTS_QWEN3_BASE_URL`, validated loopback/compose-internal at construction, SPEC §41);
    `piper` runs in-process on CPU. Neither is imported until selected (D1)."""
    return _build_named_tts(settings.tts_provider, settings)


def build_tts_fallback(settings: Settings) -> TTSProvider | None:
    """The fallback `TTSProvider` named by `SIM_TTS_FALLBACK_PROVIDER`, or `None` for `"none"`
    (D9's "configured fallback"; SPEC §39, `60-inference-ops.md` §4.4's TTS failure row).

    `"none"` is not refused the way an unrecognised name is (`_build_named_tts`'s `ValueError`):
    it is the gate's own selection (a fallback that is itself a fake would make INV 14's *second*
    failure untestable — `.env.example`'s `SIM_TTS_FALLBACK_PROVIDER` comment) and every real
    profile's explicit choice to run without a fallback provider at all."""
    provider = settings.tts_fallback_provider
    if provider == TTS_NONE:
        return None
    return _build_named_tts(provider, settings, primary=False)
