"""`LoginGuard` — the counters and the doubling wait, in isolation (I7 E51, G5; ТЗ ¶295).

No Redis, no HTTP: `InMemoryLoginAttemptStore` stands in for `RedisLoginAttemptStore`
(`app.application.testing.fakes`), and its `expire_now` simulates a window lapsing without the
suite waiting `SIM_LOGIN_WINDOW_S`. The real Redis adapter, the router wiring and the audit row are
`tests.api.test_login_throttle`'s job.
"""

from __future__ import annotations

import pytest
from app.application.auth.login_guard import LoginGuard, LoginThrottledError
from app.application.testing.fakes import InMemoryLoginAttemptStore

MAX_FAILURES = 5
#: Manager follow-up: a classroom sits behind one NAT IP, so the IP threshold is higher than the
#: username one — 20 trainees each failing a few times must not lock the whole room.
MAX_FAILURES_PER_IP = 30
WINDOW_S = 600


def build() -> tuple[LoginGuard, InMemoryLoginAttemptStore]:
    store = InMemoryLoginAttemptStore()
    guard = LoginGuard(
        store,
        max_failures=MAX_FAILURES,
        max_failures_per_ip=MAX_FAILURES_PER_IP,
        window_s=WINDOW_S,
    )
    return guard, store


async def test_under_the_threshold_nothing_is_throttled() -> None:
    guard, _ = build()

    for _ in range(MAX_FAILURES):
        await guard.check(username="trainee1", client_ip="10.0.0.1")
        await guard.record_failure(username="trainee1", client_ip="10.0.0.1")


async def test_the_check_past_the_threshold_raises_with_a_5s_retry_after() -> None:
    guard, _ = build()
    for _ in range(MAX_FAILURES):
        await guard.record_failure(username="trainee1", client_ip="10.0.0.1")

    with pytest.raises(LoginThrottledError) as excinfo:
        await guard.check(username="trainee1", client_ip="10.0.0.1")

    assert excinfo.value.retry_after_s == 5
    assert excinfo.value.code == "LOGIN_THROTTLED"


async def test_the_retry_after_doubles_and_caps_at_60() -> None:
    guard, _ = build()
    for _ in range(MAX_FAILURES):
        await guard.record_failure(username="trainee1", client_ip="10.0.0.1")

    seen: list[int] = []
    for _ in range(6):
        with pytest.raises(LoginThrottledError) as excinfo:
            await guard.check(username="trainee1", client_ip="10.0.0.1")
        seen.append(excinfo.value.retry_after_s)

    assert seen == [5, 10, 20, 40, 60, 60]


async def test_a_success_clears_only_the_username_s_counter() -> None:
    guard, store = build()
    for _ in range(MAX_FAILURES - 1):
        await guard.record_failure(username="trainee1", client_ip="10.0.0.1")

    await guard.record_success(username="trainee1")

    assert await store.count("login_throttle:username:trainee1") == 0
    # The client IP kept its failures: a shared IP trying many accounts stays tracked.
    assert await store.count("login_throttle:ip:10.0.0.1") == MAX_FAILURES - 1


async def test_the_username_counter_locks_at_its_own_lower_threshold() -> None:
    guard, _ = build()
    for _ in range(MAX_FAILURES):
        await guard.record_failure(username="attacker", client_ip="10.0.0.1")

    with pytest.raises(LoginThrottledError):
        await guard.check(username="attacker", client_ip="10.0.0.1")


async def test_the_ip_counter_is_not_locked_by_max_failures_worth_of_different_usernames() -> None:
    """Manager follow-up: `SIM_LOGIN_MAX_FAILURES` (5) failures spread over 5 DIFFERENT usernames
    from one classroom IP must not throttle a 6th trainee at that same address."""
    guard, _ = build()
    for n in range(MAX_FAILURES):
        await guard.record_failure(username=f"trainee{n}", client_ip="10.0.0.1")

    # Neither this username (0 failures of its own) nor the IP (only 5, well under its own 30) is
    # over its threshold.
    await guard.check(username="trainee-next", client_ip="10.0.0.1")


async def test_the_ip_counter_locks_at_its_own_higher_threshold() -> None:
    """Manager follow-up: the IP counter still throttles once IT crosses `SIM_LOGIN_MAX_
    FAILURES_PER_IP` (30), even though no single username came anywhere near 5 failures."""
    guard, _ = build()
    for n in range(MAX_FAILURES_PER_IP):
        await guard.record_failure(username=f"trainee{n}", client_ip="10.0.0.1")

    with pytest.raises(LoginThrottledError) as excinfo:
        await guard.check(username="trainee-next", client_ip="10.0.0.1")

    # The IP just crossed its own threshold (count == 30, excess 0): the first block waits 5 s,
    # same base as the username counter's own first block.
    assert excinfo.value.retry_after_s == 5


async def test_a_different_username_and_ip_are_unaffected() -> None:
    guard, _ = build()
    for _ in range(MAX_FAILURES):
        await guard.record_failure(username="attacker", client_ip="10.0.0.1")

    # A fresh username from a fresh ip: neither counter has any failures recorded against it.
    await guard.check(username="someone-else", client_ip="10.0.0.2")


async def test_a_lapsed_window_stops_throttling() -> None:
    """`expire_now` stands in for `SIM_LOGIN_WINDOW_S` running out (module docstring)."""
    guard, store = build()
    for _ in range(MAX_FAILURES):
        await guard.record_failure(username="trainee1", client_ip="10.0.0.1")
    with pytest.raises(LoginThrottledError):
        await guard.check(username="trainee1", client_ip="10.0.0.1")

    store.expire_now("login_throttle:username:trainee1")
    store.expire_now("login_throttle:ip:10.0.0.1")

    await guard.check(username="trainee1", client_ip="10.0.0.1")


async def test_username_matching_is_case_insensitive() -> None:
    guard, _ = build()
    for _ in range(MAX_FAILURES):
        await guard.record_failure(username="Trainee1", client_ip="10.0.0.1")

    with pytest.raises(LoginThrottledError):
        await guard.check(username="trainee1", client_ip="10.0.0.9")
