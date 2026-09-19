"""In-memory fakes for the application ports: `FakeClock`, `InMemoryEventPublisher`,
`FakeInferenceReadiness`, `SequentialIdGenerator`.

They exist so a test can pin time and inspect the realtime fan-out without PostgreSQL or Redis.
Production wiring uses `app.infrastructure.clock.SystemClock` and
`app.infrastructure.realtime.redis_publisher.RedisEventPublisher`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.ports.event_publisher import EventEnvelope
from app.domain.common.ids import SessionId

__all__ = [
    "FakeClock",
    "FakeInferenceReadiness",
    "InMemoryEventPublisher",
    "SequentialIdGenerator",
]


class FakeClock:
    """A `Clock` whose time only moves when a test moves it.

    `now()` returns `start` plus the accumulated advance; `monotonic_ms()` returns
    `monotonic_origin_ms` plus the same accumulated advance, so the two readings stay consistent.
    """

    def __init__(self, start: datetime | None = None, monotonic_origin_ms: int = 0) -> None:
        base = start if start is not None else datetime(2026, 1, 1, tzinfo=UTC)
        if base.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware start instant")
        self._start = base.astimezone(UTC)
        self._origin_ms = monotonic_origin_ms
        self._elapsed_ms = 0

    def now(self) -> datetime:
        """The pinned instant."""
        return self._start + timedelta(milliseconds=self._elapsed_ms)

    def monotonic_ms(self) -> int:
        """The pinned monotonic counter."""
        return self._origin_ms + self._elapsed_ms

    def advance_ms(self, milliseconds: int) -> None:
        """Move both readings forward; a negative advance is rejected (monotonicity)."""
        if milliseconds < 0:
            raise ValueError("a clock never goes backwards")
        self._elapsed_ms += milliseconds


class InMemoryEventPublisher:
    """An `EventPublisher` that records what it was asked to publish.

    `published` keeps `(session_id, envelope)` pairs in call order — the order the Unit of Work
    published them, which is `seq_no` order within one commit.
    """

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.published: list[tuple[SessionId, EventEnvelope]] = []
        self.calls: int = 0
        #: When set, `publish` raises it — used to prove the Unit of Work swallows the failure.
        self.fail_with = fail_with

    async def publish(self, session_id: SessionId, envelopes: Sequence[EventEnvelope]) -> None:
        """Record (or, when `fail_with` is set, raise instead of recording)."""
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        self.published.extend((session_id, envelope) for envelope in envelopes)

    def envelopes_for(self, session_id: SessionId) -> list[EventEnvelope]:
        """Every envelope published for one session, in publish order."""
        return [
            envelope
            for published_session_id, envelope in self.published
            if published_session_id == session_id
        ]


class FakeInferenceReadiness:
    """An `InferenceReadiness` whose verdict a test sets.

    TODO(E18): the real adapter over the inference health registry (D8). E5 ships this fake only,
    so `require_inference_ready=True` is exercisable without an inference stack.
    """

    def __init__(self, ready: bool = True) -> None:
        #: The verdict `is_ready()` returns; a test flips it between commands.
        self.ready = ready
        self.calls: int = 0

    async def is_ready(self) -> bool:
        """The pinned verdict."""
        self.calls += 1
        return self.ready


class SequentialIdGenerator:
    """An `IdGenerator` returning `<prefix>-0000…N`, so a use-case test can predict every id.

    The ids are valid UUIDs built from a counter, never `uuid4`: two runs of the same use case
    with a fresh generator produce the same aggregate, which is what makes a full-equality
    assertion against a persisted round-trip possible.
    """

    def __init__(self, namespace: int = 0) -> None:
        self._namespace = namespace
        self._counter = 0
        #: Every id handed out, in allocation order.
        self.issued: list[UUID] = []

    def new(self) -> UUID:
        """The next id in the sequence."""
        self._counter += 1
        value = UUID(int=(self._namespace << 64) | self._counter, version=4)
        self.issued.append(value)
        return value
