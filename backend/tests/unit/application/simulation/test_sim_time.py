"""`sim_ms` — the one simulated-time function (SPEC §39, D7).

`sim_ms` is pure and total, so it is tested here rather than through a session: the *wiring* (that
`tick_session` feeds it `session_offset_ms(clock.now(), started_at)` and the session's own
`paused_total_ms` / `time_scale`) is what the integration tests cover.

The second half of the file covers the three session-shaped functions E17 ruling R1 added on top
of it — `running_ms`, `sim_now_ms` and `transition_clock_ms` — which are equally pure: a whole
role transition, and a chain with two of them, is a sequence of `(row, wall instant)` pairs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.application.simulation.sim_time import (
    running_ms,
    sim_ms,
    sim_now_ms,
    transition_clock_ms,
)
from app.application.timebase import session_offset_ms
from app.domain.enums import (
    DDSStageState,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.session.session import SimulationSession

from tests.unit.domain.session import _builders as sb


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


# ---------------------------------------------------------------------------------------------
# The frozen clock across a role transition (E17 ruling R1)
# ---------------------------------------------------------------------------------------------
#
# `running_ms` / `sim_now_ms` / `transition_clock_ms` are the one source of "sim now" the readers
# share. They are pure functions of `(session row, wall now)`, so a whole hand-over is expressible
# here without a database: the row carries `state`, `paused_total_ms`,
# `role_transition_started_offset_ms` and `time_scale`, and nothing else is consulted.

STARTED_AT = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)


def _row(
    *,
    state: SessionState = SessionState.ACTIVE,
    paused_total_ms: int = 0,
    transition_started_offset_ms: int | None = None,
    time_scale: float = 1.0,
) -> SimulationSession:
    """A session row with nothing in it but the four fields the clock reads."""
    session = sb.build_session(
        session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE,
        state=state,
        stages=[
            sb.build_stage(
                order_index=0,
                role_type=RoleType.OPERATOR_112,
                state=Operator112StageState.STAGE_COMPLETED,
                participant_user_id=sb.user("trainee"),
            ),
            sb.build_stage(
                order_index=1,
                role_type=RoleType.DDS,
                state=DDSStageState.RECEIVED,
                participant_user_id=sb.user("trainee"),
            ),
        ],
    )
    return session.model_copy(
        update={
            "started_at": STARTED_AT,
            "paused_total_ms": paused_total_ms,
            "role_transition_started_offset_ms": transition_started_offset_ms,
            "time_scale": time_scale,
        }
    )


def _at(ms: int) -> datetime:
    return STARTED_AT + timedelta(milliseconds=ms)


def test_before_any_transition_the_clock_is_plain_elapsed_time() -> None:
    session = _row()
    assert running_ms(session, _at(0)) == 0
    assert running_ms(session, _at(30_000)) == 30_000
    assert sim_now_ms(session, _at(30_000)) == 30_000


def test_during_a_transition_the_clock_stands_still_at_the_offset_it_began_at() -> None:
    """E17 R1: simulated time does not run while the session is in `ROLE_TRANSITION`."""
    session = _row(state=SessionState.ROLE_TRANSITION, transition_started_offset_ms=30_000)
    assert running_ms(session, _at(30_000)) == 30_000
    assert running_ms(session, _at(35_000)) == 30_000
    assert running_ms(session, _at(90_000)) == 30_000
    # and the unfrozen clock the pause guard reads keeps advancing, or the pause could never end
    assert transition_clock_ms(session, _at(90_000)) == 90_000


def test_after_the_transition_the_clock_resumes_from_the_value_it_froze_at() -> None:
    """`finish_role_transition` banks the 60 s of wall clock, so 30 s is still 30 s."""
    resumed = _row(paused_total_ms=60_000)
    assert running_ms(resumed, _at(90_000)) == 30_000
    assert running_ms(resumed, _at(100_000)) == 40_000


def test_the_clock_is_continuous_across_the_whole_hand_over() -> None:
    """Frozen value, resume value and every sample in between form one non-decreasing sequence."""
    paused = _row(state=SessionState.ROLE_TRANSITION, transition_started_offset_ms=30_000)
    resumed = _row(paused_total_ms=60_000)
    samples = [running_ms(paused, _at(ms)) for ms in range(30_000, 90_001, 5_000)]
    samples += [running_ms(resumed, _at(ms)) for ms in range(90_000, 150_001, 5_000)]
    assert samples == sorted(samples)
    assert samples[0] == 30_000
    assert running_ms(paused, _at(90_000)) == running_ms(resumed, _at(90_000))


def test_two_transitions_bank_independently() -> None:
    """A three-role chain pauses twice; each pause is added, never replaced."""
    second = _row(
        state=SessionState.ROLE_TRANSITION,
        paused_total_ms=60_000,
        transition_started_offset_ms=200_000,
    )
    assert running_ms(second, _at(260_000)) == 200_000
    assert running_ms(second, _at(275_000)) == 200_000
    # the guard's clock is measured against the same `transition_started_ms` both times
    assert transition_clock_ms(second, _at(275_000)) == 215_000
    after = _row(paused_total_ms=60_000 + 15_000)
    assert running_ms(after, _at(275_000)) == 200_000
    assert running_ms(after, _at(300_000)) == 225_000


@pytest.mark.parametrize("scale,expected", [(0.5, 15_000), (2.0, 60_000), (10.0, 300_000)])
def test_the_freeze_happens_before_the_time_scale_is_applied(scale: float, expected: int) -> None:
    """`time_scale != 1`: the frozen offset is scaled, and it is still frozen."""
    session = _row(
        state=SessionState.ROLE_TRANSITION,
        transition_started_offset_ms=30_000,
        time_scale=scale,
    )
    assert sim_now_ms(session, _at(30_000)) == expected
    assert sim_now_ms(session, _at(120_000)) == expected


def test_a_stamp_left_behind_outside_a_transition_is_ignored() -> None:
    """Only `state is ROLE_TRANSITION` freezes: a stale stamp must not stop an `ACTIVE` session."""
    session = _row(state=SessionState.ACTIVE, transition_started_offset_ms=30_000)
    assert running_ms(session, _at(90_000)) == 90_000


def test_a_wall_clock_nudged_backwards_during_a_pause_does_not_move_the_frozen_value_forward() -> (
    None
):
    session = _row(state=SessionState.ROLE_TRANSITION, transition_started_offset_ms=30_000)
    assert running_ms(session, _at(10_000)) == 10_000
    assert running_ms(session, STARTED_AT - timedelta(seconds=5)) == 0
