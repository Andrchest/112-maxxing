"""`IdempotencyStore` port — `idempotency:{user_id}:{client_command_id}` (HLD §40.6, D5).

§40.6's key table: *"the first response body of that command"*, TTL `IDEMPOTENCY_TTL_S` (default
300), written and read by the backend command handlers. `setCardField` carries the optional
`client_command_id` that keys it (`openapi.yaml`), so a retried command returns the first
response instead of appending a second revision.

**Redis is never authoritative here.** §40.6 states the loss behaviour itself: *"Loss ⇒ a retried
command is re-evaluated; setting a field to its current value is already a no-op, so the worst
case is a duplicate revision of a genuinely changed value."* A miss therefore degrades to
re-evaluating the command against PostgreSQL, which is the source of truth — it never fails the
command, and it never makes the stored copy the thing a later read believes.

The value is an opaque string as far as this port is concerned; the use case that owns the key
decides how to serialise its own response (`SetCardField` uses the JSON of its result view).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.common.ids import UserId

__all__ = ["IdempotencyStore", "idempotency_key"]


def idempotency_key(user_id: UserId, client_command_id: UUID) -> str:
    """`idempotency:{user_id}:{client_command_id}` (§40.6), UUIDs in canonical lowercase form.

    Keyed by the *user*, not by the session: the id is chosen by one client, and a second client
    that happened to draw the same UUID must not be handed someone else's response body.
    """
    return f"idempotency:{str(user_id).lower()}:{str(client_command_id).lower()}"


@runtime_checkable
class IdempotencyStore(Protocol):
    """A short-lived "this command already ran, here is what it answered" note (§40.6)."""

    async def get(self, key: str) -> str | None:
        """The stored response body for `key`, or `None` when there is none (or it expired).

        An implementation never raises: an unreachable store answers `None`, which re-evaluates
        the command — the documented degradation, never an error the trainee sees.
        """
        ...

    async def put(self, key: str, value: str) -> None:
        """Store `value` under `key` with the configured TTL; a failure is swallowed, not raised."""
        ...
