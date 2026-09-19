"""`InferenceReadiness` port (D8, HLD `10-domain-model.md` §10.8 `guard_inference_ready`).

`READY --start--> ACTIVE` is guarded by "every required inference component is `READY`". The
domain guard only reads the projected verdict (`GuardRuntime.inference_ready`); deciding it means
asking the inference health registry, which is technology, so it is a port.

`REQUIRE_INFERENCE_READY` (D8) is *not* read here: whether the flag collapses the answer to `True`
is the calling use case's decision, and the use case receives the flag as a constructor argument —
the application layer never imports `app.config`.

TODO(E18): the real adapter over the inference health registry. E5 ships only
`app.application.testing.fakes.FakeInferenceReadiness`.
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
