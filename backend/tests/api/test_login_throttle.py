"""`LoginGuard`: brute-force protection on `/api/v1/auth/login` (I7 E51, G5; ТЗ ¶295 «Защита от
несанкционированного доступа»).

Driven against the real application, PostgreSQL and the real `RedisLoginAttemptStore` — the same
discipline `test_audit_log.py` uses for this router. `_clean_login_throttle`
(`tests.api.conftest`) clears every `login_throttle:*` Redis key around each test, so the counters
below always start at zero regardless of what ran before.

The default settings (`SIM_LOGIN_MAX_FAILURES=5`, `SIM_LOGIN_MAX_FAILURES_PER_IP=30`,
`SIM_LOGIN_WINDOW_S=600`) are exercised as-is: both thresholds are reached fast enough that no test
here needs to wait for the window.
"""

from __future__ import annotations

import httpx
import pytest
from app.api.container import Container
from app.application.ports.audit_log import AuditAction, AuditFilter
from app.domain.common.ids import UserId

from tests.api.conftest import PASSWORDS

pytestmark = pytest.mark.integration


async def _fail(client: httpx.AsyncClient, username: str) -> httpx.Response:
    """One deliberately wrong-password attempt."""
    return await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "not-the-password"}
    )


async def test_the_failure_past_the_threshold_is_throttled_with_a_retry_after(
    client: httpx.AsyncClient, users: dict[str, UserId]
) -> None:
    """The first five failures are plain `401`s (`SIM_LOGIN_MAX_FAILURES=5`); the sixth is 429."""
    for _ in range(5):
        response = await _fail(client, "trainee1")
        assert response.status_code == 401

    throttled = await _fail(client, "trainee1")

    assert throttled.status_code == 429, throttled.text
    assert throttled.headers["content-type"].startswith("application/problem+json")
    body = throttled.json()
    assert body["code"] == "LOGIN_THROTTLED"
    assert body["retry_after_s"] == 5
    assert throttled.headers["retry-after"] == "5"


async def test_a_throttled_attempt_never_even_checks_the_correct_password(
    client: httpx.AsyncClient,
) -> None:
    """Once throttled, even the RIGHT password gets `429` — the guard runs before `Login`."""
    for _ in range(5):
        await _fail(client, "trainee1")

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "trainee1", "password": PASSWORDS["trainee1"]},
    )

    assert response.status_code == 429, response.text
    assert response.json()["code"] == "LOGIN_THROTTLED"


async def test_retry_after_doubles_every_further_throttled_attempt_capped_at_60(
    client: httpx.AsyncClient,
) -> None:
    """The owner's amendment: 5, 10, 20, 40, 60 s, then capped at 60 s."""
    for _ in range(5):
        await _fail(client, "trainee1")

    seen: list[int] = []
    for _ in range(6):
        response = await _fail(client, "trainee1")
        assert response.status_code == 429
        seen.append(int(response.headers["retry-after"]))

    assert seen == [5, 10, 20, 40, 60, 60]


async def test_a_successful_login_clears_the_username_s_counter(
    client: httpx.AsyncClient, users: dict[str, UserId]
) -> None:
    """Four failures (under the threshold), then a success: the next failure is a plain `401`
    again, proving the counter went back to zero rather than continuing to grow."""
    for _ in range(4):
        response = await _fail(client, "trainee2")
        assert response.status_code == 401

    success = await client.post(
        "/api/v1/auth/login", json={"username": "trainee2", "password": PASSWORDS["trainee2"]}
    )
    assert success.status_code == 200, success.text

    again = await _fail(client, "trainee2")
    assert again.status_code == 401


async def test_five_different_usernames_failing_once_each_do_not_throttle_the_shared_ip(
    client: httpx.AsyncClient,
) -> None:
    """Manager follow-up: a classroom's shared IP must tolerate `SIM_LOGIN_MAX_FAILURES` (5)
    worth of failures spread over different trainees without locking the next one out."""
    for n in range(5):
        response = await _fail(client, f"e51-g5-ip-probe-{n}")
        assert response.status_code == 401

    # Neither this username (never failed) nor the IP (only 5, well under its own 30) is throttled.
    not_throttled = await _fail(client, "e51-g5-ip-probe-distinct")
    assert not_throttled.status_code == 401


async def test_the_client_ip_counter_throttles_at_its_own_higher_threshold(
    client: httpx.AsyncClient,
) -> None:
    """`SIM_LOGIN_MAX_FAILURES_PER_IP=30` DIFFERENT unknown usernames from the same client IP
    reach the IP's own threshold even though no single username has failed more than once."""
    for n in range(30):
        response = await _fail(client, f"e51-g5-ip-cap-probe-{n}")
        assert response.status_code == 401

    throttled = await _fail(client, "e51-g5-ip-cap-probe-distinct")

    assert throttled.status_code == 429, throttled.text
    assert throttled.json()["code"] == "LOGIN_THROTTLED"


async def test_a_throttled_login_is_audited_with_the_username_and_no_password(
    client: httpx.AsyncClient, container: Container
) -> None:
    for _ in range(5):
        await _fail(client, "trainee1")
    throttled = await _fail(client, "trainee1")
    assert throttled.status_code == 429

    page = await container.audit_reader.page(
        AuditFilter(action=AuditAction.LOGIN_THROTTLED, limit=10)
    )

    assert page.items, "no LOGIN_THROTTLED audit row was written"
    entry = page.items[-1].entry
    assert entry.status == 429
    assert entry.user_id is None
    assert entry.target_ids["username"] == "trainee1"
    assert set(entry.target_ids) == {"username", "retry_after_s"}
    assert "not-the-password" not in entry.target_ids.values()
