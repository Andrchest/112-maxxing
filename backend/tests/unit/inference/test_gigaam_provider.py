"""`GigaAMProvider` — pure helpers and the gate-side guarantees (E12 ruling 1/2/3).

These run everywhere `make gate` runs: no torch, no transformers, no model weights (the module
itself imports neither at module scope — that is exactly what this file proves). The real
model-backed behaviour (an actual transcript, word error rate, VRAM) is proven separately by
`backend/tests/models/test_gigaam_provider.py` (marker `requires_models`, `make test-models`).
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest
from app.application.ports.asr import UnsupportedOperationError
from app.inference.asr.gigaam_provider import GigaAMProvider, ctc_confidence, split_long_audio
from app.inference.errors import ModelNotAvailableError

_SAMPLE_RATE = 16_000


def _tone_pcm(duration_s: float, sample_rate: int = _SAMPLE_RATE, amplitude: int = 8000) -> bytes:
    count = int(duration_s * sample_rate)
    return struct.pack(f"<{count}h", *([amplitude] * count))


def test_the_module_imports_cleanly_with_no_torch_installed() -> None:
    """E12 ruling 2: `import app.inference.asr.gigaam_provider` must work in the plain dev venv.

    The import at the top of this file already exercised this; if the module imported torch (or
    transformers/hydra/omegaconf/sentencepiece) eagerly, collecting this test file would fail
    before a single test ran, in *every* environment lacking the `asr-gigaam` extra — which is the
    gate's environment. Reaching this line at all is the proof.
    """
    assert True


class TestSplitLongAudio:
    def test_short_audio_is_returned_as_a_single_window(self) -> None:
        pcm = _tone_pcm(2.0)
        assert split_long_audio(pcm, _SAMPLE_RATE) == [pcm]

    def test_audio_at_the_model_window_threshold_is_not_split(self) -> None:
        pcm = _tone_pcm(25.0)
        assert split_long_audio(pcm, _SAMPLE_RATE) == [pcm]

    def test_long_audio_is_split_into_windows_under_the_model_threshold(self) -> None:
        pcm = _tone_pcm(45.0)
        windows = split_long_audio(pcm, _SAMPLE_RATE)
        assert len(windows) >= 2
        for window in windows[:-1]:
            assert len(window) // 2 <= int(25.0 * _SAMPLE_RATE)
        # Every sample is accounted for exactly once, in order — no audio is dropped or duplicated.
        assert b"".join(windows) == pcm

    def test_split_prefers_the_lowest_energy_frame_near_the_boundary(self) -> None:
        loud = np.full(int(30 * _SAMPLE_RATE), 8000, dtype="<i2")
        quiet_start = int(20 * _SAMPLE_RATE)
        loud[quiet_start : quiet_start + int(0.1 * _SAMPLE_RATE)] = 0
        pcm = loud.tobytes()

        windows = split_long_audio(pcm, _SAMPLE_RATE)

        assert len(windows) == 2
        cut_sample = len(windows[0]) // 2
        assert abs(cut_sample - quiet_start) < int(0.5 * _SAMPLE_RATE)

    def test_rejects_a_non_positive_sample_rate(self) -> None:
        with pytest.raises(ValueError, match="sample_rate"):
            split_long_audio(b"", 0)

    def test_empty_audio_is_a_single_empty_window(self) -> None:
        assert split_long_audio(b"", _SAMPLE_RATE) == [b""]


class TestCtcConfidence:
    def test_zero_length_is_zero(self) -> None:
        assert ctc_confidence(np.array([0.9]), np.array([1]), blank_id=0, length=0) == 0.0

    def test_all_blank_frames_is_zero(self) -> None:
        result = ctc_confidence(np.array([0.9, 0.8]), np.array([0, 0]), blank_id=0, length=2)
        assert result == 0.0

    def test_averages_only_the_non_blank_frames(self) -> None:
        max_probs = np.array([0.9, 0.5, 0.7])
        labels = np.array([1, 0, 2])  # blank_id=0 -> frame 1 excluded
        result = ctc_confidence(max_probs, labels, blank_id=0, length=3)
        assert result == pytest.approx((0.9 + 0.7) / 2)

    def test_padding_past_length_is_ignored(self) -> None:
        max_probs = np.array([0.9, 0.1])
        labels = np.array([1, 1])  # frame 1 would drag the mean down if length did not exclude it
        result = ctc_confidence(max_probs, labels, blank_id=0, length=1)
        assert result == pytest.approx(0.9)


class TestGigaAMProviderPortShape:
    def test_properties_need_no_model_loaded(self) -> None:
        provider = GigaAMProvider(
            model_dir="/nonexistent", model_version="v3_ctc", device="cpu", compute_type="float32"
        )
        assert provider.provider_name == "gigaam"
        assert provider.model_version == "v3_ctc"
        assert provider.supports_streaming is False
        assert provider.required_sample_rate == 16_000

    def test_stream_raises_not_implemented_naming_the_pseudo_stream(self) -> None:
        provider = GigaAMProvider(
            model_dir="/nonexistent", model_version="v3_ctc", device="cpu", compute_type="float32"
        )
        with pytest.raises(UnsupportedOperationError, match="pseudo-stream"):
            provider.stream(iter(()), request_id="r1")

    async def test_transcribe_before_warm_up_is_refused(self) -> None:
        provider = GigaAMProvider(
            model_dir="/nonexistent", model_version="v3_ctc", device="cpu", compute_type="float32"
        )
        with pytest.raises(RuntimeError, match="warm_up"):
            await provider.transcribe(b"\x00\x00", 16_000, request_id="r1")

    async def test_the_wrong_sample_rate_is_refused_even_before_warm_up(self) -> None:
        provider = GigaAMProvider(
            model_dir="/nonexistent", model_version="v3_ctc", device="cpu", compute_type="float32"
        )
        with pytest.raises(ValueError, match="16000"):
            await provider.transcribe(b"\x00\x00", 8_000, request_id="r1")

    async def test_a_missing_model_dir_raises_model_not_available_without_importing_torch(
        self, tmp_path: Path
    ) -> None:
        """E12 ruling 2/3: the path check runs before the heavy import, so this is a gate test."""
        missing = tmp_path / "gigaam-v3-e2e_ctc"
        provider = GigaAMProvider(
            model_dir=str(missing), model_version="v3_e2e_ctc", device="cpu", compute_type="float32"
        )
        with pytest.raises(ModelNotAvailableError, match=str(missing)):
            await provider.warm_up()

    async def test_close_before_warm_up_is_a_no_op(self) -> None:
        provider = GigaAMProvider(
            model_dir="/nonexistent", model_version="v3_ctc", device="cpu", compute_type="float32"
        )
        await provider.close()
        await provider.close()
