"""`session_offset_ms` — the one source of an event's `monotonic_offset_ms` (SPEC §39, D7).

SPEC §39 wants a session to survive a backend restart, so the offset is derived from two things
that outlive the process: the session's persisted `started_at` and the wall-clock `now`. These
tests pin exactly that arithmetic — including what a restart makes observable, that the same pair
of instants always yields the same offset no matter which process asks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from app.application.timebase import session_offset_ms

STARTED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_offset_is_zero_before_the_session_started() -> None:
    """`started_at is None`: `SESSION_STARTED` is the origin, so everything earlier shares its 0."""
    assert session_offset_ms(STARTED_AT + timedelta(hours=3), None) == 0


def test_offset_at_the_origin_is_zero() -> None:
    assert session_offset_ms(STARTED_AT, STARTED_AT) == 0


@pytest.mark.parametrize(
    "elapsed,expected",
    [
        (timedelta(milliseconds=1), 1),
        (timedelta(milliseconds=1500), 1500),
        (timedelta(seconds=90), 90_000),
        (timedelta(hours=2), 7_200_000),
    ],
)
def test_offset_is_the_elapsed_milliseconds(elapsed: timedelta, expected: int) -> None:
    assert session_offset_ms(STARTED_AT + elapsed, STARTED_AT) == expected


def test_sub_millisecond_elapsed_time_is_floored_not_rounded() -> None:
    """Truncation, never rounding up: an offset must not overtake real time."""
    assert session_offset_ms(STARTED_AT + timedelta(microseconds=1999), STARTED_AT) == 1


def test_a_backwards_wall_clock_is_clamped_to_zero() -> None:
    """A negative offset is not representable in `session_events.monotonic_offset_ms`."""
    assert session_offset_ms(STARTED_AT - timedelta(seconds=5), STARTED_AT) == 0


def test_the_offset_depends_only_on_persisted_state() -> None:
    """The restart property: same `(now, started_at)` pair, same offset — no process involved."""
    now = STARTED_AT + timedelta(milliseconds=4242)
    assert session_offset_ms(now, STARTED_AT) == session_offset_ms(now, STARTED_AT) == 4242


def test_instants_in_other_timezones_are_compared_as_instants() -> None:
    """`started_at` comes back from PostgreSQL aware; the offset compares instants, not fields."""
    elsewhere = (STARTED_AT + timedelta(milliseconds=250)).astimezone(timezone(timedelta(hours=3)))
    assert session_offset_ms(elsewhere, STARTED_AT) == 250
