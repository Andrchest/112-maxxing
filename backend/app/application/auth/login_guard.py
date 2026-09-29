"""`LoginGuard` — brute-force protection on `loginUser` (I7 E51, G5; ТЗ ¶295 «Защита от
несанкционированного доступа», ¶124 «Соответствие требованиям ИБ»).

Two counters per attempt, one keyed by the attempted `username` and one by the caller's
`client_ip`, each over `LoginAttemptStore` (Redis in production, `InMemoryLoginAttemptStore` in
tests), inside the same `SIM_LOGIN_WINDOW_S` window (default 600 s) but with **different**
thresholds: `SIM_LOGIN_MAX_FAILURES` (default 5) for the username, `SIM_LOGIN_MAX_FAILURES_PER_IP`
(default 30, manager follow-up) for the client IP. A classroom sits behind one NAT address, so the
IP threshold has to tolerate many trainees each failing a few times without locking the whole room
— it still throttles a single address hammering many accounts, just at a higher count. Past its
threshold either counter throttles every further attempt on that key until the window lapses, with
a wait that doubles every throttled attempt (5 s, 10 s, 20 s, 40 s, capped at 60 s).

The router calls `check()` **before** `Login` verifies anything, so a throttled request never pays
the password-hasher's work and never learns whether the credential would have matched — the same
"no oracle" posture `app.application.auth.login.Login` already holds for username enumeration. A
successful login clears the *username's* counter only (`record_success`): the client IP's counter
is left alone, because a shared IP (a classroom NAT) trying many different accounts should stay
throttled even after one of them finally succeeds.
"""

from __future__ import annotations

from app.application.ports.login_attempts import LoginAttemptStore
from app.domain.common.errors import DomainError

__all__ = ["LoginGuard", "LoginThrottledError"]

#: The first throttled attempt on a key waits this long; each further throttled attempt on the
#: same key doubles it, capped at `_MAX_RETRY_AFTER_S` (the owner's amendment to G5's design).
_BASE_RETRY_AFTER_S = 5
_MAX_RETRY_AFTER_S = 60


class LoginThrottledError(DomainError):
    """Too many failed attempts for this username or client IP (`429 LOGIN_THROTTLED`)."""

    code = "LOGIN_THROTTLED"

    def __init__(self, retry_after_s: int) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(f"too many login attempts; retry after {retry_after_s}s")


def _username_key(username: str) -> str:
    """`login_throttle:username:{username}`, case-folded so `Trainee1`/`trainee1` share a bucket."""
    return f"login_throttle:username:{username.lower()}"


def _ip_key(client_ip: str) -> str:
    """`login_throttle:ip:{client_ip}`."""
    return f"login_throttle:ip:{client_ip}"


def _retry_after_s(count: int, max_failures: int) -> int:
    """5 s, doubling for every failure past `max_failures`, capped at 60 s."""
    excess = max(count - max_failures, 0)
    # `int.__pow__`'s typeshed stub returns `Any` (a negative exponent would give a float), so an
    # explicit `int` annotation is what keeps this an `int` return rather than `no-any-return`.
    capped: int = min(_BASE_RETRY_AFTER_S * (2**excess), _MAX_RETRY_AFTER_S)
    return capped


class LoginGuard:
    """Brute-force protection wired around `Login` by `app.api.routers.auth.login_user`."""

    def __init__(
        self,
        store: LoginAttemptStore,
        *,
        max_failures: int,
        max_failures_per_ip: int,
        window_s: int,
    ) -> None:
        self._store = store
        self._max_failures = max_failures
        self._max_failures_per_ip = max_failures_per_ip
        self._window_s = window_s

    async def check(self, *, username: str, client_ip: str | None) -> None:
        """Raise `LoginThrottledError` when `username` or `client_ip` is currently throttled.

        Every key that is already over its own threshold is also incremented here, so a client
        that ignores `Retry-After` and retries immediately sees the wait grow instead of staying
        flat.
        """
        candidates: list[tuple[str, int]] = [(_username_key(username), self._max_failures)]
        if client_ip:
            candidates.append((_ip_key(client_ip), self._max_failures_per_ip))

        blocked: list[str] = []
        retry_after = 0
        for key, threshold in candidates:
            count = await self._store.count(key)
            if count >= threshold:
                blocked.append(key)
                retry_after = max(retry_after, _retry_after_s(count, threshold))

        if not blocked:
            return
        for key in blocked:
            await self._store.increment(key, window_s=self._window_s)
        raise LoginThrottledError(retry_after)

    async def record_failure(self, *, username: str, client_ip: str | None) -> None:
        """One more failure against both the username's and the client IP's counters."""
        await self._store.increment(_username_key(username), window_s=self._window_s)
        if client_ip:
            await self._store.increment(_ip_key(client_ip), window_s=self._window_s)

    async def record_success(self, *, username: str) -> None:
        """Clear the username's counter; the client IP's counter is left untouched (see above)."""
        await self._store.clear(_username_key(username))
