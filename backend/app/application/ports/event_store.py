"""`EventStore` port — the append-only audit source (HLD `20-db-schema.md` §20.6, §20.8, D5).

`append` runs inside the caller's Unit of Work transaction and allocates `seq_no` under the row
lock of §20.8, so several processes (backend, voice-agent) can append to one session safely.
`read` is the replay/resume read path (`ix_session_events_session_seq`).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Protocol, runtime_checkable

from app.domain.common.ids import SessionId
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType

__all__ = ["EventStore"]


@runtime_checkable
class EventStore(Protocol):
    """Append and read `session_events` rows."""

    async def append(
        self, session_id: SessionId, events: Sequence[DomainEvent]
    ) -> list[SessionEvent]:
        """Append `events` to `session_id`'s log and return them with their allocated `seq_no`.

        The numbers are contiguous and allocated under `SELECT … FOR UPDATE` on
        `simulation_sessions.next_seq_no` (§20.8), inside the caller's transaction. An empty
        `events` sequence is a no-op that allocates nothing and returns `[]`.
        """
        ...

    async def read(
        self, session_id: SessionId, after_seq_no: int = 0, limit: int | None = None
    ) -> list[SessionEvent]:
        """Every event of `session_id` with `seq_no > after_seq_no`, ordered by `seq_no`."""
        ...

    async def last_seq_no(
        self, session_id: SessionId, event_types: Collection[EventType] | None = None
    ) -> int:
        """`MAX(seq_no)` for `session_id`, `0` when the log is empty (HLD §40.2, §40.6).

        `event_types` narrows the maximum to those types, which is how a caller asks for "the
        highest `seq_no` **visible to this role**": pass the role's
        `DataVisibilityPolicy.visible_event_types`. `None` means every type, which is the
        instructor's answer and the heartbeat's PostgreSQL fallback when the
        `session:{id}:last_seq_no` cache key is missing (§40.6).

        The SQL stays in the adapter: this is a `MAX` with an optional `IN`, not a read of the
        rows themselves, so a session with a hundred thousand events costs one index probe.
        """
        ...
