"""`InferenceReadiness` port (D8, HLD `10-domain-model.md` §10.8 `guard_inference_ready`).

`READY --start--> ACTIVE` is guarded by "every required inference component is `READY`". The
domain guard only reads the projected verdict (`GuardRuntime.inference_ready`); deciding it means
asking the inference health registry, which is technology, so it is a port.

`REQUIRE_INFERENCE_READY` (D8) is *not* read here: whether the flag collapses the answer to `True`
is the calling use case's decision, and the use case receives the flag as a constructor argument —
the application layer never imports `app.config`.

The real adapter is `app.infrastructure.health.RedisInferenceReadiness` (E18-B): every one of
`llm`, `asr`, `tts`, `vad` must report `READY` in its `voice:health:{service}` heartbeat
(`60-inference-ops.md` §4.3). `app.application.testing.fakes.FakeInferenceReadiness` stays as the
test fake that flips the verdict without a voice-agent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["InferenceReadiness"]


@runtime_checkable
class InferenceReadiness(Protocol):
    """Is every required inference component `READY`?"""

    async def is_ready(self) -> bool:
        """`True` when every required component reports `READY` (D8)."""
        ...
