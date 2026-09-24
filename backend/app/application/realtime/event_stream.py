"""§40.2 frames and §40.3's subscribe / replay / drain / tail mechanism (D5, D8).

The mechanism, quoted from §40.3, is implemented here in the order it is written:

1. the server sends nothing until it receives `resume` — the router's job, because that frame
   arrives on the socket; everything below starts *after* it;
2. **subscribe first** and buffer (`EventSubscriber`). "Subscribing before reading is what makes
   the handover lossless: an event appended during step 3 arrives on the buffer, not into a gap";
3. read `session_events` with `seq_no > after_seq_no` in pages of `replay_page_size`, filter each
   row by role (§40.4) and push it, yielding to the event loop between pages;
4. drain the buffer, discarding anything the read already covered, and send `resume_complete`;
5. tail the subscription live, emitting a `heartbeat` whenever `heartbeat_s` passes with nothing
   pushed.

De-duplication at the seam is by `seq_no` on the **raw** log position, not on what was pushed: a
withheld event still advances the cursor, so a trainee connection does not re-read rows it has
already decided it may not see.

This module is an async generator over ports and knows nothing about sockets. That is what makes
§40.3 testable without one: `backend/tests/unit/application/realtime/test_event_stream.py` drives
it with `InMemoryEventSubscriber`, a fake Unit of Work and `FakeClock`, including the seam race.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.application.ports.clock import Clock
from app.application.ports.event_subscriber import EventSubscriber, EventSubscription
from app.application.ports.last_seq_no_cache import LastSeqNoCache
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.realtime.effective_role import Connection, fold_role
from app.application.realtime.redaction import (
    RealtimeEnvelope,
    SourceEvent,
    redact,
    source_of_envelope,
    source_of_row,
)
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId
from app.domain.dds.call import dds_call_ids

__all__ = [
    "ErrorFrame",
    "EventFrame",
    "Frame",
    "HeartbeatFrame",
    "InvalidResumeCursorError",
    "ResumeCompleteFrame",
    "ResumeRequest",
    "SessionEventStream",
]


class InvalidResumeCursorError(DomainError):
    """§40.1 close `4409`: `after_seq_no` is ahead of the log."""

    code = "VALIDATION_ERROR"


class EventFrame(BaseModel):
    """§40.2's `event` frame — the only frame that carries simulation data.

    Its non-`type` fields are exactly `RealtimeEnvelope`'s, and `of` builds it from one, so the
    frame and `listSessionEvents`' item cannot drift (§40.2: "The envelope is byte-identical to
    what `GET /api/v1/sessions/{id}/events` returns").
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["event"] = "event"
    seq_no: int
    event_type: str
    timestamp_utc: datetime
    monotonic_offset_ms: int
    payload: dict[str, Any]
    actor_type: str
    correlation_id: str | None = None
    redacted_keys: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, envelope: RealtimeEnvelope) -> EventFrame:
        """The frame for one already-redacted envelope."""
        return cls.model_validate(envelope.model_dump(mode="json"))


class ResumeCompleteFrame(BaseModel):
    """§40.2's `resume_complete`: sent once, after the replay and before the first live event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["resume_complete"] = "resume_complete"
    replayed_count: int
    last_seq_no: int
    live: bool = True


class HeartbeatFrame(BaseModel):
    """§40.2's `heartbeat`: a liveness ping and a cheap gap detector."""

    model_config = ConfigDict(frozen=True)

    type: Literal["heartbeat"] = "heartbeat"
    server_time_utc: datetime
    last_seq_no: int


class ErrorFrame(BaseModel):
    """§40.2's `error`. It does not necessarily close the socket; a close carries a §40.1 code."""

    model_config = ConfigDict(frozen=True)

    type: Literal["error"] = "error"
    code: Literal["INVALID_FRAME", "INVALID_RESUME_CURSOR", "RATE_LIMITED", "REPLAY_FAILED"]
    detail: str


Frame = Annotated[
    EventFrame | ResumeCompleteFrame | HeartbeatFrame | ErrorFrame, Field(discriminator="type")
]
"""Every server→client frame of §40.2."""


class ResumeRequest(BaseModel):
    """§40.2's one client→server frame. `extra="forbid"` is half of the `4400` rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["resume"]
    after_seq_no: int = Field(default=0, ge=0)


@dataclass(frozen=True)
class _ReplayStep:
    """One row of the replay: what to push (if anything), and the state after it."""

    frame: EventFrame | None
    cursor: int
    connection: Connection


class SessionEventStream:
    """The §40.3 mechanism, as `stream(...)` — one async generator per `resume`.

    A second `resume` on a live socket does not mutate a running generator: the router abandons
    the current one and starts a new one from the new cursor, which is how a client heals a gap
    (§40.2's "a client whose `last_seq_no` is behind the heartbeat's […] re-sends `resume`").
    """

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        subscriber: EventSubscriber,
        last_seq_no_cache: LastSeqNoCache,
        clock: Clock,
        *,
        replay_page_size: int,
        heartbeat_s: float,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._subscriber = subscriber
        self._cache = last_seq_no_cache
        self._clock = clock
        self._replay_page_size = max(1, replay_page_size)
        self._heartbeat_s = heartbeat_s

    async def stream(
        self, session_id: SessionId, connection: Connection, after_seq_no: int
    ) -> AsyncIterator[Frame]:
        """Yield §40.2 frames forever, until the consumer stops consuming or the task is cancelled.

        Raises `InvalidResumeCursorError` after yielding the matching `error` frame when
        `after_seq_no` is ahead of the log — the router turns that into close `4409`.
        """
        async with self._subscriber.subscribe(session_id) as subscription:
            # Step 2 is complete here: every envelope published from now on is buffered, so the
            # PostgreSQL read below cannot open a gap.
            log_last_seq_no = await self._log_last_seq_no(session_id)
            if after_seq_no > log_last_seq_no:
                detail = f"after_seq_no {after_seq_no} > last_seq_no {log_last_seq_no}"
                yield ErrorFrame(code="INVALID_RESUME_CURSOR", detail=detail)
                raise InvalidResumeCursorError(detail)

            cursor = after_seq_no
            replayed = 0
            current = await self._seed_dds_call_ids(session_id, connection, after_seq_no)

            async for step in self._replay(session_id, current, cursor):
                cursor, current = step.cursor, step.connection
                if step.frame is not None:
                    replayed += 1
                    yield step.frame

            for envelope in subscription.drain():
                if envelope.seq_no <= cursor:
                    continue  # the seam: the PostgreSQL read already covered this one (§40.3)
                cursor = envelope.seq_no
                buffered, current = self._frame_of(source_of_envelope(envelope), current)
                if buffered is not None:
                    replayed += 1
                    yield buffered

            yield ResumeCompleteFrame(replayed_count=replayed, last_seq_no=cursor, live=True)

            async for live in self._tail(session_id, subscription, current, cursor):
                yield live

    async def _replay(
        self, session_id: SessionId, connection: Connection, cursor: int
    ) -> AsyncIterator[_ReplayStep]:
        """§40.3 step 3: paged PostgreSQL read, one short-lived Unit of Work per page.

        Short-lived on purpose: a replay of a two-hour session must not hold one transaction open
        across the whole push, or it pins a connection and an MVCC snapshot for minutes.

        A withheld row yields a step with `frame is None` rather than nothing at all: the cursor
        is the **raw** log position, so the caller's seam de-duplication stays correct for a role
        whose last visible event is far behind the log's head.
        """
        while True:
            async with self._unit_of_work() as uow:
                rows = await uow.events.read(session_id, cursor, self._replay_page_size)
                await uow.commit()
            for row in rows:
                cursor = row.seq_no
                frame, connection = self._frame_of(source_of_row(row), connection)
                yield _ReplayStep(frame=frame, cursor=cursor, connection=connection)
            if len(rows) < self._replay_page_size:
                return
            # §40.3 "pausing between pages so a long session does not block the event loop".
            await asyncio.sleep(0)

    async def _tail(
        self,
        session_id: SessionId,
        subscription: EventSubscription,
        connection: Connection,
        cursor: int,
    ) -> AsyncIterator[Frame]:
        """§40.3 step 5, plus §40.2's heartbeat "every 15 seconds when no event was pushed"."""
        while True:
            try:
                envelope = await asyncio.wait_for(subscription.get(), timeout=self._heartbeat_s)
            except TimeoutError:
                yield HeartbeatFrame(
                    server_time_utc=self._clock.now(),
                    last_seq_no=await self._heartbeat_last_seq_no(session_id, cursor),
                )
                continue
            if envelope.seq_no <= cursor:
                continue
            cursor = envelope.seq_no
            frame, connection = self._frame_of(source_of_envelope(envelope), connection)
            if frame is not None:
                yield frame

    def _frame_of(
        self, event: SourceEvent, connection: Connection
    ) -> tuple[EventFrame | None, Connection]:
        """Redact under the current role, then re-derive the role from the event just pushed.

        Order matters and is §40.1's: the event that *announces* the new stage is still delivered
        under the old role. Both `ROLE_STAGE_STARTED` and `ROLE_TRANSITION_COMPLETED` are `✔` for
        both trainee roles (§40.4 rows 3 and 32), so the choice changes no payload — it only keeps
        the rule statable in one sentence.
        """
        envelope = redact(
            event, connection.role, connection.policy, dds_call_ids=connection.dds_call_ids
        )
        moved = fold_role(connection, event.event_type, event.payload)
        return (None if envelope is None else EventFrame.of(envelope)), moved

    async def _seed_dds_call_ids(
        self, session_id: SessionId, connection: Connection, after_seq_no: int
    ) -> Connection:
        """The ДДС call ids started at or before the cursor (I3 E6b, HLD 80 §80.6.2).

        A resumed connection has not folded the `DDS_CALL_STARTED` events behind its cursor, and
        without them a ДДС call's turn after the cursor would be taken for the 112 call's. One
        read of the log's head, once per `resume`; nothing to read for a replay from `0`.
        """
        if after_seq_no <= 0:
            return connection
        async with self._unit_of_work() as uow:
            head = await uow.events.read(session_id, 0, after_seq_no)
            await uow.commit()
        return connection.with_dds_call_ids(dds_call_ids(head))

    async def _log_last_seq_no(self, session_id: SessionId) -> int:
        """`MAX(seq_no)` over the whole log — the cursor check of §40.1's `4409` is not per role.

        A trainee resuming from a cursor they were handed by `SessionDetail.last_seq_no` (which
        *is* per role) must never be told their own cursor is ahead of the log.
        """
        async with self._unit_of_work() as uow:
            last = await uow.events.last_seq_no(session_id)
            await uow.commit()
        return last

    async def _heartbeat_last_seq_no(self, session_id: SessionId, cursor: int) -> int:
        """§40.6: the `session:{id}:last_seq_no` cache, falling back to `MAX(seq_no)`.

        The fallback is the whole point of the key being non-authoritative: a flushed Redis costs
        one indexed `MAX` per heartbeat and nothing else (SPEC §31).
        """
        cached = await self._cache.get(session_id)
        if cached is not None:
            return cached
        return max(cursor, await self._log_last_seq_no(session_id))
