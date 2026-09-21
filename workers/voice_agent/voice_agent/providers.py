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
"""

from __future__ import annotations

from app.application.ports.asr import ASRProvider
from app.application.ports.llm import LLMClient
from app.application.ports.vad import VADProvider
from app.application.voice.config import VoiceTurnConfig, voice_turn_config_from_settings
from app.config.settings import Settings

__all__ = [
    "ASR_FAKE",
    "ASR_FASTER_WHISPER",
    "ASR_GIGAAM",
    "LLM_FAKE",
    "LLM_LLAMA_CPP",
    "VAD_ENERGY",
    "VAD_SILERO",
    "build_asr",
    "build_llm",
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
            model_path=settings.vad_model_path,
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
            model_dir=settings.asr_model_dir,
            model_version=settings.asr_model_version,
            device=settings.asr_device,
            compute_type=settings.asr_compute_type,
        )
    if provider == ASR_FASTER_WHISPER:
        # Lazy: `faster-whisper` is the `asr-whisper` extra.
        from app.inference.asr.faster_whisper_provider import FasterWhisperProvider

        return FasterWhisperProvider(
            model_path=settings.asr_model_dir,
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
