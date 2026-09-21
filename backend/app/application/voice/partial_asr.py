"""Partial ASR — `ASR_PARTIAL` while the trainee is still speaking (§4.5, SPEC §17, D6).

SPEC §17 permits partials to be *displayed* and forbids them to *drive* anything: "the response
begins only from the finalized turn". Everything in this module follows from that one sentence:

* an `ASR_PARTIAL` is an event and nothing else — never a `transcript_segments` row (§9.1 says so
  literally), never handed to the next stage, never counted toward the turn's latency (§8);
* a partial in flight when the turn ends is **cancelled and discarded**, never merged into the
  final. The final comes from one `transcribe()` over the finalized audio, full stop;
* partials are produced only when `VoiceTurnConfig.partial_asr_enabled` **and** the session's
  `SessionPolicy.show_asr_partials` are both true (§4.5, D6) — an assessment mode switches them
  off without touching the pipeline. The policy is read once, when the call's pipeline starts:
  a session's mode does not change mid-call, and re-reading it per frame would put a database
  round trip inside the audio path.

Two strategies, chosen by the provider and not by configuration (§4.5):

* `supports_streaming` — the turn's frames are forwarded to `ASRProvider.stream()` and every
  `AsrPartial` it yields becomes one event. The final `AsrResult` the stream ends with is
  **dropped**: `AsrTurnResponder` produces the final, and two finals for one turn would be two
  `ASR_FINAL`s.
* otherwise — pseudo-streaming: every `partial_interval_ms` of accumulated speech, a separate
  task calls `transcribe()` on the accumulation so far with request id `{turn_id}:p{n}` and
  `stability=None`. **At most one partial is in flight**; a tick that arrives while one is
  running is skipped rather than queued, because a queue here would spend GPU time on hypotheses
  that are already stale.

A partial failing is not a turn failing: an exception from a partial task is logged and dropped.
The trainee simply sees no interim text, which is precisely the configured-off behaviour.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

from app.application.ports.asr import AsrPartial, ASRProvider
from app.application.ports.call_transport import AudioFrame
from app.application.voice.config import MS_PER_S as _MS_PER_S
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import asr_partial_event
from app.domain.events.session_event import DomainEvent

__all__ = ["PartialAsrEmitter", "partial_request_id"]

logger = logging.getLogger(__name__)

AppendEvents = Callable[[Sequence[DomainEvent]], Awaitable[None]]
"""How the emitter appends: the pipeline's own serialised append path, never a second one."""


def partial_request_id(turn_id: uuid.UUID, index: int) -> str:
    """§4.5's request id for the `index`-th pseudo-streamed partial: `{turn_id}:p{n}`."""
    return f"{turn_id}:p{index}"


class PartialAsrEmitter:
    """Produces `ASR_PARTIAL` for the open turn, or nothing at all (§4.5).

    One instance per call. `enabled` folds §4.5's two gates into one boolean at construction; a
    disabled emitter starts no task, calls no provider and allocates nothing per frame, so the
    "partials off" path costs the audio loop a single `if`.
    """

    def __init__(
        self,
        *,
        asr: ASRProvider,
        append: AppendEvents,
        call_id: uuid.UUID,
        config: VoiceTurnConfig,
        offset_ms: Callable[[], int],
        enabled: bool,
    ) -> None:
        self._asr = asr
        self._append = append
        self._call_id = call_id
        self._config = config
        self._offset_ms = offset_ms
        self._enabled = enabled
        self._turn_id: uuid.UUID | None = None
        self._turn_index: int | None = None
        self._turn_start_ms = 0
        self._next_partial_index = 0
        self._emitted_at_ms = 0
        self._in_flight: asyncio.Task[None] | None = None
        self._frames: asyncio.Queue[AudioFrame | None] | None = None
        #: Every request id this emitter used, in order — what a test asserts `…:p0`, `…:p1` on.
        self.request_ids: list[str] = []

    @property
    def enabled(self) -> bool:
        """True when both §4.5 gates are open."""
        return self._enabled

    @property
    def in_flight(self) -> bool:
        """True while a partial task is running (the "at most one" rule)."""
        task = self._in_flight
        return task is not None and not task.done()

    def start_turn(self, *, turn_id: uuid.UUID, turn_index: int, start_ms: int) -> None:
        """A turn opened; reset the partial counter and start the native stream if there is one."""
        self._turn_id = turn_id
        self._turn_index = turn_index
        self._turn_start_ms = start_ms
        self._next_partial_index = 0
        self._emitted_at_ms = 0
        if not self._enabled:
            return
        if self._asr.supports_streaming:
            frames: asyncio.Queue[AudioFrame | None] = asyncio.Queue()
            self._frames = frames
            # The queue is handed to the task rather than read off `self`: the iterator's body
            # runs lazily, on the first `__anext__`, and by then `end_turn` may already have
            # cleared the attribute — which would end the stream before it saw a single frame.
            self._in_flight = asyncio.create_task(
                self._run_stream(turn_id, turn_index, frames), name=f"asr-partials-{turn_id}"
            )

    async def on_frame(self, frame: AudioFrame, *, accumulated: bytes, accumulated_ms: int) -> None:
        """One accumulated frame of the open turn.

        `accumulated` / `accumulated_ms` are the `TurnDetector`'s read-only view of the turn so
        far; this module never touches the detector's state machine.
        """
        if not self._enabled or self._turn_id is None:
            return
        if self._asr.supports_streaming:
            frames = self._frames
            if frames is not None:
                frames.put_nowait(frame)
            return
        if self.in_flight:
            # §4.5: at most one partial in flight — skip this tick rather than queue it.
            return
        if accumulated_ms - self._emitted_at_ms < self._config.partial_interval_ms:
            return
        self._emitted_at_ms = accumulated_ms
        index = self._next_partial_index
        self._next_partial_index += 1
        self._in_flight = asyncio.create_task(
            self._run_pseudo_partial(
                self._turn_id, self._turn_index or 0, accumulated, accumulated_ms, index
            ),
            name=f"asr-partial-{self._turn_id}-{index}",
        )

    async def end_turn(self) -> None:
        """`USER_SPEECH_ENDED`: nothing about this turn may outlive it (§4.5).

        The two strategies end differently because their "in flight" means different things:

        * a **pseudo-streamed** partial is a `transcribe()` over audio the pipeline has already
          finalized, so it is cancelled outright — §4.5's "a pending partial task is cancelled
          the moment `USER_SPEECH_ENDED` fires; its result is discarded, never merged";
        * a **native stream** is ended by closing its frame iterator, which is what a streaming
          recogniser is built for. The partials it already committed are the trainee's to see,
          and dropping them because the sentinel and the cancel raced would be arbitrary. It is
          still bounded: a stream that has not finished one `partial_interval_ms` after its input
          closed is cancelled like any other.
        """
        task, self._in_flight = self._in_flight, None
        frames, self._frames = self._frames, None
        if task is not None and not task.done():
            if frames is not None:
                frames.put_nowait(None)
                with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
                    await asyncio.wait_for(
                        asyncio.shield(task), self._config.partial_interval_ms / _MS_PER_S
                    )
            if not task.done():
                task.cancel()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._turn_id = None
        self._turn_index = None

    async def aclose(self) -> None:
        """End the call: nothing may outlive the pipeline."""
        await self.end_turn()

    # -- the two strategies -------------------------------------------------------------------

    async def _run_pseudo_partial(
        self, turn_id: uuid.UUID, turn_index: int, audio: bytes, accumulated_ms: int, index: int
    ) -> None:
        request_id = partial_request_id(turn_id, index)
        self.request_ids.append(request_id)
        try:
            result = await self._asr.transcribe(
                audio, self._config.sample_rate, request_id=request_id
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("a partial transcription failed for turn %s", turn_id, exc_info=True)
            return
        await self._emit(
            turn_id,
            turn_index,
            text=result.text,
            start_ms=self._turn_start_ms,
            end_ms=self._turn_start_ms + accumulated_ms,
            stability=None,
        )

    async def _run_stream(
        self, turn_id: uuid.UUID, turn_index: int, frames: asyncio.Queue[AudioFrame | None]
    ) -> None:
        request_id = partial_request_id(turn_id, 0)
        self.request_ids.append(request_id)
        try:
            async for item in self._asr.stream(self._frame_iterator(frames), request_id=request_id):
                if not isinstance(item, AsrPartial):
                    # The stream's own final is dropped: `AsrTurnResponder` owns `ASR_FINAL`.
                    continue
                await self._emit(
                    turn_id,
                    turn_index,
                    text=item.text,
                    start_ms=item.start_ms or self._turn_start_ms,
                    end_ms=item.end_ms,
                    stability=item.stability,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("the partial ASR stream failed for turn %s", turn_id, exc_info=True)

    async def _frame_iterator(
        self, frames: asyncio.Queue[AudioFrame | None]
    ) -> AsyncIterator[AudioFrame]:
        while True:
            frame = await frames.get()
            if frame is None:
                return
            yield frame

    async def _emit(
        self,
        turn_id: uuid.UUID,
        turn_index: int,
        *,
        text: str,
        start_ms: int,
        end_ms: int,
        stability: float | None,
    ) -> None:
        if not text.strip():
            # An empty hypothesis tells the trainee nothing and would still cost a `seq_no`.
            return
        await self._append(
            [
                asr_partial_event(
                    call_id=self._call_id,
                    turn_id=turn_id,
                    turn_index=turn_index,
                    offset_ms=self._offset_ms(),
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    asr_provider=self._asr.provider_name,
                    asr_model=self._asr.model_version,
                    stability=stability,
                )
            ]
        )
