"""In-memory fakes for the application ports: `FakeClock`, `InMemoryEventPublisher`,
`InMemoryEventSubscriber`, `InMemoryLastSeqNoCache`, `FakeInferenceReadiness`,
`SequentialIdGenerator`, `InMemoryRunnerLock`, `FakeCallTransportStatus`, `FakePasswordHasher`.

They exist so a test can pin time and inspect the realtime fan-out without PostgreSQL or Redis.
Production wiring uses `app.infrastructure.clock.SystemClock` and
`app.infrastructure.realtime.redis_publisher.RedisEventPublisher`.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from random import Random
from typing import Any
from uuid import UUID

from app.application.ports.call_transport import (
    AudioFrame,
    PlaybackHandle,
    TransportEvent,
    TransportEventType,
)
from app.application.ports.dialogue_turn_repository import (
    DialogueTurnUpsert,
    StoredDialogueTurn,
)
from app.application.ports.event_publisher import EventEnvelope
from app.application.ports.voice_token_service import MintedVoiceToken
from app.application.voice.playback import ChunkedPlayback, OutboundQueue
from app.domain.common.ids import SessionId

__all__ = [
    "FakeCallTransport",
    "FakeCallTransportStatus",
    "FakeClock",
    "FakeInferenceReadiness",
    "FakePasswordHasher",
    "InMemoryCallStateCache",
    "InMemoryDialogueTurnRepository",
    "InMemoryEventPublisher",
    "InMemoryEventSubscriber",
    "InMemoryEventSubscription",
    "InMemoryIdempotencyStore",
    "InMemoryLastSeqNoCache",
    "InMemoryRunnerLock",
    "InMemoryVoiceSignals",
    "SequentialIdGenerator",
    "StubVoiceTokenService",
    "noise_frames",
    "silence_frames",
    "sine_burst_frames",
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

    `ready` is the blanket answer; `per_session` overrides it for one session, so a test can have
    the media plane up for one session and down for another in the same process. This is the
    *test* fake: production wiring never imports `app.application.testing` (D13), and
    `SIM_CALL_TRANSPORT=fake` wires
    `app.infrastructure.transport.local_call_transport_status.LocalCallTransportStatus` instead.
    """

    def __init__(self, ready: bool = True) -> None:
        #: The answer for every session that has no override.
        self.ready = ready
        #: `session_id -> answer`, checked before `ready`.
        self.per_session: dict[SessionId, bool] = {}
        #: Every session asked about, in call order.
        self.calls: list[SessionId] = []

    async def transport_ready(self, session_id: SessionId) -> bool:
        """The scripted answer."""
        self.calls.append(session_id)
        return self.per_session.get(session_id, self.ready)


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


# ---------------------------------------------------------------------------------------------
# The voice path (HLD `50-voice-pipeline.md` §2.1, §6.2; D9, D13; SPEC §18, §42 test 12)
# ---------------------------------------------------------------------------------------------

_INT16_MAX = 32767
_BYTES_PER_SAMPLE = 2
_MS_PER_S = 1000


def _pcm(samples: Sequence[float]) -> bytes:
    """Clamp `samples` (full-scale floats) to s16le bytes."""
    out = bytearray()
    for value in samples:
        scaled = round(max(-1.0, min(1.0, value)) * _INT16_MAX)
        out += scaled.to_bytes(_BYTES_PER_SAMPLE, "little", signed=True)
    return bytes(out)


def _frames(
    values: Sequence[float],
    *,
    frame_samples: int,
    sample_rate: int,
    start_offset_ms: int,
) -> list[AudioFrame]:
    frame_ms = (frame_samples * _MS_PER_S) // sample_rate
    frames: list[AudioFrame] = []
    for index in range(len(values) // frame_samples):
        block = values[index * frame_samples : (index + 1) * frame_samples]
        frames.append(
            AudioFrame(
                pcm=_pcm(block),
                sample_rate=sample_rate,
                num_channels=1,
                samples_per_channel=frame_samples,
                capture_offset_ms=start_offset_ms + index * frame_ms,
            )
        )
    return frames


def sine_burst_frames(
    *,
    duration_ms: int,
    frame_samples: int = 512,
    sample_rate: int = 16_000,
    start_offset_ms: int = 0,
    amplitude: float = 0.3,
    frequency_hz: float = 220.0,
) -> list[AudioFrame]:
    """Voiced-sounding synthetic speech: a steady tone loud enough to cross any VAD threshold.

    A sine is not speech, but it is what a *deterministic* turn-detector test needs — the same
    bytes every run, an RMS that is exactly `amplitude / sqrt(2)`, and no model in the loop.
    """
    count = (duration_ms * sample_rate) // _MS_PER_S
    step = 2.0 * math.pi * frequency_hz / sample_rate
    values = [amplitude * math.sin(step * n) for n in range(count)]
    return _frames(
        values,
        frame_samples=frame_samples,
        sample_rate=sample_rate,
        start_offset_ms=start_offset_ms,
    )


def silence_frames(
    *,
    duration_ms: int,
    frame_samples: int = 512,
    sample_rate: int = 16_000,
    start_offset_ms: int = 0,
) -> list[AudioFrame]:
    """Digital silence: every VAD scores it 0.0, which is what closes a turn."""
    count = (duration_ms * sample_rate) // _MS_PER_S
    return _frames(
        [0.0] * count,
        frame_samples=frame_samples,
        sample_rate=sample_rate,
        start_offset_ms=start_offset_ms,
    )


def noise_frames(
    *,
    duration_ms: int,
    frame_samples: int = 512,
    sample_rate: int = 16_000,
    start_offset_ms: int = 0,
    amplitude: float = 0.004,
    seed: int = 20_260_921,
) -> list[AudioFrame]:
    """A quiet, seeded noise floor — below the energy threshold, above digital silence.

    It is what proves the hysteresis band does something: breath noise must neither open a turn
    nor re-open a closing one (§4.4's closing paragraph).
    """
    count = (duration_ms * sample_rate) // _MS_PER_S
    random = Random(seed)
    values = [random.uniform(-amplitude, amplitude) for _ in range(count)]
    return _frames(
        values,
        frame_samples=frame_samples,
        sample_rate=sample_rate,
        start_offset_ms=start_offset_ms,
    )


class FakeCallTransport:
    """A `CallTransport` with scripted inbound audio and a simulated playout clock (D13).

    Three things make it a usable stand-in for LiveKit rather than a mock:

    * **the inbound script drives time.** Yielding a frame advances the injected `FakeClock` by
      the frame's duration, so the whole call — capture offsets, VAD frames, playout drain —
      runs on one deterministic timeline and a test never sleeps;
    * **`clear_outbound()` is truthful.** SPEC §42 test 12 asserts that queued caller audio is
      really cancelled, so this fake implements the queue with the same drain-deadline model the
      real `AudioSource` has, and `played_frames` / `discarded_frames` are what actually
      happened;
    * **playback is chunked.** `play()` returns a real `ChunkedPlayback`, so the §6.3 arithmetic
      under test here is the same code the LiveKit transport runs.
    """

    def __init__(
        self,
        *,
        clock: FakeClock,
        inbound: Iterable[AudioFrame] = (),
        outbound_queue_ms: int = 200,
        call_id: UUID | None = None,
    ) -> None:
        self._clock = clock
        self._inbound = list(inbound)
        self._call_id = call_id
        self._connected = False
        self._inbound_active = False
        self._disconnected = asyncio.Event()
        self._events: asyncio.Queue[TransportEvent | None] = asyncio.Queue()
        self.queue = OutboundQueue(
            capacity_ms=outbound_queue_ms,
            now_ms=clock.monotonic_ms,
            sleep_ms=self._advance,
        )
        #: Every playback started, in start order.
        self.playbacks: list[ChunkedPlayback] = []
        #: How many times `clear_outbound()` was called, and at which simulated instant.
        self.clear_outbound_calls: list[int] = []
        #: Frames the inbound iterator has yielded so far.
        self.yielded: list[AudioFrame] = []

    # -- test scripting -----------------------------------------------------------------------

    @property
    def call_id(self) -> UUID | None:
        """The call `connect()` was given."""
        return self._call_id

    @property
    def connected(self) -> bool:
        """True between `connect()` and `disconnect()`."""
        return self._connected

    @property
    def played_frames(self) -> list[AudioFrame]:
        """Every frame handed to the outbound queue, in capture order."""
        return list(self.queue.captured)

    @property
    def discarded_frames(self) -> list[AudioFrame]:
        """Every frame `clear_outbound()` threw away."""
        return list(self.queue.discarded)

    def script(self, frames: Iterable[AudioFrame]) -> None:
        """Append frames to the inbound script before `inbound_audio()` is iterated."""
        self._inbound.extend(frames)

    def emit(self, event: TransportEvent) -> None:
        """Push one media-plane event for `_control` to consume."""
        self._events.put_nowait(event)

    async def _advance(self, milliseconds: int) -> None:
        """The simulated playout clock: waiting moves time instead of blocking.

        While the inbound script is still running it owns the clock — one advance per captured
        frame — so that a barge-in latency measured across this transport is the ingest
        timeline and not the sum of two independent ones. Once the script is exhausted there is
        nothing else to move time, so waiting on the outbound queue does it and a natural drain
        terminates.
        """
        if self._inbound_active:
            await asyncio.sleep(0)
            return
        self._clock.advance_ms(milliseconds)
        await asyncio.sleep(0)

    # -- the CallTransport port ---------------------------------------------------------------

    async def connect(self, call_id: UUID) -> None:
        """Join the (imaginary) room. Idempotent."""
        self._call_id = call_id
        self._connected = True
        self.emit(
            TransportEvent(
                type=TransportEventType.CONNECTED,
                call_id=call_id,
                at_offset_ms=self._clock.monotonic_ms(),
            )
        )

    async def inbound_audio(self) -> AsyncIterator[AudioFrame]:
        """Yield the scripted frames, advancing the clock by each frame's duration."""
        self._inbound_active = True
        try:
            for frame in self._inbound:
                if self._disconnected.is_set():
                    break
                self.yielded.append(frame)
                yield frame
                self._clock.advance_ms(frame.duration_ms)
                await asyncio.sleep(0)
        finally:
            self._inbound_active = False
            self._disconnected.set()

    async def play(self, frames: AsyncIterator[AudioFrame]) -> PlaybackHandle:
        """Start a chunked playback over the simulated queue."""
        playback = ChunkedPlayback(frames, self.queue, now_ms=self._clock.monotonic_ms)
        playback.start()
        self.playbacks.append(playback)
        await asyncio.sleep(0)
        return playback

    async def clear_outbound(self) -> None:
        """Discard every queued frame (SPEC §18 step 3, §42 test 12)."""
        self.clear_outbound_calls.append(self._clock.monotonic_ms())
        self.queue.clear_queue()

    async def events(self) -> AsyncIterator[TransportEvent]:
        """Media-plane events, ending when `disconnect()` pushes the sentinel."""
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    async def disconnect(self) -> None:
        """Stop the inbound iterator and end the event stream. Idempotent."""
        self._connected = False
        self._disconnected.set()
        self._events.put_nowait(None)


# ---------------------------------------------------------------------------------------------
# E11-B: the backend half of the call (D9, §40.6)
# ---------------------------------------------------------------------------------------------


class StubVoiceTokenService:
    """A `VoiceTokenService` that records what it was asked to mint and signs nothing.

    The real adapter (`app.infrastructure.transport.livekit_token_service.LiveKitTokenService`)
    has its own test that decodes the JWT it produces; a use-case test only needs to know which
    room and identity reached the minter, which is what `calls` holds.
    """

    def __init__(self, livekit_url: str = "ws://livekit.test:7880", ttl_minutes: int = 10) -> None:
        self.livekit_url = livekit_url
        self._ttl = timedelta(minutes=ttl_minutes)
        #: `(room_name, participant_identity)` per call, in order.
        self.calls: list[tuple[str, str]] = []

    def mint(self, *, room_name: str, participant_identity: str) -> MintedVoiceToken:
        """A deterministic, unsigned stand-in for a LiveKit access token."""
        self.calls.append((room_name, participant_identity))
        return MintedVoiceToken(
            token=f"stub-token:{room_name}:{participant_identity}",
            livekit_url=self.livekit_url,
            room_name=room_name,
            participant_identity=participant_identity,
            expires_at=datetime.now(UTC) + self._ttl,
        )


class InMemoryVoiceSignals:
    """A recording `VoiceSignalPublisher` — §40.6's `voice:join` and `voice:cancel:{session_id}`.

    Like the real adapter it never raises; unlike it, nothing is lost, so a test can assert both
    *that* a signal was published and *when* relative to the commit (a use case that published
    inside its transaction would show up here before the rollback a failing test forces).
    """

    def __init__(self) -> None:
        #: `(session_id, room, call_id)` per `voice:join`, in order.
        self.joins: list[tuple[SessionId, str, UUID]] = []
        #: `(session_id, call_id, reason, at_offset_ms)` per `voice:cancel`, in order.
        self.cancels: list[tuple[SessionId, UUID, str, int]] = []

    async def publish_join(self, session_id: SessionId, *, room: str, call_id: UUID) -> None:
        """Record one `voice:join`."""
        self.joins.append((session_id, room, call_id))

    async def publish_cancel(
        self, session_id: SessionId, *, call_id: UUID, reason: str, at_offset_ms: int
    ) -> None:
        """Record one `voice:cancel:{session_id}`."""
        self.cancels.append((session_id, call_id, reason, at_offset_ms))


class InMemoryCallStateCache:
    """§40.6's `session:{id}:call_state`, in a dict — including its documented ways of losing it.

    `forget` is a lapsed TTL or a `FLUSHALL`; `fail_reads` is an unreachable Redis, which the real
    adapter turns into a miss. Both must leave every reader answering from the fold.
    """

    def __init__(self) -> None:
        #: `session_id -> the stored JSON document`.
        self.values: dict[SessionId, str] = {}
        #: Every session read, in order.
        self.reads: list[SessionId] = []
        #: When true, every `get` answers `None`, as the adapter does for a Redis error.
        self.fail_reads = False

    async def get(self, session_id: SessionId) -> str | None:
        """The stored document, or `None`."""
        self.reads.append(session_id)
        if self.fail_reads:
            return None
        return self.values.get(session_id)

    async def put(self, session_id: SessionId, document: str) -> None:
        """Store the document; a second `put` overwrites, as `SET` would."""
        self.values[session_id] = document

    def forget(self, session_id: SessionId) -> None:
        """Drop the key, as a lapsed TTL or a `FLUSHALL` would (§40.6's documented loss)."""
        self.values.pop(session_id, None)


class InMemoryDialogueTurnRepository:
    """A `DialogueTurnRepository` in a dict (§20.6, D13).

    Three epics fill a `dialogue_turns` row in three passes (E12 the speech boundaries, E13 the
    interpretation and the gate output, E14 the caller side), and none may blank another's work.
    This fake has to reproduce that or a unit test would pass against it while the real
    `INSERT … ON CONFLICT DO UPDATE` lost a column — so `upsert` writes only the fields the caller
    actually set (`model_fields_set`), exactly as `SqlAlchemyDialogueTurnRepository` does.
    """

    def __init__(self) -> None:
        #: `(session_id, turn_index) -> the row as it stands`.
        self.rows: dict[tuple[SessionId, int], StoredDialogueTurn] = {}

    async def upsert(self, turn: DialogueTurnUpsert) -> uuid.UUID:
        """Insert or update `(session_id, turn_index)`; returns the row's id."""
        key = (turn.session_id, turn.turn_index)
        existing = self.rows.get(key)
        supplied: dict[str, Any] = {
            name: getattr(turn, name)
            for name in (
                "user_speech_ended_offset_ms",
                "operator_transcript_segment_id",
                "correlation_id",
            )
            if name in turn.model_fields_set
        }
        if existing is None:
            self.rows[key] = StoredDialogueTurn(
                id=turn.id,
                session_id=turn.session_id,
                role_stage_id=turn.role_stage_id,
                turn_index=turn.turn_index,
                user_speech_started_offset_ms=turn.user_speech_started_offset_ms,
                **supplied,
            )
        else:
            self.rows[key] = existing.model_copy(
                update={
                    "user_speech_started_offset_ms": turn.user_speech_started_offset_ms,
                    **supplied,
                }
            )
        return self.rows[key].id

    async def set_dialogue_outcome(
        self,
        session_id: SessionId,
        turn_index: int,
        *,
        interpretation: Mapping[str, Any],
        gate_output: Mapping[str, Any],
        planned_text: str,
        fallback_used: bool,
    ) -> None:
        """E13's four columns on an existing row; a missing row is not created (the port's rule)."""
        row = self.rows.get((session_id, turn_index))
        if row is None:
            return
        self.rows[(session_id, turn_index)] = row.model_copy(
            update={
                "interpretation": dict(interpretation),
                "gate_output": dict(gate_output),
                "planned_text": planned_text,
                "fallback_used": fallback_used,
            }
        )

    async def set_speech_end_to_first_audio_ms(
        self, session_id: SessionId, turn_index: int, value: int
    ) -> None:
        """SPEC §27's critical product metric on an existing row; no row, no write."""
        row = self.rows.get((session_id, turn_index))
        if row is None:
            return
        self.rows[(session_id, turn_index)] = row.model_copy(
            update={"speech_end_to_first_audio_ms": value}
        )

    async def get(self, session_id: SessionId, turn_index: int) -> StoredDialogueTurn | None:
        """One row by its natural key, or `None`."""
        return self.rows.get((session_id, turn_index))

    async def list_for_session(self, session_id: SessionId) -> list[StoredDialogueTurn]:
        """Every turn of one session in `turn_index` order."""
        return sorted(
            (row for key, row in self.rows.items() if key[0] == session_id),
            key=lambda row: row.turn_index,
        )
