"""`Clock` port (D5: "from the injected `Clock` port (never `time.time()` in domain)").

Two readings are needed by the event store and by the use cases above it:

* `now()` — the wall-clock instant written to `session_events.timestamp_utc`, always timezone-aware
  and UTC. It is also the input to `app.application.timebase.session_offset_ms`, which is where an
  event's `monotonic_offset_ms` comes from;
* `monotonic_ms()` — a monotonically non-decreasing millisecond counter for measuring a latency
  *inside one process* (the voice metrics of SPEC §31 / §40). Its origin is the process, so it dies
  with the process and is **never** the source of an event offset (SPEC §39, D7).

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
        """A monotonically non-decreasing counter in milliseconds, for in-process latencies.

        Its origin is arbitrary and belongs to the running process; only differences taken within
        that one process are meaningful. Use it to measure how long something took — a voice
        round-trip (SPEC §31) — and never to stamp an event: a session survives a backend restart
        (SPEC §39, D7), which this counter does not, so an event's `monotonic_offset_ms` is
        computed by `app.application.timebase.session_offset_ms` from `now()` and the session's
        persisted `started_at`.
        """
        ...
