"""`EventStore` port — the append-only audit source (HLD `20-db-schema.md` §20.6, §20.8, D5).

`append` runs inside the caller's Unit of Work transaction and allocates `seq_no` under the row
lock of §20.8, so several processes (backend, voice-agent) can append to one session safely.
`read` is the replay/resume read path (`ix_session_events_session_seq`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.domain.common.ids import SessionId
from app.domain.events.session_event import DomainEvent, SessionEvent

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
