"""In-memory fakes for the application ports: `FakeClock`, `InMemoryEventPublisher`,
`InMemoryEventSubscriber`, `InMemoryLastSeqNoCache`, `FakeInferenceReadiness`,
`SequentialIdGenerator`, `InMemoryRunnerLock`, `FakeCallTransportStatus`, `FakePasswordHasher`.

They exist so a test can pin time and inspect the realtime fan-out without PostgreSQL or Redis.
Production wiring uses `app.infrastructure.clock.SystemClock` and
`app.infrastructure.realtime.redis_publisher.RedisEventPublisher`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.ports.event_publisher import EventEnvelope
from app.domain.common.ids import SessionId

__all__ = [
    "FakeCallTransportStatus",
    "FakeClock",
    "FakeInferenceReadiness",
    "FakePasswordHasher",
    "InMemoryEventPublisher",
    "InMemoryEventSubscriber",
    "InMemoryEventSubscription",
    "InMemoryIdempotencyStore",
    "InMemoryLastSeqNoCache",
    "InMemoryRunnerLock",
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
        #: `InMemoryEventSubscriber` registers a callback here, so a fake publish fans out
        #: exactly as a Redis publish does — that is what makes the §40.3 seam testable without
        #: Redis (E7-C).
        self.listeners: list[Callable[[SessionId, EventEnvelope], None]] = []

    async def publish(self, session_id: SessionId, envelopes: Sequence[EventEnvelope]) -> None:
        """Record (or, when `fail_with` is set, raise instead of recording)."""
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        self.published.extend((session_id, envelope) for envelope in envelopes)
        for envelope in envelopes:
            for listener in self.listeners:
                listener(session_id, envelope)

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


class InMemoryRunnerLock:
    """A `RunnerLock` shared by every runner constructed with the same instance (D7, §40.6).

    It reproduces the three semantics the Redis adapter gets from `SET NX EX` and its two
    compare-and-act scripts, minus the TTL: `acquire` succeeds only while the key is free,
    `refresh` and `release` act only while the caller still owns it. A test that needs the TTL
    branch calls `expire`, which is what a lapsed TTL looks like from the outside.
    """

    def __init__(self) -> None:
        #: `session_id -> owner`; a session absent from the map is unlocked.
        self.owners: dict[SessionId, str] = {}
        #: Every `(operation, session_id, owner)` in call order.
        self.calls: list[tuple[str, SessionId, str]] = []

    async def acquire(self, session_id: SessionId, owner: str, ttl_s: int) -> bool:
        """`SET NX`: `True` only when nobody holds the lock."""
        self.calls.append(("acquire", session_id, owner))
        if session_id in self.owners:
            return False
        self.owners[session_id] = owner
        return True

    async def refresh(self, session_id: SessionId, owner: str, ttl_s: int) -> bool:
        """`True` while `owner` still holds the lock."""
        self.calls.append(("refresh", session_id, owner))
        return self.owners.get(session_id) == owner

    async def release(self, session_id: SessionId, owner: str) -> bool:
        """Compare-and-delete: never releases a lock somebody else has taken over."""
        self.calls.append(("release", session_id, owner))
        if self.owners.get(session_id) != owner:
            return False
        del self.owners[session_id]
        return True

    def expire(self, session_id: SessionId) -> None:
        """Drop the key as a lapsed TTL would, so another instance can adopt the session."""
        self.owners.pop(session_id, None)


class FakeCallTransportStatus:
    """A scriptable `CallTransportStatus` (D9, §10.8 `ring`).

    `joined` is the blanket answer; `per_session` overrides it for one session, so a test can have
    the caller present on one session and absent on another in the same process. This is the
    *test* fake: production wiring never imports `app.application.testing` (D13), and
    `SIM_CALL_TRANSPORT=fake` wires
    `app.infrastructure.transport.local_call_transport_status.LocalCallTransportStatus` instead.
    """

    def __init__(self, joined: bool = True) -> None:
        #: The answer for every session that has no override.
        self.joined = joined
        #: `session_id -> answer`, checked before `joined`.
        self.per_session: dict[SessionId, bool] = {}
        #: Every session asked about, in call order.
        self.calls: list[SessionId] = []

    async def caller_joined(self, session_id: SessionId) -> bool:
        """The scripted answer."""
        self.calls.append(session_id)
        return self.per_session.get(session_id, self.joined)


class FakePasswordHasher:
    """A `PasswordHasher` with no KDF, so a login test is not argon2-bound (D8, D13).

    The "digest" is `fake$<password>`: `hash` prefixes and `verify` compares. It is deliberately
    unusable as a credential store — nothing outside a test may construct it, and the seeded
    digests of `app.tools.seed_users` always come from the real
    `app.infrastructure.auth.argon2_hasher.Argon2PasswordHasher`.
    """

    PREFIX = "fake$"

    def hash(self, password: str) -> str:
        """The recognisable, deliberately worthless digest."""
        return f"{self.PREFIX}{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        """Constant-shaped comparison; a digest this fake did not produce is never a match."""
        return password_hash == f"{self.PREFIX}{password}"


class InMemoryEventSubscription:
    """One `EventSubscription` over an `InMemoryEventPublisher` (E7-C, §40.3).

    It is registered with the publisher the moment the context is entered, which is the in-memory
    equivalent of Redis's `SUBSCRIBE`, and it buffers everything published afterwards. That is
    what lets a unit test reproduce the replay/live seam race — publish while the replay is
    mid-page and assert the event arrives exactly once, in order — with no Redis at all.
    """

    def __init__(self, session_id: SessionId) -> None:
        self._session_id = session_id
        self._queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()

    def offer(self, session_id: SessionId, envelope: EventEnvelope) -> None:
        """The publisher's callback: buffer an envelope published for this session."""
        if session_id == self._session_id:
            self._queue.put_nowait(envelope)

    async def get(self) -> EventEnvelope:
        """The next buffered or live envelope, waiting when the buffer is empty."""
        return await self._queue.get()

    def drain(self) -> list[EventEnvelope]:
        """Everything buffered so far, without waiting (§40.3 step 4)."""
        drained: list[EventEnvelope] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                return drained


class InMemoryEventSubscriber:
    """An `EventSubscriber` wired to an `InMemoryEventPublisher` (E7-C).

    `subscribe` is a context manager whose *entry* registers the listener and whose exit removes
    it, exactly like the Redis adapter's subscribe/unsubscribe — so a test that leaks a
    subscription fails the same way the real one would. `active` counts the open subscriptions,
    which is the in-memory stand-in for `PUBSUB NUMSUB`.
    """

    def __init__(self, publisher: InMemoryEventPublisher) -> None:
        self._publisher = publisher
        #: Open subscriptions, by session — the fake's `PUBSUB NUMSUB`.
        self.active: dict[SessionId, int] = {}

    @asynccontextmanager
    async def subscribe(self, session_id: SessionId) -> AsyncIterator[InMemoryEventSubscription]:
        """Register a buffering listener; unregister it on the way out."""
        subscription = InMemoryEventSubscription(session_id)
        self._publisher.listeners.append(subscription.offer)
        self.active[session_id] = self.active.get(session_id, 0) + 1
        try:
            yield subscription
        finally:
            self._publisher.listeners.remove(subscription.offer)
            remaining = self.active.get(session_id, 1) - 1
            if remaining:
                self.active[session_id] = remaining
            else:
                self.active.pop(session_id, None)


class InMemoryLastSeqNoCache:
    """A `LastSeqNoCache` in a dictionary (§40.6's `session:{id}:last_seq_no`, E7-C).

    `forget` is how a test reproduces the documented loss behaviour — "Loss ⇒ the handler reads
    `MAX(seq_no)` from PostgreSQL instead" — without flushing a shared Redis.
    """

    def __init__(self) -> None:
        #: `session_id -> cached maximum`; a session absent from the map is a missing key.
        self.values: dict[SessionId, int] = {}

    async def get(self, session_id: SessionId) -> int | None:
        """The cached value, or `None` for a missing key."""
        return self.values.get(session_id)

    async def set(self, session_id: SessionId, seq_no: int) -> None:
        """Write the cached value."""
        self.values[session_id] = seq_no

    def forget(self, session_id: SessionId) -> None:
        """Drop the key, as a lapsed TTL or a `FLUSHALL` would."""
        self.values.pop(session_id, None)


class InMemoryIdempotencyStore:
    """An `IdempotencyStore` that is a `dict` (§40.6).

    No TTL: a test that wants the key to have expired calls `forget`, which is the same
    observable event as an expiry and does not make the suite wait 300 seconds for it. The
    production adapter is
    `app.infrastructure.realtime.redis_idempotency_store.RedisIdempotencyStore`.
    """

    def __init__(self) -> None:
        #: `key -> the first response body`, in the shape the owning use case stored it.
        self.values: dict[str, str] = {}
        #: Every key asked for, in call order — a test asserts the second command hit the store.
        self.reads: list[str] = []

    async def get(self, key: str) -> str | None:
        """The stored body, or `None`."""
        self.reads.append(key)
        return self.values.get(key)

    async def put(self, key: str, value: str) -> None:
        """Store the body; a second `put` for one key overwrites, as `SET` would."""
        self.values[key] = value

    def forget(self, key: str) -> None:
        """Drop the key, as a lapsed TTL or a `FLUSHALL` would (§40.6's documented loss)."""
        self.values.pop(key, None)
