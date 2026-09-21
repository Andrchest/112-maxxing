"""§40.3's mechanism, driven over the in-memory fakes with no socket at all (E7-C).

`SessionEventStream` is an async generator over four ports, which is exactly what makes the
lossless-handover argument testable: this module owns a fake `UnitOfWork` whose event store can be
appended to *while the replay is mid-page*, and asserts the §40.3 guarantees directly —

* role filtering on both sides of the seam ("Replay equals live");
* the seam race: an event published between the subscribe and the end of the PostgreSQL read
  arrives exactly once, in order;
* de-duplication when the same `seq_no` arrives from both sides;
* `resume_complete` after the replay and before the first live event;
* `4409`'s error frame and exception when the cursor is ahead of the log;
* the heartbeat's `last_seq_no` coming from the cache, and from `MAX(seq_no)` when it is missing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Sequence
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any

import pytest
from app.application.ports.event_publisher import EventEnvelope, envelope_of
from app.application.realtime.effective_role import INSTRUCTOR, Connection
from app.application.realtime.event_stream import (
    ErrorFrame,
    EventFrame,
    HeartbeatFrame,
    InvalidResumeCursorError,
    ResumeCompleteFrame,
    SessionEventStream,
)
from app.application.testing.fakes import (
    FakeClock,
    InMemoryEventPublisher,
    InMemoryEventSubscriber,
    InMemoryLastSeqNoCache,
)
from app.domain.common.ids import EventId, SessionId
from app.domain.enums import ActorType, RoleType, SessionMode
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.session.policy import SESSION_POLICIES

SESSION_ID = SessionId("11111111-1111-4111-8111-111111111111")
OPERATOR = Connection(RoleType.OPERATOR_112, SESSION_POLICIES[SessionMode.MULTI_TRAINEE], False)
CONSOLE = Connection(INSTRUCTOR, SESSION_POLICIES[SessionMode.MULTI_TRAINEE], False)


# ---------------------------------------------------------------------------------------------
# A fake event store and Unit of Work: the two ports the mechanism reads PostgreSQL through.
# ---------------------------------------------------------------------------------------------


class _FakeEventStore:
    """An `EventStore` over a list, with a hook that fires while a page is being read."""

    def __init__(self, rows: list[SessionEvent]) -> None:
        self.rows = rows
        #: Awaited once, inside the first `read` — the seam race's injection point.
        self.on_read: Any | None = None

    async def append(self, session_id: SessionId, events: Sequence[Any]) -> list[SessionEvent]:
        raise NotImplementedError("the read path never appends")

    async def read(
        self, session_id: SessionId, after_seq_no: int = 0, limit: int | None = None
    ) -> list[SessionEvent]:
        hook, self.on_read = self.on_read, None
        if hook is not None:
            await hook()
        selected = [row for row in self.rows if row.seq_no > after_seq_no]
        return selected if limit is None else selected[:limit]

    async def last_seq_no(
        self, session_id: SessionId, event_types: Collection[EventType] | None = None
    ) -> int:
        if event_types is not None and not event_types:
            return 0
        candidates = [
            row.seq_no for row in self.rows if event_types is None or row.event_type in event_types
        ]
        return max(candidates, default=0)


class _FakeUnitOfWork:
    """Just enough `UnitOfWork` for the read path: one event store, a no-op transaction."""

    def __init__(self, events: _FakeEventStore) -> None:
        self.events = events

    async def __aenter__(self) -> _FakeUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def event(seq_no: int, event_type: EventType, **payload: Any) -> SessionEvent:
    return SessionEvent(
        id=EventId(f"00000000-0000-4000-8000-{seq_no:012d}"),
        session_id=SESSION_ID,
        seq_no=seq_no,
        event_type=event_type,
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seq_no),
        monotonic_offset_ms=seq_no * 1000,
        actor_type=ActorType.SIMULATION,
        payload=payload,
    )


def build(
    rows: list[SessionEvent],
    *,
    page_size: int = 100,
    heartbeat_s: float = 3600.0,
) -> tuple[SessionEventStream, _FakeEventStore, InMemoryEventPublisher, InMemoryLastSeqNoCache]:
    store = _FakeEventStore(rows)
    publisher = InMemoryEventPublisher()
    cache = InMemoryLastSeqNoCache()
    stream = SessionEventStream(
        lambda: _FakeUnitOfWork(store),  # type: ignore[arg-type,return-value]
        InMemoryEventSubscriber(publisher),
        cache,
        FakeClock(),
        replay_page_size=page_size,
        heartbeat_s=heartbeat_s,
    )
    return stream, store, publisher, cache


async def take_until_resume_complete(generator: Any) -> list[Any]:
    """Consume frames up to and including `resume_complete`, then leave the generator live."""
    frames: list[Any] = []
    async for frame in generator:
        frames.append(frame)
        if isinstance(frame, ResumeCompleteFrame):
            return frames
    return frames


# ---------------------------------------------------------------------------------------------
# Replay and role filtering
# ---------------------------------------------------------------------------------------------


async def test_replay_pushes_only_what_the_role_may_see_then_resume_complete() -> None:
    rows = [
        event(1, EventType.SESSION_CREATED, session_seed="s"),
        event(2, EventType.SESSION_STARTED, first_role_type="OPERATOR_112"),
        event(3, EventType.WORLD_TRUTH_MUTATED, revision=1),
        event(4, EventType.CARD_FIELD_CHANGED, field_path="address"),
    ]
    stream, *_ = build(rows)

    frames = await take_until_resume_complete(stream.stream(SESSION_ID, OPERATOR, 0))

    pushed = [frame for frame in frames if isinstance(frame, EventFrame)]
    assert [frame.seq_no for frame in pushed] == [2, 4]
    complete = frames[-1]
    assert isinstance(complete, ResumeCompleteFrame)
    assert complete.replayed_count == 2
    # The cursor is the **raw** log head, not the last visible event: a client that resumes from
    # it is not re-sent the rows it may not see.
    assert complete.last_seq_no == 4
    assert complete.live is True


async def test_the_instructor_sees_the_events_a_trainee_never_does() -> None:
    rows = [
        event(1, EventType.WORLD_TRUTH_MUTATED, revision=1),
        event(2, EventType.CALLER_RESPONSE_PLANNED, withheld_count=2),
        event(3, EventType.SESSION_CREATED, session_seed="s"),
    ]
    stream, *_ = build(rows)
    frames = await take_until_resume_complete(stream.stream(SESSION_ID, CONSOLE, 0))
    assert [f.seq_no for f in frames if isinstance(f, EventFrame)] == [1, 2, 3]


async def test_replay_pages_and_preserves_order() -> None:
    """§40.3 "Replay bounds": pages of `WS_REPLAY_MAX_EVENTS`, with no reordering."""
    rows = [event(seq, EventType.SESSION_STARTED) for seq in range(1, 26)]
    stream, *_ = build(rows, page_size=4)
    frames = await take_until_resume_complete(stream.stream(SESSION_ID, OPERATOR, 0))
    assert [f.seq_no for f in frames if isinstance(f, EventFrame)] == list(range(1, 26))


async def test_after_seq_no_is_exclusive() -> None:
    rows = [event(seq, EventType.SESSION_STARTED) for seq in range(1, 6)]
    stream, *_ = build(rows)
    frames = await take_until_resume_complete(stream.stream(SESSION_ID, OPERATOR, 3))
    assert [f.seq_no for f in frames if isinstance(f, EventFrame)] == [4, 5]


# ---------------------------------------------------------------------------------------------
# The seam (§40.3 steps 2-4) — the reason the subscribe comes first
# ---------------------------------------------------------------------------------------------


async def test_an_event_published_during_the_replay_arrives_exactly_once_in_order() -> None:
    """§40.3: "an event appended during step 3 arrives on the buffer, not into a gap".

    The publish happens *inside* the first PostgreSQL read and reaches the bus only — which is
    what the seam really looks like: the reading transaction's snapshot was taken before the
    appending transaction committed, so no page of this replay will ever return seq_no 5, and the
    buffer is the one and only path by which it can arrive. Subscribing after the read instead of
    before turns this into a lost event — see the task report for the run that proves it.
    """
    rows = [event(seq, EventType.SESSION_STARTED) for seq in range(1, 5)]
    stream, store, publisher, _ = build(rows, page_size=2)

    late = event(5, EventType.CARD_FIELD_CHANGED, field_path="address")

    async def publish_mid_page() -> None:
        await publisher.publish(SESSION_ID, [envelope_of(late)])

    store.on_read = publish_mid_page

    frames = await take_until_resume_complete(stream.stream(SESSION_ID, OPERATOR, 0))
    seq_nos = [frame.seq_no for frame in frames if isinstance(frame, EventFrame)]
    assert seq_nos == [1, 2, 3, 4, 5], "the event published mid-replay must not be lost"
    assert seq_nos.count(5) == 1, "…and must not be delivered twice at the seam"


async def test_a_duplicate_at_the_seam_is_delivered_once() -> None:
    """§40.3's at-least-once note: an event both read from PostgreSQL and buffered from Redis."""
    rows = [event(1, EventType.SESSION_STARTED), event(2, EventType.SESSION_STARTED)]
    stream, _, publisher, _ = build(rows)
    await publisher.publish(SESSION_ID, [envelope_of(rows[1])])

    frames = await take_until_resume_complete(stream.stream(SESSION_ID, OPERATOR, 0))
    assert [f.seq_no for f in frames if isinstance(f, EventFrame)] == [1, 2]


async def test_live_events_arrive_after_resume_complete_in_order() -> None:
    rows = [event(1, EventType.SESSION_STARTED)]
    stream, _, publisher, _ = build(rows)
    generator = stream.stream(SESSION_ID, OPERATOR, 0)
    frames = await take_until_resume_complete(generator)
    assert isinstance(frames[-1], ResumeCompleteFrame)

    for seq in (2, 3):
        await publisher.publish(
            SESSION_ID, [envelope_of(event(seq, EventType.CARD_FIELD_CHANGED, field_path="a"))]
        )
    assert (await anext(generator)).seq_no == 2
    assert (await anext(generator)).seq_no == 3
    await generator.aclose()


async def test_a_live_event_the_role_may_not_see_is_never_serialised() -> None:
    """§40.4, on the live side: `WORLD_TRUTH_MUTATED` is absent from the bytes, not hidden."""
    rows = [event(1, EventType.SESSION_STARTED)]
    stream, _, publisher, _ = build(rows)
    generator = stream.stream(SESSION_ID, OPERATOR, 0)
    await take_until_resume_complete(generator)

    await publisher.publish(SESSION_ID, [envelope_of(event(2, EventType.WORLD_TRUTH_MUTATED))])
    await publisher.publish(
        SESSION_ID, [envelope_of(event(3, EventType.CARD_FIELD_CHANGED, field_path="a"))]
    )
    assert (await anext(generator)).seq_no == 3
    await generator.aclose()


# ---------------------------------------------------------------------------------------------
# §40.1's 4409 and §40.2's heartbeat
# ---------------------------------------------------------------------------------------------


async def test_a_cursor_ahead_of_the_log_yields_the_error_frame_then_raises() -> None:
    """§40.1 `4409`, §40.2's `INVALID_RESUME_CURSOR` — the frame first, so the client knows why."""
    stream, *_ = build([event(1, EventType.SESSION_STARTED)])
    generator = stream.stream(SESSION_ID, OPERATOR, 900)

    frame = await anext(generator)
    assert isinstance(frame, ErrorFrame)
    assert frame.code == "INVALID_RESUME_CURSOR"
    assert frame.detail == "after_seq_no 900 > last_seq_no 1"
    with pytest.raises(InvalidResumeCursorError):
        await anext(generator)


async def test_a_trainees_role_cursor_is_never_ahead_of_the_log() -> None:
    """The `4409` check is over the whole log, not the role's visible slice (§40.1)."""
    rows = [event(1, EventType.SESSION_STARTED), event(2, EventType.WORLD_TRUTH_MUTATED)]
    stream, *_ = build(rows)
    frames = await take_until_resume_complete(stream.stream(SESSION_ID, OPERATOR, 2))
    assert isinstance(frames[-1], ResumeCompleteFrame)


async def test_the_heartbeat_reads_the_cache_and_falls_back_to_postgresql() -> None:
    """§40.6: the read cache, "Loss ⇒ the handler reads `MAX(seq_no)` from PostgreSQL instead"."""
    rows = [event(1, EventType.SESSION_STARTED), event(2, EventType.WORLD_TRUTH_MUTATED)]
    stream, _, _, cache = build(rows, heartbeat_s=0.01)
    generator = stream.stream(SESSION_ID, OPERATOR, 0)
    await take_until_resume_complete(generator)

    await cache.set(SESSION_ID, 42)
    cached = await anext(generator)
    assert isinstance(cached, HeartbeatFrame)
    assert cached.last_seq_no == 42

    cache.forget(SESSION_ID)
    fallback = await anext(generator)
    assert isinstance(fallback, HeartbeatFrame)
    assert fallback.last_seq_no == 2, "the log's head, including events this role cannot see"
    await generator.aclose()


async def test_the_subscription_is_released_when_the_generator_closes() -> None:
    """Resource hygiene (§40.6): nothing outlives the `async with` inside the mechanism."""
    publisher = InMemoryEventPublisher()
    subscriber = InMemoryEventSubscriber(publisher)
    stream = SessionEventStream(
        lambda: _FakeUnitOfWork(_FakeEventStore([event(1, EventType.SESSION_STARTED)])),  # type: ignore[arg-type,return-value]
        subscriber,
        InMemoryLastSeqNoCache(),
        FakeClock(),
        replay_page_size=10,
        heartbeat_s=3600.0,
    )
    generator = stream.stream(SESSION_ID, OPERATOR, 0)
    await take_until_resume_complete(generator)
    assert subscriber.active == {SESSION_ID: 1}
    await generator.aclose()
    assert subscriber.active == {}
    assert publisher.listeners == []


async def test_twenty_connect_disconnect_cycles_leave_no_task_behind() -> None:
    """The unit-level half of the `asyncio.all_tasks()` delta-zero assertion (§40.6)."""
    before = len(asyncio.all_tasks())
    for _ in range(20):
        stream, _, publisher, _ = build([event(1, EventType.SESSION_STARTED)])
        generator = stream.stream(SESSION_ID, OPERATOR, 0)
        await take_until_resume_complete(generator)
        await generator.aclose()
        assert publisher.listeners == []
    await asyncio.sleep(0)
    assert len(asyncio.all_tasks()) == before


def test_the_live_envelope_and_the_replayed_row_produce_the_same_frame() -> None:
    """§40.3's "Replay equals live": both paths build the envelope through the same filter."""
    from app.application.realtime.redaction import (
        redact,
        source_of_envelope,
        source_of_row,
    )

    row = event(7, EventType.ASR_FINAL, call_id="c", text="алло", asr_provider="whisper")
    envelope: EventEnvelope = envelope_of(row)
    from_row = redact(source_of_row(row), OPERATOR.role, OPERATOR.policy)
    from_bus = redact(source_of_envelope(envelope), OPERATOR.role, OPERATOR.policy)
    assert from_row is not None and from_bus is not None
    assert EventFrame.of(from_row) == EventFrame.of(from_bus)
    assert "asr_provider" not in from_row.payload
