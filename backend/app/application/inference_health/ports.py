"""Ports of `app.application.inference_health` (D2, D8).

One port, narrow on purpose: `clearInferenceFatal` is a single Redis side effect and nothing the
domain reasons about. It lives here rather than in `app.application.ports` for the same reason
`app.application.reports.explanation.ports` does — it is used by exactly one package.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["InferenceFatalLatch"]


@runtime_checkable
class InferenceFatalLatch(Protocol):
    """The un-expiring `voice:health:fatal` mirror of §4.3, seen as an operation."""

    async def clear(self) -> bool:
        """Clear the latch; `True` when one was latched, `False` when there was nothing to clear.

        Clearing announces the transition on `voice:health` so the change reaches every ACTIVE
        session's log (`openapi.yaml`, `clearInferenceFatal` `x-emits`). It never makes a service
        `READY`: only the next heartbeat can do that.
        """
        ...
