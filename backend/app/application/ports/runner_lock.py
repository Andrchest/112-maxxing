"""`RunnerLock` port — `lock:session:{session_id}:runner` (HLD `40-realtime-protocol.md` §40.6, D7).

D7 gives every ACTIVE session exactly one ticking `SimulationRunner`, and §40.6's key table makes
the lock a Redis string holding the owning backend instance id with `SIM_RUNNER_LOCK_TTL_S`
(default 30) and a refresh every 10 s.

The three operations are the three the runner needs and nothing more:

* `acquire` is `SET key owner NX EX ttl` — it succeeds for exactly one instance;
* `refresh` extends the TTL **only while this instance still owns the key**, so an instance that
  was declared dead (its TTL expired and another instance adopted the session) learns about it from
  a `False` and stops ticking;
* `release` is a compare-and-delete on the owner, so an instance can never delete a lock another
  instance has already taken over.

Losing the lock costs liveness only, never correctness (§40.6): a tick derives its effects from
persisted state and the `seq_no` row lock of §20.8 serialises two appenders anyway.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import SessionId

__all__ = ["RunnerLock"]


@runtime_checkable
class RunnerLock(Protocol):
    """Single-runner-per-session lock (D7, §40.6)."""

    async def acquire(self, session_id: SessionId, owner: str, ttl_s: int) -> bool:
        """`SET NX EX`: `True` when this call took the lock for `owner`."""
        ...

    async def refresh(self, session_id: SessionId, owner: str, ttl_s: int) -> bool:
        """Extend the TTL while `owner` still holds the lock; `False` when it does not."""
        ...

    async def release(self, session_id: SessionId, owner: str) -> bool:
        """Delete the lock if and only if `owner` holds it; `True` when it was deleted."""
        ...
