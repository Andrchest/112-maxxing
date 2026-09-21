"""`sim_ms` — the one simulated-time function (SPEC §39, D7).

`sim_ms` is pure and total, so it is tested here rather than through a session: the *wiring* (that
`tick_session` feeds it `session_offset_ms(clock.now(), started_at)` and the session's own
`paused_total_ms` / `time_scale`) is what the integration tests cover.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.application.simulation.sim_time import sim_ms
from app.application.timebase import session_offset_ms


def test_real_time_at_scale_one_is_simulated_time() -> None:
    assert sim_ms(0, 0, 1.0) == 0
    assert sim_ms(1, 0, 1.0) == 1
    assert sim_ms(180_000, 0, 1.0) == 180_000


@pytest.mark.parametrize(
    "scale,expected",
    [(0.5, 90_000), (1.0, 180_000), (2.0, 360_000), (10.0, 1_800_000)],
)
def test_time_scale_multiplies_the_running_time(scale: float, expected: int) -> None:
    assert sim_ms(180_000, 0, scale) == expected


def test_paused_time_is_subtracted_before_scaling() -> None:
    """A pause removes wall-clock time from the simulation; the scale applies to what is left."""
    assert sim_ms(100_000, 40_000, 1.0) == 60_000
    assert sim_ms(100_000, 40_000, 2.0) == 120_000


def test_a_pause_total_larger_than_the_elapsed_time_clamps_to_zero() -> None:
    """Never negative: a session whose pause total overruns its elapsed time is at time zero."""
    assert sim_ms(1_000, 5_000, 1.0) == 0
    assert sim_ms(0, 1, 3.0) == 0


def test_the_product_is_truncated_never_rounded_up() -> None:
    """Simulated time must not overtake the real time it is derived from."""
    assert sim_ms(3, 0, 0.5) == 1
    assert sim_ms(999, 0, 0.001) == 0


def test_the_function_is_monotonic_in_elapsed_time() -> None:
    previous = 0
    for elapsed in range(0, 10_000, 137):
        current = sim_ms(elapsed, 1_000, 1.7)
        assert current >= previous
        previous = current


def test_it_composes_with_session_offset_ms_rather_than_reimplementing_it() -> None:
    """The tick's `now_ms` is `sim_ms(session_offset_ms(now, started_at), …)` — SPEC §39, D7."""
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    now = started_at + timedelta(milliseconds=180_000)
    assert sim_ms(session_offset_ms(now, started_at), 0, 2.0) == 360_000


def test_a_session_that_has_not_started_is_at_simulated_time_zero() -> None:
    """`started_at is None` ⇒ offset 0 ⇒ simulated time 0, whatever the scale."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert sim_ms(session_offset_ms(now, None), 0, 5.0) == 0


def test_a_wall_clock_nudged_backwards_does_not_produce_negative_simulated_time() -> None:
    """`session_offset_ms` clamps, and `sim_ms` clamps again — SPEC §39 "never silently reset"."""
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    earlier = started_at - timedelta(seconds=30)
    assert sim_ms(session_offset_ms(earlier, started_at), 0, 1.0) == 0
