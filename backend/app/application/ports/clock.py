"""`Clock` port (D5: "from the injected `Clock` port (never `time.time()` in domain)").

Two readings are needed by the event store and by the use cases above it:

* `now()` — the wall-clock instant written to `session_events.timestamp_utc`, always timezone-aware
  and UTC;
* `monotonic_ms()` — a monotonically non-decreasing millisecond counter, from which a use case
  derives a `DomainEvent.monotonic_offset_ms` (ms since `SESSION_STARTED`, D5) without ever calling
  `time` itself.

`app.domain` is forbidden from importing `time` at all and `app.application` never calls
`datetime.now()`; both go through this port, so a test can make time deterministic by injecting
`app.application.testing.fakes.FakeClock`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

__all__ = ["Clock"]


@runtime_checkable
class Clock(Protocol):
    """The only source of time for the application layer."""

    def now(self) -> datetime:
        """The current instant as a timezone-aware UTC `datetime`."""
        ...

    def monotonic_ms(self) -> int:
        """A monotonically non-decreasing counter in milliseconds.

        Its origin is arbitrary; only differences are meaningful. `monotonic_offset_ms` of an
        event is `monotonic_ms()` minus the value taken at `SESSION_STARTED` (D5).
        """
        ...
