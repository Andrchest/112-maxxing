"""`SileroVAD` — gate-side guarantees only (E12 ruling 1/2).

No onnxruntime, no model weights: this file runs everywhere `make gate` runs. The real
model-backed behaviour (actual speech/silence probabilities, per-frame latency) is proven by
`backend/tests/models/test_silero_vad.py` (marker `requires_models`, `make test-models`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.inference.errors import ModelNotAvailableError
from app.inference.vad.silero_vad import FRAME_SAMPLES, REQUIRED_SAMPLE_RATE, SileroVAD


def test_the_module_imports_cleanly_with_no_onnxruntime_installed() -> None:
    """E12 ruling 2: `import app.inference.vad` must work without the `vad-silero` extra.

    The import at the top of this file already exercised it — reaching this line is the proof.
    """
    assert True


def test_frame_window_matches_energy_vad_so_the_two_are_frame_interchangeable() -> None:
    """§2.2: SileroVAD and EnergyVAD must be frame-identical (the whole reason for the constant)."""
    provider = SileroVAD(model_path="/nonexistent/silero_vad.onnx")
    assert provider.frame_samples == FRAME_SAMPLES == 512
    assert provider.required_sample_rate == REQUIRED_SAMPLE_RATE == 16_000
    assert provider.provider_name == "silero"


def test_threshold_hint_is_carried_but_not_required() -> None:
    provider = SileroVAD(model_path="/nonexistent/silero_vad.onnx", threshold_hint=0.6)
    assert provider.threshold_hint == 0.6
    assert SileroVAD(model_path="/nonexistent/silero_vad.onnx").threshold_hint is None


async def test_a_missing_model_file_raises_model_not_available_without_importing_onnxruntime(
    tmp_path: Path,
) -> None:
    """The path check happens before the heavy import (ruling 2), so this is a gate test."""
    missing = tmp_path / "silero_vad.onnx"
    provider = SileroVAD(model_path=str(missing))
    with pytest.raises(ModelNotAvailableError, match=str(missing)) as excinfo:
        await provider.warm_up()
    assert "make models-silero" in str(excinfo.value)


async def test_process_before_warm_up_is_refused() -> None:
    from app.application.ports.call_transport import AudioFrame

    provider = SileroVAD(model_path="/nonexistent/silero_vad.onnx")
    frame = AudioFrame(
        pcm=b"\x00\x00" * 512,
        sample_rate=16_000,
        num_channels=1,
        samples_per_channel=512,
        capture_offset_ms=0,
    )
    with pytest.raises(RuntimeError, match="warm_up"):
        await provider.process(frame)


async def test_close_before_warm_up_is_a_no_op_and_is_idempotent() -> None:
    provider = SileroVAD(model_path="/nonexistent/silero_vad.onnx")
    await provider.close()
    await provider.close()


def test_reset_before_warm_up_does_not_raise() -> None:
    """`reset()` is synchronous per the port and must be safe even with no session loaded yet."""
    provider = SileroVAD(model_path="/nonexistent/silero_vad.onnx")
    provider.reset()
