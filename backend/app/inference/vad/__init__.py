"""VAD adapters for the `VADProvider` port (HLD `50-voice-pipeline.md` §2.2, `60-inference-ops.md`).

`EnergyVAD` ships with E11: pure Python + numpy, no model file, no GPU. It is what `make gate`
runs (D13) and the documented fallback when the Silero onnx model is absent.

`SileroVAD` (E12, `app.inference.vad.silero_vad`) is the production provider for every real model
profile — onnxruntime, CPU execution provider. It keeps the same `frame_samples = 512` at 16 kHz so
a threshold configured for one provider is frame-identical for the other. Importing this package
never requires onnxruntime: `SileroVAD`'s heavy import is lazy, inside `warm_up()`.
"""

from __future__ import annotations

from app.inference.vad.energy_vad import EnergyVAD
from app.inference.vad.silero_vad import SileroVAD

__all__ = ["EnergyVAD", "SileroVAD"]
