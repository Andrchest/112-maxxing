"""`SqlAlchemyEventStore` — the `seq_no` allocation protocol of HLD `20-db-schema.md` §20.8 (D5).

The two statements of §20.8 step 1 are issued literally and in that order:

```sql
SELECT next_seq_no FROM simulation_sessions WHERE id = :session_id FOR UPDATE;
UPDATE simulation_sessions SET next_seq_no = next_seq_no + :event_count
 WHERE id = :session_id RETURNING next_seq_no - :event_count AS first_seq_no;
```

The `FOR UPDATE` row lock is what serialises concurrent appenders (backend and voice-agent), so
`uq_session_events_session_seq` can never be violated and the sequence has no gaps. Both statements
run inside the caller's Unit of Work transaction; the events are inserted with the numbers reserved
here (step 3) and published only after that transaction commits.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.clock import Clock
from app.db.models.events import SessionEvent as SessionEventRow
from app.domain.common.ids import SessionId
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.infrastructure.persistence.mappers import (
    event_row_values,
    session_event_from_row,
    session_event_of,
)

__all__ = ["SqlAlchemyEventStore", "UnknownSessionError"]

logger = logging.getLogger(__name__)

#: §20.8 step 1, verbatim. Taking the row lock first is the whole protocol: without it two
#: appenders could read the same `next_seq_no` and reserve overlapping ranges.
_LOCK_SESSION_ROW = sa.text(
    "SELECT next_seq_no FROM simulation_sessions WHERE id = :session_id FOR UPDATE"
)
_ALLOCATE_SEQ_NOS = sa.text(
    "UPDATE simulation_sessions SET next_seq_no = next_seq_no + :event_count"
    " WHERE id = :session_id RETURNING next_seq_no - :event_count AS first_seq_no"
)


class UnknownSessionError(LookupError):
    """Raised when an append targets a `simulation_sessions` row that does not exist."""


class SqlAlchemyEventStore:
    """`EventStore` over PostgreSQL, bound to one `AsyncSession` (one transaction)."""

    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        on_append: Callable[[SessionId, list[SessionEvent]], None] | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        #: The Unit of Work registers a callback here so it knows what to publish after commit.
        self._on_append = on_append

    async def append(
        self, session_id: SessionId, events: Sequence[DomainEvent]
    ) -> list[SessionEvent]:
        """Allocate contiguous `seq_no`s under the §20.8 row lock and insert the events."""
        if not events:
            return []

        first_seq_no = await self._allocate(session_id, len(events))
        timestamp_utc = self._clock.now()

        rows: list[dict[str, Any]] = []
        appended: list[SessionEvent] = []
        for offset, event in enumerate(events):
            values = event_row_values(session_id, event, first_seq_no + offset, timestamp_utc)
            rows.append(values)
            appended.append(session_event_of(session_id, event, values))

        await self._session.execute(sa.insert(SessionEventRow), rows)

        if self._on_append is not None:
            self._on_append(session_id, appended)
        return appended

    async def read(
        self, session_id: SessionId, after_seq_no: int = 0, limit: int | None = None
    ) -> list[SessionEvent]:
        """Every event with `seq_no > after_seq_no`, ordered by `seq_no` (§20.6 read path)."""
        table = SessionEventRow.__table__
        statement = (
            sa.select(table)
            .where(
                table.c.session_id == UUID(str(session_id)),
                table.c.seq_no > after_seq_no,
            )
            .order_by(table.c.seq_no)
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self._session.execute(statement)
        return [session_event_from_row(row._mapping) for row in result.all()]

    async def _allocate(self, session_id: SessionId, event_count: int) -> int:
        """§20.8 step 1: lock the session row, then reserve `event_count` numbers."""
        parameters = {"session_id": UUID(str(session_id)), "event_count": event_count}
        locked = await self._session.execute(_LOCK_SESSION_ROW, parameters)
        if locked.one_or_none() is None:
            raise UnknownSessionError(f"no simulation_sessions row {session_id}")
        allocated = await self._session.execute(_ALLOCATE_SEQ_NOS, parameters)
        return int(allocated.scalar_one())
