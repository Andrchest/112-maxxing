"""Shared inference-adapter exceptions (E12).

Defined once here, not per-adapter, so that callers (the pipeline, `workers/voice_agent/health.py`'s
`guard_inference`, the E18 health state machine) can catch a single stable type regardless of which
concrete provider raised it (SPEC §19 — application code never names a concrete model).
"""

from __future__ import annotations

__all__ = ["InferenceOutOfMemoryError", "ModelNotAvailableError"]


class ModelNotAvailableError(RuntimeError):
    """A model file/directory a provider needs is missing.

    Raised from `warm_up()` (or the constructor, for providers that check eagerly) with a message
    naming the expected path and the `make` target that fetches it, so a developer without the
    model files gets an actionable error instead of an import-time crash or a silent no-op.
    """


class InferenceOutOfMemoryError(RuntimeError):
    """A CUDA/accelerator allocation failed with an out-of-memory condition.

    A distinct type (rather than a bare `RuntimeError` or letting `torch.cuda.OutOfMemoryError`
    leak through the port) so that downstream code — the E18 health state machine's
    `guard_inference` (`docs/hld/60-inference-ops.md` §4.4) — can key off of it without importing
    torch itself.
    """
