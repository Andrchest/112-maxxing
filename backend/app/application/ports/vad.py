"""`VADProvider` port (HLD `50-voice-pipeline.md` §2.2, D9, SPEC §17).

The `TurnDetector` sees probabilities, never audio models: every provider — `SileroVAD` (E12),
`EnergyVAD` (here, the gate's VAD and the fallback when the onnx model is absent) — answers the
same question about the same fixed window, so a threshold configured for one is frame-identical
for the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.application.ports.call_transport import AudioFrame

__all__ = ["VADProvider", "VadFrameResult"]


@dataclass(frozen=True, slots=True)
class VadFrameResult:
    """One analysed window (§2.2)."""

    speech_probability: float
    """0.0..1.0."""

    frame_start_ms: int
    """Session-relative start of the analysed frame."""

    frame_duration_ms: int


@runtime_checkable
class VADProvider(Protocol):
    """Voice-activity detection over fixed-size mono frames."""

    @property
    def frame_samples(self) -> int:
        """Fixed window the model requires, in samples at `required_sample_rate`."""
        ...

    @property
    def required_sample_rate(self) -> int:
        """The only sample rate this provider accepts."""
        ...

    @property
    def provider_name(self) -> str:
        """Short identifier written to `USER_SPEECH_STARTED.vad_provider` (§10.13)."""
        ...

    async def warm_up(self) -> None:
        """Run one dummy window so the first real frame is not the first inference (SPEC §37)."""
        ...

    def reset(self) -> None:
        """Drop the model's internal recurrent state. Called at the start of every call."""
        ...

    async def process(self, frame: AudioFrame) -> VadFrameResult:
        """`frame` must carry exactly `frame_samples` mono samples at `required_sample_rate`."""
        ...

    async def close(self) -> None:
        """Release the model. Idempotent."""
        ...
