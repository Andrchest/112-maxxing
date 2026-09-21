"""Chunked outbound playback with truthful cancellation (§2.1, §6.1–§6.3; SPEC §18; D9).

SPEC §18 forbids the easy implementation: "Do not implement TTS as one complete WAV file that
cannot be interrupted." So an utterance is pulled from its producer chunk by chunk
(`tts_chunk_ms`, default 20 ms), handed to a transport queue no deeper than `outbound_queue_ms`
(default 200 ms), and can be stopped at any point with three numbers that are *measured*, not
assumed: how much audio was actually played out, how much was generated, and how many frames were
thrown away.

Two classes:

* `ChunkedPlayback` — the `PlaybackHandle` implementation both transports use. It owns the pump
  task, the captured-chunk ledger and the §6.3 arithmetic
  `delivered_audio_ms = sum(captured chunk ms) - queued_duration_at_cancel`, clamped to
  `[0, total_audio_ms_generated]`.
* `OutboundQueue` — an in-memory `PlayoutSink` with a **simulated playout clock**: audio drains at
  real time as read from an injected clock, so `queued_duration_ms()` answers the same question
  LiveKit's `AudioSource.queued_duration` answers, and a test driving a `FakeClock` gets a
  deterministic `DeliveredAudio` instead of a race.

`LiveKitCallTransport` supplies a `PlayoutSink` over `rtc.AudioSource` instead; the arithmetic
above is then exactly the mapping table of §2.1 (`capture_frame` / `queued_duration` /
`clear_queue` / `wait_for_playout`).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol, runtime_checkable

from app.application.ports.call_transport import AudioFrame, DeliveredAudio
from app.application.voice.config import MS_PER_S

__all__ = ["ChunkedPlayback", "OutboundQueue", "PlayoutSink"]


@runtime_checkable
class PlayoutSink(Protocol):
    """The transport's outbound buffer, as `ChunkedPlayback` needs to see it (§2.1)."""

    @property
    def capacity_ms(self) -> int:
        """`outbound_queue_ms`: how much audio the buffer holds before `capture_frame` blocks."""
        ...

    async def capture_frame(self, frame: AudioFrame) -> None:
        """Enqueue one frame, waiting while the buffer is full."""
        ...

    def queued_duration_ms(self) -> int:
        """Audio enqueued but not yet played out (LiveKit's `AudioSource.queued_duration`)."""
        ...

    def clear_queue(self) -> None:
        """Discard everything enqueued but not yet played out."""
        ...

    async def wait_for_playout(self) -> None:
        """Await the natural drain of the buffer."""
        ...


class OutboundQueue:
    """An in-memory `PlayoutSink` whose playout follows an injected clock.

    `_drain_deadline_ms` is the instant the currently enqueued audio finishes playing. Everything
    else follows from it: what is still queued is `deadline - now`, capturing a frame pushes the
    deadline out by the frame's duration (from `now` if the queue had already drained — an
    underrun, which is a gap in the caller's speech and not an error), and clearing the queue pulls
    the deadline back to `now`.

    `sleep_ms` is injected so that a test can make waiting *move the clock*: with a `FakeClock` and
    a sleep that advances it, the whole playout is simulated and `DeliveredAudio` is exact.
    """

    def __init__(
        self,
        *,
        capacity_ms: int,
        now_ms: Callable[[], int],
        sleep_ms: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        if capacity_ms <= 0:
            raise ValueError("an outbound queue needs a positive capacity")
        self._capacity_ms = capacity_ms
        self._now_ms = now_ms
        self._sleep_ms = sleep_ms if sleep_ms is not None else _real_sleep_ms
        self._drain_deadline_ms = now_ms()
        self._played: deque[AudioFrame] = deque()
        #: Frames dropped by `clear_queue`, in drop order — the fake transport's proof that the
        #: queue really was cleared (SPEC §42 test 12).
        self.discarded: list[AudioFrame] = []
        #: Every frame handed to the sink, in capture order.
        self.captured: list[AudioFrame] = []

    @property
    def capacity_ms(self) -> int:
        """`outbound_queue_ms`."""
        return self._capacity_ms

    async def capture_frame(self, frame: AudioFrame) -> None:
        """Enqueue one frame, waiting while the buffer is full."""
        while self.queued_duration_ms() + frame.duration_ms > self._capacity_ms:
            await self._sleep_ms(frame.duration_ms)
        now = self._now_ms()
        self._drain_deadline_ms = max(now, self._drain_deadline_ms) + frame.duration_ms
        self._played.append(frame)
        self.captured.append(frame)

    def queued_duration_ms(self) -> int:
        """Audio enqueued but not yet played out."""
        return max(0, self._drain_deadline_ms - self._now_ms())

    def clear_queue(self) -> None:
        """Discard everything enqueued but not yet played out."""
        queued_ms = self.queued_duration_ms()
        self._drain_deadline_ms = self._now_ms()
        dropped_ms = 0
        while self._played and dropped_ms < queued_ms:
            frame = self._played.pop()
            dropped_ms += frame.duration_ms
            self.discarded.append(frame)

    async def wait_for_playout(self) -> None:
        """Await the natural drain of the buffer."""
        while True:
            remaining = self.queued_duration_ms()
            if remaining <= 0:
                return
            await self._sleep_ms(remaining)


async def _real_sleep_ms(milliseconds: int) -> None:
    await asyncio.sleep(milliseconds / MS_PER_S)


class ChunkedPlayback:
    """One outbound utterance: the `PlaybackHandle` of §2.1, with §6.3's accounting."""

    def __init__(
        self,
        frames: AsyncIterator[AudioFrame],
        sink: PlayoutSink,
        *,
        now_ms: Callable[[], int],
        on_frame: Callable[[AudioFrame], None] | None = None,
    ) -> None:
        self._frames = frames
        self._sink = sink
        self._now_ms = now_ms
        #: Tee for the caller recording (§9.1): every frame actually handed to the transport.
        self._on_frame = on_frame
        self._playback_id = uuid.uuid4()
        self._started_offset_ms: int | None = None
        self._captured: list[AudioFrame] = []
        self._total_ms_generated = 0
        self._frames_pulled = 0
        self._cancelled = False
        self._result: DeliveredAudio | None = None
        self._pump: asyncio.Task[None] | None = None
        self._done = asyncio.Event()

    @property
    def playback_id(self) -> uuid.UUID:
        """Identity of this playback."""
        return self._playback_id

    @property
    def started_offset_ms(self) -> int | None:
        """Offset of the first frame actually handed to the transport; None until then."""
        return self._started_offset_ms

    @property
    def captured_frames(self) -> tuple[AudioFrame, ...]:
        """Every frame handed to the transport, in capture order (the caller recording tee)."""
        return tuple(self._captured)

    def start(self) -> None:
        """Schedule the pump task. `CallTransport.play` returns as soon as this has run."""
        if self._pump is None:
            self._pump = asyncio.create_task(self._run())

    def is_active(self) -> bool:
        """True while frames are still being pulled or played out."""
        return self._result is None

    async def wait_done(self) -> DeliveredAudio:
        """Await natural end of playback (queue drained)."""
        await self._done.wait()
        assert self._result is not None
        return self._result

    async def cancel(self) -> DeliveredAudio:
        """Stop playback now, drop queued frames, return what was delivered. Idempotent."""
        if self._result is not None:
            return self._result
        self._cancelled = True
        # §6.1 step 3 before step 4: clearing the queue is what actually stops sound, and the
        # queued duration must be read *immediately before* the clear or the arithmetic of §6.3
        # would credit audio that was thrown away.
        queued_ms = self._sink.queued_duration_ms()
        self._sink.clear_queue()
        pump = self._pump
        if pump is not None and not pump.done():
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump
        self._settle(cancelled=True, queued_ms=queued_ms)
        assert self._result is not None
        return self._result

    # -- internals ----------------------------------------------------------------------------

    async def _run(self) -> None:
        try:
            async for frame in self._frames:
                self._frames_pulled += 1
                self._total_ms_generated += frame.duration_ms
                if self._cancelled:
                    break
                await self._sink.capture_frame(frame)
                if self._started_offset_ms is None:
                    self._started_offset_ms = self._now_ms()
                self._captured.append(frame)
                if self._on_frame is not None:
                    self._on_frame(frame)
            await self._sink.wait_for_playout()
        except asyncio.CancelledError:
            raise
        else:
            self._settle(cancelled=False, queued_ms=0)

    def _settle(self, *, cancelled: bool, queued_ms: int) -> None:
        if self._result is not None:
            return
        captured_ms = sum(frame.duration_ms for frame in self._captured)
        delivered = max(0, min(captured_ms - queued_ms, self._total_ms_generated))
        discarded = self._frames_pulled - len(self._captured) + self._frames_dropped(queued_ms)
        self._result = DeliveredAudio(
            delivered_audio_ms=delivered,
            total_audio_ms_generated=self._total_ms_generated,
            frames_delivered=len(self._captured) - self._frames_dropped(queued_ms),
            frames_discarded=discarded,
            cancelled=cancelled,
        )
        self._done.set()

    def _frames_dropped(self, queued_ms: int) -> int:
        """How many captured frames were still inside the queue when it was cleared."""
        dropped = 0
        accumulated = 0
        for frame in reversed(self._captured):
            if accumulated >= queued_ms:
                break
            accumulated += frame.duration_ms
            dropped += 1
        return dropped
