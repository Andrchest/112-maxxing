"""`voice_agent.providers` — provider selection and the laziness of the heavy imports (D1, §1).

Two properties, and the second is the one that keeps `make gate` runnable on a machine with no
GPU and no weights:

* the setting selects the provider, and an unknown value is **refused** rather than defaulted —
  a typo in `SIM_ASR_PROVIDER` that silently fell back to `FakeASR` would mean a training session
  run against a scripted transcript;
* `torch`, `onnxruntime` and `faster_whisper` are imported inside the branch that needs them, so
  `import app.inference.asr` and `import voice_agent.providers` work in a plain dev venv.

The `silero` / `gigaam` / `faster_whisper` branches are asserted through a monkeypatched
constructor, so this file passes whether or not E12-B's adapters can load their extras here.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest
from app.application.ports.asr import ASRProvider
from app.application.ports.tts import TTSProvider
from app.application.ports.vad import VADProvider
from app.application.voice.config import VoiceTurnConfig
from app.config.settings import Settings
from app.inference.asr import FakeASR
from app.inference.tts import FakeTTS
from voice_agent import providers as providers_module
from voice_agent.providers import (
    ASR_FAKE,
    ASR_FASTER_WHISPER,
    ASR_GIGAAM,
    TTS_FAKE,
    TTS_NONE,
    TTS_PIPER,
    TTS_QWEN3,
    VAD_ENERGY,
    VAD_SILERO,
    build_asr,
    build_tts,
    build_tts_fallback,
    build_vad,
)

REPO = Path(__file__).resolve().parents[3]
#: The packages a dev venv is not required to have (D1: optional extras).
HEAVY_PACKAGES: tuple[str, ...] = (
    "torch",
    "torchaudio",
    "transformers",
    "onnxruntime",
    "faster_whisper",
    "gigaam",
    "piper",
    "qwen_tts",
)


def settings(**overrides: Any) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        "redis_url": "redis://localhost:56379/0",
        "jwt_secret": "test-only-secret",
        "livekit_url": "ws://localhost:7880",
        "livekit_api_key": "devkey",
        "livekit_api_secret": "devsecret1234567890",
        "llm_base_url": "http://localhost:8080/v1",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# -- the gate's selection ----------------------------------------------------------------------


def test_the_defaults_are_the_gate_s_providers() -> None:
    """D13: an unconfigured process runs `energy` + `fake` — no weights, no GPU."""
    resolved = settings()
    assert resolved.vad_provider == VAD_ENERGY
    assert resolved.asr_provider == ASR_FAKE
    assert resolved.tts_provider == TTS_FAKE
    assert resolved.tts_fallback_provider == TTS_NONE


def test_the_energy_branch_builds_a_vad_matching_the_turn_config() -> None:
    """The provider and the config must agree frame for frame (§2.2, §4.1)."""
    config = VoiceTurnConfig()
    vad = build_vad(settings(), config)
    assert isinstance(vad, VADProvider)
    assert vad.provider_name == "energy"
    assert vad.frame_samples == config.frame_samples
    assert vad.required_sample_rate == config.sample_rate


def test_build_vad_loads_the_config_itself_when_it_is_not_given() -> None:
    """The single-argument form of the factory has to mean something (ruling 3)."""
    vad = build_vad(settings(voice_vad_frame_ms=16))
    assert vad.frame_samples == VoiceTurnConfig(vad_frame_ms=16).frame_samples


def test_the_fake_branch_builds_the_scripted_provider() -> None:
    """D13's ASR: scripted, deterministic, no model file."""
    asr = build_asr(settings(asr_provider=ASR_FAKE))
    assert isinstance(asr, FakeASR)
    assert isinstance(asr, ASRProvider)
    assert asr.provider_name == "fake"


def test_build_tts_fake_branch_builds_faketts() -> None:
    """D13's TTS: `FakeTTS`, deterministic, no weights."""
    tts = build_tts(settings(tts_provider=TTS_FAKE))
    assert isinstance(tts, FakeTTS)
    assert isinstance(tts, TTSProvider)
    assert tts.provider_name == "fake"


def test_build_tts_fallback_is_none_for_the_no_fallback_setting() -> None:
    """`SIM_TTS_FALLBACK_PROVIDER=none` (the gate's own selection, D9/INV 14) -> `None`."""
    assert build_tts_fallback(settings(tts_fallback_provider=TTS_NONE)) is None


def test_build_tts_fallback_builds_the_named_provider_when_configured() -> None:
    fallback = build_tts_fallback(settings(tts_fallback_provider=TTS_FAKE))
    assert isinstance(fallback, FakeTTS)


# -- the real branches, without the real packages ----------------------------------------------


def test_the_silero_branch_passes_the_configured_model_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling 3's signature: `SileroVAD(*, model_path, threshold_hint)`."""
    captured: dict[str, Any] = {}

    class StubSilero:
        def __init__(self, *, model_path: str, threshold_hint: float | None = None) -> None:
            captured.update(model_path=model_path, threshold_hint=threshold_hint)

    module = _stub_module("app.inference.vad.silero_vad", SileroVAD=StubSilero)
    monkeypatch.setitem(sys.modules, "app.inference.vad.silero_vad", module)

    config = VoiceTurnConfig()
    build_vad(settings(vad_provider=VAD_SILERO, vad_model_path="models/x.onnx"), config)

    assert captured == {
        "model_path": "models/x.onnx",
        "threshold_hint": config.speech_start_threshold,
    }


def test_the_gigaam_branch_passes_the_configured_model_and_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling 3: `GigaAMProvider(*, model_dir, model_version, device, compute_type)`."""
    captured: dict[str, Any] = {}

    class StubGigaAM:
        def __init__(
            self, *, model_dir: str, model_version: str, device: str, compute_type: str
        ) -> None:
            captured.update(
                model_dir=model_dir,
                model_version=model_version,
                device=device,
                compute_type=compute_type,
            )

    module = _stub_module("app.inference.asr.gigaam_provider", GigaAMProvider=StubGigaAM)
    monkeypatch.setitem(sys.modules, "app.inference.asr.gigaam_provider", module)

    build_asr(
        settings(
            asr_provider=ASR_GIGAAM,
            asr_model_dir="models/gigaam-v3-ctc",
            asr_model_version="v3_ctc",
            asr_device="cpu",
            asr_compute_type="float32",
        )
    )

    assert captured == {
        "model_dir": "models/gigaam-v3-ctc",
        "model_version": "v3_ctc",
        "device": "cpu",
        "compute_type": "float32",
    }


def test_the_faster_whisper_branch_passes_the_configured_model_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling 3: `FasterWhisperProvider(*, model_path, device, compute_type)`."""
    captured: dict[str, Any] = {}

    class StubWhisper:
        def __init__(self, *, model_path: str, device: str, compute_type: str) -> None:
            captured.update(model_path=model_path, device=device, compute_type=compute_type)

    module = _stub_module(
        "app.inference.asr.faster_whisper_provider", FasterWhisperProvider=StubWhisper
    )
    monkeypatch.setitem(sys.modules, "app.inference.asr.faster_whisper_provider", module)

    build_asr(
        settings(
            asr_provider=ASR_FASTER_WHISPER,
            asr_model_dir="models/whisper-small",
            asr_device="cuda",
            asr_compute_type="float16",
        )
    )

    assert captured == {
        "model_path": "models/whisper-small",
        "device": "cuda",
        "compute_type": "float16",
    }


def test_the_qwen3_tts_branch_passes_the_configured_endpoint_and_speaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`Qwen3TTS(*, base_url, speaker, timeout_ms)` (E14-B)."""
    captured: dict[str, Any] = {}

    class StubQwen3TTS:
        def __init__(self, *, base_url: str, speaker: str, timeout_ms: int) -> None:
            captured.update(base_url=base_url, speaker=speaker, timeout_ms=timeout_ms)

    module = _stub_module("app.inference.tts.qwen3_tts", Qwen3TTS=StubQwen3TTS)
    monkeypatch.setitem(sys.modules, "app.inference.tts.qwen3_tts", module)

    build_tts(
        settings(
            tts_provider=TTS_QWEN3,
            tts_qwen3_base_url="http://127.0.0.1:8112",
            tts_qwen3_speaker="Serena",
            tts_timeout_ms=9000,
        )
    )

    assert captured == {
        "base_url": "http://127.0.0.1:8112",
        "speaker": "Serena",
        "timeout_ms": 9000,
    }


def test_the_piper_branch_passes_the_configured_voice_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`PiperTTS(*, voice_path)` (E14-B)."""
    captured: dict[str, Any] = {}

    class StubPiperTTS:
        def __init__(self, *, voice_path: str) -> None:
            captured.update(voice_path=voice_path)

    module = _stub_module("app.inference.tts.piper_tts", PiperTTS=StubPiperTTS)
    monkeypatch.setitem(sys.modules, "app.inference.tts.piper_tts", module)

    build_tts(settings(tts_provider=TTS_PIPER, tts_piper_voice_path="models/piper/x.onnx"))

    assert captured == {"voice_path": "models/piper/x.onnx"}


def test_build_tts_fallback_also_uses_the_shared_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback slot builds the same way the primary slot does — one branch, two callers."""
    captured: dict[str, Any] = {}

    class StubPiperTTS:
        def __init__(self, *, voice_path: str) -> None:
            captured.update(voice_path=voice_path)

    module = _stub_module("app.inference.tts.piper_tts", PiperTTS=StubPiperTTS)
    monkeypatch.setitem(sys.modules, "app.inference.tts.piper_tts", module)

    fallback = build_tts_fallback(
        settings(tts_fallback_provider=TTS_PIPER, tts_piper_voice_path="models/piper/y.onnx")
    )

    assert fallback is not None
    assert captured == {"voice_path": "models/piper/y.onnx"}


# -- refusals ----------------------------------------------------------------------------------


def test_an_unknown_vad_provider_is_refused() -> None:
    """A typo must not silently become the gate's detector in a real training session."""
    with pytest.raises(ValueError, match="SIM_VAD_PROVIDER"):
        build_vad(settings(vad_provider="webrtc"))


def test_an_unknown_asr_provider_is_refused() -> None:
    """Likewise for ASR — a scripted transcript in production is worse than a dead process."""
    with pytest.raises(ValueError, match="SIM_ASR_PROVIDER"):
        build_asr(settings(asr_provider="whisper-api"))


def test_an_unknown_tts_provider_is_refused() -> None:
    with pytest.raises(ValueError):
        build_tts(settings(tts_provider="elevenlabs"))


def test_an_unknown_tts_fallback_provider_is_refused() -> None:
    """`"none"` is the only value that means "no fallback" — anything else unrecognised is a
    refusal, exactly like the primary slot, not a silent `None`."""
    with pytest.raises(ValueError):
        build_tts_fallback(settings(tts_fallback_provider="elevenlabs"))


# -- laziness ----------------------------------------------------------------------------------


def test_no_heavy_package_is_imported_at_module_level() -> None:
    """Ruling 2: the extras are imported inside `warm_up()` / the selecting branch, never at top.

    An `ast` scan rather than a `sys.modules` check, because the latter would pass merely because
    the machine running the gate has no GPU — this asserts the *source*, which is the rule.
    """
    roots = (
        REPO / "backend" / "app" / "inference",
        REPO / "workers" / "voice_agent" / "voice_agent",
    )
    offenders: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:  # module level only — nested imports are the point
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    root_package = name.split(".")[0]
                    if root_package in HEAVY_PACKAGES:
                        offenders.append(f"{path.relative_to(REPO).as_posix()}: {name}")
    assert not offenders, (
        "these modules import an optional heavy extra at module level, which breaks "
        f"`import app.inference.asr` in a plain dev venv (D1, ruling 2): {offenders}"
    )


def test_importing_the_providers_module_pulls_in_no_heavy_package() -> None:
    """The complement of the scan above, observed rather than read."""
    assert providers_module.__name__ == "voice_agent.providers"
    assert not [name for name in HEAVY_PACKAGES if name in sys.modules], (
        "a heavy extra was already imported before any provider was selected"
    )


def _stub_module(name: str, **attributes: Any) -> Any:
    """A module object carrying `attributes`, for `monkeypatch.setitem(sys.modules, …)`."""
    import types

    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module
