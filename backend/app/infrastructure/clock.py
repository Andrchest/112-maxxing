"""`SystemClock` — the production `Clock` adapter (D5).

This is the one module in the backend that is allowed to read the machine's clock: `app.domain`
may not import `time` at all and `app.application` goes through the `Clock` port, so every
`timestamp_utc` in the system originates here.

`time.monotonic_ns()` (not `time.time()`) backs `monotonic_ms()`, so an in-process latency
measurement cannot be distorted by a wall-clock adjustment. That counter's origin is this process,
though, so it is deliberately *not* what an event offset is built from: a session survives a
backend restart (SPEC §39, D7), so `monotonic_offset_ms` is derived from persisted state by
`app.application.timebase.session_offset_ms`, using `now()` and the session's `started_at`.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

__all__ = ["SystemClock"]


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        """The current instant, timezone-aware and UTC."""
        return datetime.now(UTC)

    def monotonic_ms(self) -> int:
        """A monotonically non-decreasing millisecond counter with a process-local origin.

        For latencies measured inside this process only (SPEC §31); never an event offset.
        """
        return time.monotonic_ns() // 1_000_000
