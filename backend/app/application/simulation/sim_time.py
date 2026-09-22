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

E17 (manager ruling R1) gave `paused_total_ms` its one writer and this module its one reader of
the session row. **Simulated time does not run during a role transition**: while the session sits
in `ROLE_TRANSITION` the clock is frozen at the offset the transition began at
(`SimulationSession.role_transition_started_offset_ms`), and `finish_role_transition` banks the
wall-clock length of that interval into `paused_total_ms` so the clock resumes from exactly the
value it froze at. Three quantities come out of that, and they are deliberately named apart:

* `running_ms(session, now)` — **the** session offset: wall-clock milliseconds since
  `started_at`, minus every pause already banked, frozen during an open transition. This is what
  an appended event's `monotonic_offset_ms` is stamped with, so a DEADLINE scoring rule (which
  subtracts two of those offsets) never counts a hand-over pause, and so `world_state_loader`
  needs no per-event pause attribution: the offset already excludes the pauses that preceded it.
* `sim_now_ms(session, now)` — `running_ms` scaled by `time_scale`; simulated "now".
* `transition_clock_ms(session, now)` — the same subtraction **without** the freeze. The
  `ROLE_TRANSITION` pause is measured against this one, because a clock frozen at
  `transition_started_ms` could never reach `transition_started_ms + transition_pause_seconds`
  and the hand-over would deadlock. It is the countdown the client is shown, nothing else.

Because the freeze makes the running clock depend on `state` and the transition stamp as well,
every reader takes the whole session row rather than three loose integers — the "one function
that is the single source of sim now" R1 asks for. The low-level `sim_ms` stays for the pure
unit tests and for callers holding a bare offset.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from app.application.timebase import session_offset_ms
from app.domain.enums import SessionState

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle at runtime
    from app.domain.session.session import SimulationSession

__all__ = ["running_ms", "sim_ms", "sim_now_ms", "transition_clock_ms"]


def sim_ms(real_elapsed_ms: int, paused_total_ms: int, time_scale: float) -> int:
    """`floor(max(0, real_elapsed_ms - paused_total_ms) * time_scale)`.

    A negative running time is clamped to `0` rather than allowed to go negative (a session whose
    recorded pause total momentarily exceeds its elapsed time is at simulated time zero, not
    before it), and the product is truncated rather than rounded, so simulated time never
    overtakes the real time it is derived from.
    """
    running_ms = max(0, real_elapsed_ms - paused_total_ms)
    return int(running_ms * time_scale)


def transition_clock_ms(session: SimulationSession, now: datetime) -> int:
    """Pause-excluded wall elapsed **without** the role-transition freeze (see the module doc).

    `max(0, session_offset_ms(now, started_at) - paused_total_ms)`. The only two legitimate
    readers are the `finish_role_transition` pause guard and the `SessionDetail` countdown that
    mirrors it: both compare against the `ROLE_TRANSITION_STARTED` event's own offset, and both
    must keep advancing while the session is paused.
    """
    return max(0, session_offset_ms(now, session.started_at) - session.paused_total_ms)


def running_ms(session: SimulationSession, now: datetime) -> int:
    """The session's offset in milliseconds — the number an appended event is stamped with (R1).

    Equal to `transition_clock_ms` outside a role transition. Inside one it is clamped to
    `role_transition_started_offset_ms`, the offset the transition began at, so the clock stands
    still for as long as the hand-over lasts and resumes from that same value afterwards
    (`finish_role_transition` adds the interval's wall-clock length to `paused_total_ms`, which
    makes the two expressions agree exactly at the resume instant).

    The clamp is a `min`, not an assignment: a wall clock nudged backwards during the pause must
    not make the frozen value jump *forward*.
    """
    unfrozen = transition_clock_ms(session, now)
    frozen = session.role_transition_started_offset_ms
    if session.state is SessionState.ROLE_TRANSITION and frozen is not None:
        return min(unfrozen, frozen)
    return unfrozen


def sim_now_ms(session: SimulationSession, now: datetime) -> int:
    """Simulated "now" — `running_ms` scaled by the session's `time_scale` (SPEC §39, D7)."""
    return int(running_ms(session, now) * session.time_scale)
