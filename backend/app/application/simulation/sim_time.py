"""Simulated time — one pure function (SPEC §39, D7, HLD `40-realtime-protocol.md` §40.5).

D7: "sim time is derived from the persisted `started_at` plus paused intervals, so a restart or
refresh never resets a session (§39)". Both inputs of that derivation are columns of
`simulation_sessions` — `started_at` (a wall-clock `timestamptz`) and `paused_total_ms` — so the
whole computation survives a process death, which is exactly what SPEC §39's "never silently reset
the simulation" asks for. Nothing here reads a clock: the caller supplies the elapsed wall-clock
milliseconds, and it gets them from `app.application.timebase.session_offset_ms`, the one function
that turns `(Clock.now(), session.started_at)` into an offset. There is deliberately no second
implementation of that subtraction.

`Clock.monotonic_ms()` is never an input. Its origin is the process, so it dies with the process
and a restart would shift every later offset against a different zero.

The same function converts a persisted `SessionEvent`'s `monotonic_offset_ms` into the simulated
offset a `PendingAction` carries: event offsets are wall-clock based for the same §39 reason, so
scaling them is the same operation as scaling the tick's own elapsed time.
"""

from __future__ import annotations

__all__ = ["sim_ms"]


def sim_ms(real_elapsed_ms: int, paused_total_ms: int, time_scale: float) -> int:
    """`floor(max(0, real_elapsed_ms - paused_total_ms) * time_scale)`.

    A negative running time is clamped to `0` rather than allowed to go negative (a session whose
    recorded pause total momentarily exceeds its elapsed time is at simulated time zero, not
    before it), and the product is truncated rather than rounded, so simulated time never
    overtakes the real time it is derived from.
    """
    running_ms = max(0, real_elapsed_ms - paused_total_ms)
    return int(running_ms * time_scale)
