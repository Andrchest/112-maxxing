"""`LoginAttemptStore` port — the failure counter behind `LoginGuard` (I7 E51, G5, ТЗ ¶295).

One counter per key (`login_throttle:username:{username}` or `login_throttle:ip:{client_ip}`,
built by `app.application.auth.login_guard`), incremented once per failed or blocked login
attempt, windowed so an old burst does not throttle forever.

Like `IdempotencyStore` and `RunnerLock`, Redis here is a cache of a security *signal*, never the
source of truth for anything a trainee is scored on: `app.application.auth.login_guard.LoginGuard`
degrades to "not throttled" when the store answers `0` (including because Redis is unreachable),
which trades a lost brute-force counter for never wrongly locking someone out of a class.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["LoginAttemptStore"]


@runtime_checkable
class LoginAttemptStore(Protocol):
    """A per-key failure counter with a fixed window (§40.6-style Redis port)."""

    async def count(self, key: str) -> int:
        """The counter's current value, or `0` when it does not exist (including unreachable)."""
        ...

    async def increment(self, key: str, *, window_s: int) -> int:
        """`INCR key`; the first increment also starts a `window_s`-second expiry.

        Returns the counter's new value, or `0` when the store could not be reached — the caller
        then treats this attempt as uncounted rather than raising.
        """
        ...

    async def clear(self, key: str) -> None:
        """Drop the counter (a successful login resets its username's history)."""
        ...
