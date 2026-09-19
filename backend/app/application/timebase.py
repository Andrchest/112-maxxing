"""Session time base — where a `monotonic_offset_ms` comes from (SPEC §39, D7).

SPEC §39 requires a session to survive a backend restart: after the process comes back, the
already-persisted events must still line up with the ones appended afterwards. A counter whose
origin is the *process* — `time.monotonic()` and anything derived from it — cannot do that: its
origin is lost with the process, so the first event appended after a restart would be offset
against a different zero than the events before it.

The offset is therefore derived from persisted state only: the session's `started_at` instant,
which lives in the `simulation_sessions` row, and the current wall-clock instant taken from the
injected `Clock`. Both survive a restart, so the same event gets the same offset no matter how
many times the backend was restarted in between.

`Clock.monotonic_ms()` keeps its own, narrower job: measuring a latency *inside* one process (the
voice metrics of §40 / SPEC §31). It is never the source of an event offset.
"""

from __future__ import annotations

from datetime import datetime, timedelta

__all__ = ["session_offset_ms"]

_ONE_MS = timedelta(milliseconds=1)


def session_offset_ms(now: datetime, started_at: datetime | None) -> int:
    """Milliseconds from `started_at` to `now`, the offset an event is stamped with (SPEC §39).

    `started_at is None` — the session has not started yet — is offset `0`: `SESSION_STARTED` is
    itself the origin, and everything before it shares that zero. A `now` earlier than
    `started_at` (a wall clock adjusted backwards) is clamped to `0` rather than producing a
    negative offset; the fraction of a millisecond is truncated, never rounded up, so the offset
    never overtakes real time.

    Both instants must be timezone-aware; mixing an aware and a naive `datetime` raises
    `TypeError` from the subtraction, which is the correct outcome — a naive instant here would be
    a bug in the caller's `Clock`.
    """
    if started_at is None:
        return 0
    # `timedelta // timedelta` is exact integer floor division — no float rounding to reason about.
    return max(0, (now - started_at) // _ONE_MS)
