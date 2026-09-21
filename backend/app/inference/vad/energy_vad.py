"""`EnergyVAD` — RMS-threshold voice activity detection (§2.2, `60-inference-ops.md` §1, D13).

The gate's VAD and the fallback when the Silero onnx model is absent. It answers the same
question over the same window as `SileroVAD` (512 samples = 32 ms at 16 kHz, fixed by the Silero
v5 model), so every `VoiceTurnConfig` threshold means the same thing for both and a turn-detector
test written against this provider is not a test of a different machine.

The probability mapping is `rms / (rms + threshold)`: monotone, bounded to (0, 1), and anchored so
that a frame exactly at the threshold scores 0.5 — the middle of the default hysteresis band
(0.35 / 0.55), where the detector deliberately does nothing. Loud speech saturates toward 1.0 and
digital silence is exactly 0.0. It is not a calibrated probability and does not pretend to be one;
it is a reproducible number with the right shape, which is what a deterministic gate needs.
"""

from __future__ import annotations

import numpy as np

from app.application.ports.call_transport import AudioFrame
from app.application.ports.vad import VadFrameResult

__all__ = ["EnergyVAD"]

_INT16_MAX = 32767.0

#: The Silero v5 window, which this provider copies so the two are frame-interchangeable (§2.2).
DEFAULT_FRAME_SAMPLES = 512
DEFAULT_SAMPLE_RATE = 16_000
#: RMS (in full-scale units) at which a frame scores 0.5. About −34 dBFS: above the noise floor of
#: a headset microphone, below any voiced speech.
DEFAULT_RMS_THRESHOLD = 0.02


class EnergyVAD:
    """A `VADProvider` with no model file (§2.2)."""

    provider_name = "energy"

    def __init__(
        self,
        *,
        frame_samples: int = DEFAULT_FRAME_SAMPLES,
        required_sample_rate: int = DEFAULT_SAMPLE_RATE,
        rms_threshold: float = DEFAULT_RMS_THRESHOLD,
    ) -> None:
        if frame_samples <= 0:
            raise ValueError("frame_samples must be positive")
        if required_sample_rate <= 0:
            raise ValueError("required_sample_rate must be positive")
        if rms_threshold <= 0.0:
            raise ValueError("rms_threshold must be positive")
        self._frame_samples = frame_samples
        self._required_sample_rate = required_sample_rate
        self._rms_threshold = rms_threshold
        self._closed = False

    @property
    def frame_samples(self) -> int:
        """Fixed window this provider requires, in samples at `required_sample_rate`."""
        return self._frame_samples

    @property
    def required_sample_rate(self) -> int:
        """The only sample rate this provider accepts."""
        return self._required_sample_rate

    @property
    def rms_threshold(self) -> float:
        """The RMS that scores 0.5."""
        return self._rms_threshold

    async def warm_up(self) -> None:
        """Nothing to warm: there is no model. Kept so the port is uniform (SPEC §37)."""
        return None

    def reset(self) -> None:
        """Nothing to reset: the detector is stateless between frames."""
        return None

    async def process(self, frame: AudioFrame) -> VadFrameResult:
        """Score one frame. It must be mono at `required_sample_rate`, `frame_samples` long."""
        if self._closed:
            raise RuntimeError("EnergyVAD is closed")
        if frame.sample_rate != self._required_sample_rate:
            raise ValueError(
                f"EnergyVAD needs {self._required_sample_rate} Hz, got {frame.sample_rate}"
            )
        if frame.num_channels != 1:
            raise ValueError(f"EnergyVAD needs mono audio, got {frame.num_channels} channels")
        if frame.samples_per_channel != self._frame_samples:
            raise ValueError(
                f"EnergyVAD needs exactly {self._frame_samples} samples, "
                f"got {frame.samples_per_channel}"
            )
        samples = np.frombuffer(frame.pcm, dtype="<i2").astype(np.float32) / _INT16_MAX
        rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        probability = rms / (rms + self._rms_threshold) if rms > 0.0 else 0.0
        return VadFrameResult(
            speech_probability=probability,
            frame_start_ms=frame.capture_offset_ms,
            frame_duration_ms=frame.duration_ms,
        )

    async def close(self) -> None:
        """Release the (non-existent) model. Idempotent."""
        self._closed = True
