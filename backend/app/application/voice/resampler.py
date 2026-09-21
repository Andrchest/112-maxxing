"""`Resampler` — transport audio to the one format every later stage assumes (§3.1, D9, SPEC §16).

Input: `AudioFrame`s at the transport's rate (48 kHz from LiveKit, mono or stereo). Output:
`AudioFrame`s at `VoiceTurnConfig.sample_rate` (16 kHz), mono, s16le, **exactly**
`VADProvider.frame_samples` samples each — the VAD window is fixed by the model (512 samples for
Silero v5) and a short frame would be a different question asked of it.

Three jobs, in this order:

1. **Downmix** to mono by averaging the channels in 32-bit space, so two loud channels cannot wrap
   around;
2. **Resample** to the target rate by linear interpolation over a continuous sample position that
   survives across calls — resampling each input frame independently would put a discontinuity at
   every frame boundary, which a VAD hears as a click;
3. **Peak-normalise** toward `target_peak` with a hard limiter, so a loud trainee cannot clip the
   VAD/ASR input and a quiet one is still audible. The gain is a slow-moving running peak rather
   than a per-frame one, because per-frame normalisation would amplify silence between words into
   full-scale noise.

Re-blocking carries a remainder across calls and `capture_offset_ms` is derived from the count of
emitted samples since the first input frame, so offsets are continuous and never re-derived from
a wall clock (D5, D7). Pure and synchronous; no model, no I/O; emits no events.

`50-voice-pipeline.md` §1 names `workers/voice_agent/audio/resampler.py` as the target file. This
task's brief places it in `backend/app/application/voice/resampler.py` instead, and the brief
wins: the resampler is pure application logic with no transport dependency, and putting it here is
what lets the turn path be tested without importing the worker package (see the report,
"HLD gaps").
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from app.application.ports.call_transport import AudioFrame

__all__ = ["Resampler"]

_INT16_MAX = 32767.0
_BYTES_PER_SAMPLE = 2
_MS_PER_S = 1000


class Resampler:
    """Stateful 48 kHz-or-whatever → 16 kHz mono re-blocker (§3.1)."""

    def __init__(
        self,
        *,
        target_sample_rate: int,
        frame_samples: int,
        target_peak: float = 0.95,
        peak_decay: float = 0.995,
    ) -> None:
        if target_sample_rate <= 0:
            raise ValueError("target_sample_rate must be positive")
        if frame_samples <= 0:
            raise ValueError("frame_samples must be positive")
        if not 0.0 < target_peak <= 1.0:
            raise ValueError("target_peak must be in (0, 1]")
        if not 0.0 < peak_decay <= 1.0:
            raise ValueError("peak_decay must be in (0, 1]")
        self._target_sample_rate = target_sample_rate
        self._frame_samples = frame_samples
        self._target_peak = target_peak
        self._peak_decay = peak_decay
        self._pending: np.ndarray = np.zeros(0, dtype=np.float32)
        self._origin_ms: int | None = None
        self._emitted_samples = 0
        self._source_rate: int | None = None
        self._carry: float = 0.0
        self._last_sample: float = 0.0
        self._running_peak: float = 0.0

    @property
    def target_sample_rate(self) -> int:
        """The rate every emitted frame carries."""
        return self._target_sample_rate

    @property
    def frame_samples(self) -> int:
        """Samples per emitted frame."""
        return self._frame_samples

    def reset(self) -> None:
        """Drop every carried sample and offset. Called at the start of every call."""
        self._pending = np.zeros(0, dtype=np.float32)
        self._origin_ms = None
        self._emitted_samples = 0
        self._source_rate = None
        self._carry = 0.0
        self._last_sample = 0.0
        self._running_peak = 0.0

    def process(self, frame: AudioFrame) -> list[AudioFrame]:
        """Consume one transport frame and return the whole output frames it completed."""
        if self._origin_ms is None:
            self._origin_ms = frame.capture_offset_ms
        mono = self._downmix(frame)
        resampled = self._resample(mono, frame.sample_rate)
        normalised = self._normalise(resampled)
        self._pending = np.concatenate((self._pending, normalised))
        return list(self._drain())

    def flush(self) -> list[AudioFrame]:
        """Emit a final, zero-padded frame if a partial one is pending (end of a call)."""
        if self._pending.size == 0:
            return []
        padding = self._frame_samples - self._pending.size
        self._pending = np.concatenate((self._pending, np.zeros(padding, dtype=np.float32)))
        return list(self._drain())

    # -- internals ----------------------------------------------------------------------------

    def _downmix(self, frame: AudioFrame) -> np.ndarray:
        samples = np.frombuffer(frame.pcm, dtype="<i2").astype(np.float32)
        if frame.num_channels > 1:
            usable = (samples.size // frame.num_channels) * frame.num_channels
            samples = samples[:usable].reshape(-1, frame.num_channels).mean(axis=1)
        return samples / _INT16_MAX

    def _resample(self, mono: np.ndarray, source_rate: int) -> np.ndarray:
        if source_rate <= 0:
            raise ValueError("an AudioFrame must carry a positive sample_rate")
        if source_rate != self._source_rate:
            # A rate change mid-call restarts the interpolation phase rather than pretending the
            # carried position means the same thing at the new rate.
            self._source_rate = source_rate
            self._carry = 0.0
        if mono.size == 0:
            return mono
        if source_rate == self._target_sample_rate:
            self._last_sample = float(mono[-1])
            return mono
        step = source_rate / self._target_sample_rate
        # Positions are measured against a buffer that begins with the previous call's last
        # sample, so interpolation across the frame boundary is continuous.
        extended = np.concatenate((np.asarray([self._last_sample], dtype=np.float32), mono))
        count = int(np.floor((extended.size - 1 - self._carry) / step)) + 1
        if count <= 0:
            self._carry -= extended.size - 1
            self._last_sample = float(mono[-1])
            return np.zeros(0, dtype=np.float32)
        positions = self._carry + step * np.arange(count, dtype=np.float64)
        out = np.asarray(np.interp(positions, np.arange(extended.size, dtype=np.float64), extended))
        self._carry = float(positions[-1] + step - (extended.size - 1))
        self._last_sample = float(mono[-1])
        return out.astype(np.float32)

    def _normalise(self, samples: np.ndarray) -> np.ndarray:
        if samples.size == 0:
            return samples
        frame_peak = float(np.max(np.abs(samples)))
        self._running_peak = max(frame_peak, self._running_peak * self._peak_decay)
        if self._running_peak <= 0.0:
            return samples
        gain = self._target_peak / self._running_peak
        return np.clip(samples * gain, -self._target_peak, self._target_peak)

    def _drain(self) -> Iterator[AudioFrame]:
        origin = self._origin_ms or 0
        while self._pending.size >= self._frame_samples:
            block = self._pending[: self._frame_samples]
            self._pending = self._pending[self._frame_samples :]
            offset_ms = origin + (self._emitted_samples * _MS_PER_S) // self._target_sample_rate
            self._emitted_samples += self._frame_samples
            pcm = np.round(block * _INT16_MAX).astype("<i2").tobytes()
            yield AudioFrame(
                pcm=pcm,
                sample_rate=self._target_sample_rate,
                num_channels=1,
                samples_per_channel=self._frame_samples,
                capture_offset_ms=offset_ms,
            )

    @staticmethod
    def silence(frame_samples: int) -> bytes:
        """`frame_samples` mono s16le zero samples — the warm-up window of SPEC §37."""
        return b"\x00" * (frame_samples * _BYTES_PER_SAMPLE)
