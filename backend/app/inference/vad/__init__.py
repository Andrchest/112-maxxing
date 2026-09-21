"""VAD adapters for the `VADProvider` port (HLD `50-voice-pipeline.md` §2.2, `60-inference-ops.md`).

`EnergyVAD` ships with E11: pure Python + numpy, no model file, no GPU. It is what `make gate`
runs (D13) and the documented fallback when the Silero onnx model is absent.

TODO(E12): `SileroVAD` (onnxruntime, CPU) — the production provider for every model profile. It
keeps the same `frame_samples = 512` at 16 kHz so a threshold configured for one provider is
frame-identical for the other, which is the whole reason the energy detector uses that window
instead of a convenient one.
"""

from __future__ import annotations

from app.inference.vad.energy_vad import EnergyVAD

__all__ = ["EnergyVAD"]
