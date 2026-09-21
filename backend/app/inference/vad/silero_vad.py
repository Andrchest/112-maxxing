"""`SileroVAD` — the onnxruntime `VADProvider` (`50-voice-pipeline.md` §2.2, `60-inference-ops.md`
§1/§2.2/table, `make models-silero`).

The production VAD for every real model profile; `EnergyVAD` (`app.inference.vad.energy_vad`) is
the gate's provider and the fallback when this model's onnx file is absent. Both share
`frame_samples = 512` at 16 kHz (the Silero v5 model's fixed window, 32 ms) so a threshold
configured for one is frame-identical for the other.

`onnxruntime` is a heavy, optional dependency (the `vad-silero` extra, D1) and is imported lazily
inside `warm_up()`, never at module import time — `import app.inference.vad` must succeed in the
plain dev venv (E12 ruling 2).

Model interface (pinned tag v5.1.2 of github.com/snakers4/silero-vad,
`src/silero_vad/data/silero_vad.onnx`, MIT licence — see `models/README.md` and
`docs/hld/60-inference-ops.md`'s model table for the URL and sha256): three inputs —
`input` (float32, `[batch, 64 + frame_samples]`, the 512-sample chunk with the *previous* chunk's
trailing 64 samples prepended as convolutional context), `state` (float32, `[2, batch, 128]`, the
model's own recurrent state) and `sr` (int64 scalar, the sample rate) — and two outputs, `output`
(the speech probability) and the updated `state`. The 64-sample context and the `state` tensor are
exactly the two pieces of memory ruling (2) calls out; `reset()` zeroes both.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.application.ports.call_transport import AudioFrame
from app.application.ports.vad import VadFrameResult
from app.inference.errors import ModelNotAvailableError

if TYPE_CHECKING:
    import numpy as np

__all__ = ["SileroVAD"]

#: Fixed by the Silero v5 model (`60-inference-ops.md` §2.2); not configurable.
FRAME_SAMPLES = 512
REQUIRED_SAMPLE_RATE = 16_000
#: The trailing-context window the v5 onnx graph expects prepended to every chunk.
_CONTEXT_SAMPLES = 64
#: `[num_layers, batch, hidden]` of the model's combined recurrent state.
_STATE_SHAPE = (2, 1, 128)
_INT16_MAX = 32768.0


class SileroVAD:
    """`VADProvider` over the Silero VAD v5 onnx graph, CPU execution provider only."""

    provider_name = "silero"

    def __init__(self, *, model_path: str, threshold_hint: float | None = None) -> None:
        self._model_path = model_path
        #: Not used by `process()` itself — `TurnDetector` owns the actual threshold
        #: (`VoiceTurnConfig.speech_start_threshold`, §4.1). Carried here only so a profile can
        #: document the value this checkpoint was tuned against.
        self.threshold_hint = threshold_hint
        self._session: Any = None
        self._np: Any = None
        self._state: np.ndarray | None = None
        self._context: np.ndarray | None = None
        self._closed = False

    @property
    def frame_samples(self) -> int:
        """Fixed window the model requires, in samples at `required_sample_rate`."""
        return FRAME_SAMPLES

    @property
    def required_sample_rate(self) -> int:
        """The only sample rate this provider accepts."""
        return REQUIRED_SAMPLE_RATE

    async def warm_up(self) -> None:
        """Load the onnx session (CPU, 1 intra-op thread) and process one zero frame."""
        if self._session is not None:
            return
        path = Path(self._model_path)
        if not await asyncio.to_thread(path.is_file):
            raise ModelNotAvailableError(
                f"Silero VAD model not found at {path} — run `make models-silero` to fetch it"
            )
        import numpy as np
        import onnxruntime as ort

        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = 1
        session_options.inter_op_num_threads = 1
        self._np = np
        self._session = ort.InferenceSession(
            str(path), sess_options=session_options, providers=["CPUExecutionProvider"]
        )
        self.reset()
        zero_frame = AudioFrame(
            pcm=b"\x00\x00" * FRAME_SAMPLES,
            sample_rate=REQUIRED_SAMPLE_RATE,
            num_channels=1,
            samples_per_channel=FRAME_SAMPLES,
            capture_offset_ms=0,
        )
        await self.process(zero_frame)
        self.reset()  # the warm-up frame must not leak state into the first real call

    def reset(self) -> None:
        """Drop the model's recurrent state and the 64-sample context window."""
        np = self._np
        if np is None:
            self._state = None
            self._context = None
            return
        self._state = np.zeros(_STATE_SHAPE, dtype=np.float32)
        self._context = np.zeros((1, _CONTEXT_SAMPLES), dtype=np.float32)

    async def process(self, frame: AudioFrame) -> VadFrameResult:
        """Score one frame. Runs inline: a 512-sample onnx call is ~1 ms (measured, see report)."""
        if self._closed:
            raise RuntimeError("SileroVAD is closed")
        if self._session is None or self._state is None or self._context is None:
            raise RuntimeError("SileroVAD.warm_up() must be called before process()")
        if frame.sample_rate != REQUIRED_SAMPLE_RATE:
            raise ValueError(f"SileroVAD needs {REQUIRED_SAMPLE_RATE} Hz, got {frame.sample_rate}")
        if frame.num_channels != 1:
            raise ValueError(f"SileroVAD needs mono audio, got {frame.num_channels} channels")
        if frame.samples_per_channel != FRAME_SAMPLES:
            raise ValueError(
                f"SileroVAD needs exactly {FRAME_SAMPLES} samples, got {frame.samples_per_channel}"
            )
        np = self._np
        samples = np.frombuffer(frame.pcm, dtype="<i2").astype(np.float32) / _INT16_MAX
        chunk = np.concatenate([self._context, samples.reshape(1, -1)], axis=1)
        outputs = self._session.run(
            None,
            {
                "input": chunk.astype(np.float32),
                "state": self._state,
                "sr": np.array(REQUIRED_SAMPLE_RATE, dtype=np.int64),
            },
        )
        probability, state = outputs[0], outputs[1]
        self._state = state
        self._context = chunk[:, -_CONTEXT_SAMPLES:]
        return VadFrameResult(
            speech_probability=float(np.asarray(probability).reshape(-1)[0]),
            frame_start_ms=frame.capture_offset_ms,
            frame_duration_ms=frame.duration_ms,
        )

    async def close(self) -> None:
        """Drop the onnx session. Idempotent."""
        self._session = None
        self._closed = True
