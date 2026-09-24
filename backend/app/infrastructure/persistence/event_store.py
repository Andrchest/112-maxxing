"""`SqlAlchemyEventStore` — the `seq_no` allocation protocol of HLD `20-db-schema.md` §20.8 (D5).

The two statements of §20.8 step 1 are issued in that order:

```sql
SELECT next_seq_no FROM simulation_sessions WHERE id = :session_id FOR NO KEY UPDATE;
UPDATE simulation_sessions SET next_seq_no = next_seq_no + :event_count
 WHERE id = :session_id RETURNING next_seq_no - :event_count AS first_seq_no;
```

The row lock is what serialises concurrent appenders (backend and voice-agent), so
`uq_session_events_session_seq` can never be violated and the sequence has no gaps. Both statements
run inside the caller's Unit of Work transaction; the events are inserted with the numbers reserved
here (step 3) and published only after that transaction commits.

**The lock mode is `FOR NO KEY UPDATE`, and that is the whole of R14** (E19-E3 bug #6). §20.8's
text says "FOR UPDATE", which is the strongest row lock PostgreSQL has, and it was taken literally
until E20. Every table the voice agent writes beside its events — `audio_segments`,
`transcript_segments`, `dialogue_turns`, `inference_metrics` — has a foreign key to
`simulation_sessions.id`, and PostgreSQL takes a `FOR KEY SHARE` lock on the **referenced** row for
each such insert. `VoiceEventAppender.append` writes those rows first and allocates the `seq_no`
afterwards, so its transaction already holds `FOR KEY SHARE` on the session row when it asks for
the allocation lock. `FOR UPDATE` conflicts with `FOR KEY SHARE`, so two such transactions each
held a lock the other had to wait for and PostgreSQL broke the cycle the only way it can:

```
asyncpg.exceptions.DeadlockDetectedError: deadlock detected
[SQL: SELECT next_seq_no FROM simulation_sessions WHERE id = $1 FOR UPDATE]
```

— which is what killed E19-E3's first real LiveKit run after two turns, and why that run had to be
repeated with `SIM_SIM_TICK_MS=10000` instead of the shipped 500.

`FOR NO KEY UPDATE` is exactly the mode the very next statement (an `UPDATE` of a non-key column)
takes anyway. It still conflicts with **itself**, which is the only property §20.8 needs — two
allocations of one session are still strictly serialised — and it is *compatible* with
`FOR KEY SHARE`, so a transaction that already wrote a child row can acquire it without an upgrade
and no cycle can form. `SessionRepository.get_for_update` uses the same mode for the same reason,
so there is **one lock mode on `simulation_sessions` for every writer in both processes**.

**The lock order, documented once (D5).** A writer that takes both takes the session-row lock
(`SessionRepository.get_for_update`) before the allocation — which every command, the
`SimulationRunner`'s tick and its `after_tick` hooks already do — and never the other way round.
Because both are now the same mode on the same row, that order is an ordering of equal locks and
cannot deadlock either way; it is stated so that a future writer taking a *different* row lock has
a rule to follow rather than a convention to guess.

`backend/tests/integration/persistence/test_seq_lock_order.py` is the regression test, and it bites
against real PostgreSQL when either mode here is put back to `FOR UPDATE`.

**Flush-before-append (HLD 70 §70.3.5, I3 E4a).** Every append runs the card-status projection
over the batch before it allocates: under the session-row lock it folds the session's relevant
events (`app.domain.dds.card_status.RELEVANT_EVENT_TYPES`) into a `CardStatusFold`, lets
`plan_append` merge the due `DDS_CARD_STATUS_CHANGED` events into the batch, and materialises
`incidents.card_status` in the same transaction. Because this is the one path every session
writer — each command, the runner tick and its hooks, the voice agent — appends through, the rule
holds in every session Unit of Work without any caller having to remember it. `flush_deadlines`
is the same flush with an empty batch (stage automation, every tick). The running clock that
caps a batch's bound comes from the session row and the store's `Clock`, through
`app.application.simulation.sim_time.running_offset_ms` — the one implementation of that number.
A session without an incident row (only the lowest-level store tests write one) has no card and
is appended to unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any, NamedTuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.clock import Clock
from app.application.simulation.sim_time import running_offset_ms
from app.db.models.events import SessionEvent as SessionEventRow
from app.db.models.session import Incident as IncidentRow
from app.db.models.session import SimulationSession as SessionRow
from app.domain.common.ids import SessionId
from app.domain.dds.card_status import (
    RELEVANT_EVENT_TYPES,
    CardStatus,
    fold_card_status,
    plan_append,
)
from app.domain.enums import SessionState
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.infrastructure.persistence.mappers import (
    event_row_values,
    session_event_from_row,
    session_event_of,
)

__all__ = ["SqlAlchemyEventStore", "UnknownSessionError"]

logger = logging.getLogger(__name__)

#: §20.8 step 1. Taking the row lock first is the whole protocol: without it two appenders could
#: read the same `next_seq_no` and reserve overlapping ranges. `FOR NO KEY UPDATE` rather than
#: §20.8's literal `FOR UPDATE` — see this module's docstring (R14): it conflicts with itself, so
#: allocation is still serialised, and is compatible with the `FOR KEY SHARE` an appender's own
#: foreign keys already hold on this row, so no lock-upgrade cycle can form.
_LOCK_SESSION_ROW = sa.text(
    "SELECT next_seq_no FROM simulation_sessions WHERE id = :session_id FOR NO KEY UPDATE"
)
_ALLOCATE_SEQ_NOS = sa.text(
    "UPDATE simulation_sessions SET next_seq_no = next_seq_no + :event_count"
    " WHERE id = :session_id RETURNING next_seq_no - :event_count AS first_seq_no"
)


class UnknownSessionError(LookupError):
    """Raised when an append targets a `simulation_sessions` row that does not exist."""


class _FoldedEvent(NamedTuple):
    """The three columns `fold_card_status` reads, without building a whole `SessionEvent`."""

    event_type: EventType
    payload: Mapping[str, Any]
    monotonic_offset_ms: int


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
        """Allocate contiguous `seq_no`s under the §20.8 row lock and insert the events, with the
        card-status events the flush-before-append rule merges in (HLD 70 §70.3.5)."""
        if not events:
            return []
        await self._lock(session_id)
        planned = await self._with_card_status(session_id, events, now_ms=None)
        return await self._insert(session_id, planned)

    async def flush_deadlines(self, session_id: SessionId, now_ms: int) -> list[SessionEvent]:
        """Append the card-status deadline events due at `now_ms` (HLD 70 §70.3.5)."""
        await self._lock(session_id)
        planned = await self._with_card_status(session_id, (), now_ms=now_ms)
        return await self._insert(session_id, planned)

    async def _insert(
        self, session_id: SessionId, events: Sequence[DomainEvent]
    ) -> list[SessionEvent]:
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

    async def last_seq_no(
        self, session_id: SessionId, event_types: Collection[EventType] | None = None
    ) -> int:
        """`MAX(seq_no)`, optionally narrowed to `event_types`; `0` for an empty log (§40.6).

        This is the PostgreSQL fallback behind the `session:{id}:last_seq_no` cache key, and —
        with `event_types` set to a role's `visible_event_types` — the "highest `seq_no` visible
        to the caller's role" that `SessionDetail.last_seq_no` and `SessionEventPage.last_seq_no`
        are defined as. An empty `event_types` collection means "no type at all" and therefore
        answers `0` without touching the database.
        """
        table = SessionEventRow.__table__
        if event_types is not None and not event_types:
            return 0
        statement = sa.select(sa.func.max(table.c.seq_no)).where(
            table.c.session_id == UUID(str(session_id))
        )
        if event_types is not None:
            statement = statement.where(
                table.c.event_type.in_([event_type.value for event_type in event_types])
            )
        result = await self._session.execute(statement)
        return int(result.scalar_one_or_none() or 0)

    async def _lock(self, session_id: SessionId) -> None:
        """§20.8's row lock, taken before the card-status read so no appender interleaves."""
        locked = await self._session.execute(
            _LOCK_SESSION_ROW, {"session_id": UUID(str(session_id))}
        )
        if locked.one_or_none() is None:
            raise UnknownSessionError(f"no simulation_sessions row {session_id}")

    async def _with_card_status(
        self, session_id: SessionId, events: Sequence[DomainEvent], *, now_ms: int | None
    ) -> list[DomainEvent]:
        """`events` with the due `DDS_CARD_STATUS_CHANGED` merged in; the column follows.

        Nothing is read beyond the session row when the session has not started and the batch
        does not start it — a `CREATED`/`READY` session has no card timeline yet.
        """
        sessions = SessionRow.__table__
        incidents = IncidentRow.__table__
        row = (
            await self._session.execute(
                sa.select(
                    sessions.c.started_at,
                    sessions.c.paused_total_ms,
                    sessions.c.state,
                    sessions.c.role_transition_started_offset_ms,
                    incidents.c.id.label("incident_id"),
                )
                .select_from(sessions.outerjoin(incidents, incidents.c.session_id == sessions.c.id))
                .where(sessions.c.id == UUID(str(session_id)))
            )
        ).one_or_none()
        if row is None:
            raise UnknownSessionError(f"no simulation_sessions row {session_id}")
        starts_here = any(event.event_type is EventType.SESSION_STARTED for event in events)
        if row.incident_id is None or (row.started_at is None and not starts_here):
            return list(events)
        fold = fold_card_status(await self._relevant_events(session_id))
        if fold.closed:
            return list(events)
        running_now = running_offset_ms(
            started_at=row.started_at,
            paused_total_ms=int(row.paused_total_ms),
            state=SessionState(str(row.state)),
            role_transition_started_offset_ms=row.role_transition_started_offset_ms,
            now=self._clock.now(),
        )
        if now_ms is not None:
            running_now = min(running_now, now_ms)
        planned, after = plan_append(
            fold, events, incident_id=UUID(str(row.incident_id)), running_now_ms=running_now
        )
        if after.status is not fold.status:
            await self._materialise(session_id, after.status)
        return planned

    async def _relevant_events(self, session_id: SessionId) -> list[_FoldedEvent]:
        table = SessionEventRow.__table__
        result = await self._session.execute(
            sa.select(table.c.event_type, table.c.payload, table.c.monotonic_offset_ms)
            .where(
                table.c.session_id == UUID(str(session_id)),
                table.c.event_type.in_([event_type.value for event_type in RELEVANT_EVENT_TYPES]),
            )
            .order_by(table.c.seq_no)
        )
        return [
            _FoldedEvent(EventType(row.event_type), dict(row.payload), int(row.monotonic_offset_ms))
            for row in result.all()
        ]

    async def _materialise(self, session_id: SessionId, status: CardStatus) -> None:
        incidents = IncidentRow.__table__
        await self._session.execute(
            sa.update(incidents)
            .where(incidents.c.session_id == UUID(str(session_id)))
            .values(card_status=status.value)
        )

    async def _allocate(self, session_id: SessionId, event_count: int) -> int:
        """§20.8 step 1: lock the session row, then reserve `event_count` numbers."""
        parameters = {"session_id": UUID(str(session_id)), "event_count": event_count}
        locked = await self._session.execute(_LOCK_SESSION_ROW, parameters)
        if locked.one_or_none() is None:
            raise UnknownSessionError(f"no simulation_sessions row {session_id}")
        allocated = await self._session.execute(_ALLOCATE_SEQ_NOS, parameters)
        return int(allocated.scalar_one())
