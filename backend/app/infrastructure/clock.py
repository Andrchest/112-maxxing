"""`SystemClock` — the production `Clock` adapter (D5).

This is the one module in the backend that is allowed to read the machine's clock: `app.domain`
may not import `time` at all and `app.application` goes through the `Clock` port, so every
`timestamp_utc` and every `monotonic_offset_ms` in the system originates here.

`time.monotonic_ns()` (not `time.time()`) backs `monotonic_ms()`, so a wall-clock adjustment
during a running simulation cannot make sim time jump or go backwards.
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
        """A monotonically non-decreasing millisecond counter with an arbitrary origin."""
        return time.monotonic_ns() // 1_000_000
