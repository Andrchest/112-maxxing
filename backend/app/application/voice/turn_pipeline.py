"""`TurnPipeline` — the per-call asyncio task graph (§3.7, D9, SPEC §16, §18, §42 item 14).

Three long-lived tasks per call, exactly as §3.7 specifies:

1. `_ingest` — `inbound_audio()` → `Resampler` → `VADProvider` → `TurnDetector`, teeing the
   trainee recording (§9.1);
2. `_respond` — consumes `DetectedTurn`s from a queue of **depth 1** and hands each to the
   injected `TurnResponder`. A second finalized turn arriving while one is in flight cancels the
   in-flight response: that is the cross-turn half of barge-in, and it is why the queue is depth
   one and not unbounded — a caller answering a question the trainee has already moved past is
   worse than no answer;
3. `_control` — the transport's `events()` and the cross-process cancellation signal
   (`voice:cancel:{session_id}`, consumed by `voice_agent.main` and pushed in here).

**E11 owns no dialogue.** ASR, the interpreter, the Fact Access Gate, the generator, the validator
and TTS are the `TurnResponder` seam; E11 ships `NullTurnResponder`, which emits nothing at all.
E12–E14 supply the real one, and the seam is typed so that they add a class rather than rewrite
this file.

Two robustness properties this file is responsible for:

* **A responder exception never kills `_ingest`** (SPEC §42 item 14, "model failure does not erase
  simulation data"). The response task is awaited inside `_respond` with a broad `except`, logged,
  and the loop continues; audio keeps being ingested, recorded and turned into events throughout.
* **Event order is the documented order.** Appends from all three tasks are serialised behind one
  lock, so `USER_SPEECH_STARTED` can never overtake the `USER_SPEECH_ENDED` of the turn before it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.call_transport import (
    AudioFrame,
    CallTransport,
    PlaybackHandle,
    TransportEvent,
    TransportEventType,
)
from app.application.ports.clock import Clock
from app.application.ports.vad import VADProvider
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import (
    VoiceEventAppender,
    call_ended_event,
    transport_event_to_domain_event,
    user_speech_ended_event,
    user_speech_started_event,
)
from app.application.voice.recorder import SessionRecorder
from app.application.voice.resampler import Resampler
from app.application.voice.turn_detector import DetectedTurn, TurnDetector
from app.domain.common.ids import SessionId
from app.domain.events.session_event import DomainEvent, SessionEvent

__all__ = ["NullTurnResponder", "TurnContext", "TurnPipeline", "TurnResponder"]

logger = logging.getLogger(__name__)

_CALL_ENDED_TRANSPORT_CLOSED = "TRANSPORT_CLOSED"
_CALL_ENDED_CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class TurnContext:
    """Everything a `TurnResponder` may see. Deliberately narrow (D3, D10).

    It carries no `WorldTruth`, no `CallerBelief` and no `OperatorCard`: a responder reaches
    scenario facts only through the Fact Access Gate (SPEC §21), which is a collaborator E13
    injects into its own responder, never something this context hands over.
    """

    session_id: SessionId
    call_id: uuid.UUID
    config: VoiceTurnConfig
    transport: CallTransport
    appender: VoiceEventAppender
    recorder: SessionRecorder | None


@runtime_checkable
class TurnResponder(Protocol):
    """What the pipeline calls for a finalized, non-discarded turn (§3.7).

    The whole of ASR → interpret → gate → generate → validate → TTS → play lives behind this one
    method (E12–E14). It is cancelled — not asked to stop — when a newer turn arrives, so an
    implementation must treat `asyncio.CancelledError` as "the trainee is talking again" and
    clean up its own streams (§6.1 step 2).
    """

    async def respond(self, turn: DetectedTurn, context: TurnContext) -> None:
        """Produce and play the caller's answer to `turn`."""
        ...


class NullTurnResponder:
    """A `TurnResponder` that does nothing (D13, E11).

    E11 builds the transport, the detector, the playback and the recording; it deliberately has
    no dialogue to produce, and a stub that invented one would be a silently unmet requirement.
    `responded` records the turns it was handed, so the pipeline's wiring is assertable without a
    single model.

    TODO(E12): `AsrTurnResponder` — the first real implementation, which adds ASR and the
    `ASR_PARTIAL` / `ASR_FINAL` events of §4.5.
    TODO(E13): the interpreter, the Fact Access Gate, the generator and the validator.
    TODO(E14): streaming TTS and the outbound half of barge-in (§6.1 steps 2, 5, 6).
    """

    def __init__(self) -> None:
        #: Every turn handed over, in arrival order.
        self.responded: list[DetectedTurn] = []

    async def respond(self, turn: DetectedTurn, context: TurnContext) -> None:
        """Record the turn and return; no event, no audio, no model."""
        self.responded.append(turn)


class TurnPipeline:
    """One call's turn loop (§3.7)."""

    def __init__(
        self,
        *,
        session_id: SessionId,
        call_id: uuid.UUID,
        transport: CallTransport,
        vad: VADProvider,
        detector: TurnDetector,
        appender: VoiceEventAppender,
        clock: Clock,
        config: VoiceTurnConfig,
        resampler: Resampler | None = None,
        recorder: SessionRecorder | None = None,
        responder: TurnResponder | None = None,
        cancel_signals: AsyncIterator[str] | None = None,
    ) -> None:
        self._session_id = session_id
        self._call_id = call_id
        self._transport = transport
        self._vad = vad
        self._detector = detector
        self._appender = appender
        self._clock = clock
        self._config = config
        self._resampler = resampler or Resampler(
            target_sample_rate=config.sample_rate, frame_samples=vad.frame_samples
        )
        self._recorder = recorder
        self._responder: TurnResponder = responder or NullTurnResponder()
        self._cancel_signals = cancel_signals
        self._turns: asyncio.Queue[DetectedTurn] = asyncio.Queue(maxsize=1)
        self._append_lock = asyncio.Lock()
        self._response_task: asyncio.Task[None] | None = None
        self._playback: PlaybackHandle | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._call_started_offset_ms: int | None = None
        self._disconnected_at_offset_ms: int | None = None
        self._ended_reason: str | None = None
        #: Every event this pipeline appended, in append order — what a test asserts on.
        self.appended: list[SessionEvent] = []
        #: Every exception a responder raised, in raise order (SPEC §42 item 14).
        self.responder_failures: list[BaseException] = []

    @property
    def context(self) -> TurnContext:
        """What a `TurnResponder` is handed."""
        return TurnContext(
            session_id=self._session_id,
            call_id=self._call_id,
            config=self._config,
            transport=self._transport,
            appender=self._appender,
            recorder=self._recorder,
        )

    @property
    def playback_active(self) -> bool:
        """True while a caller utterance is being played out (the detector's barge-in flag)."""
        playback = self._playback
        return playback is not None and playback.is_active()

    def set_playback(self, handle: PlaybackHandle | None) -> None:
        """Tell the pipeline which `PlaybackHandle` is live (called by the responder, E14)."""
        self._playback = handle

    async def run(self) -> None:
        """Run the three tasks until the transport closes or `stop()` is called."""
        self._detector.reset()
        self._resampler.reset()
        self._vad.reset()
        self._call_started_offset_ms = self._appender.offset_ms()
        ingest = asyncio.create_task(self._ingest(), name="voice-ingest")
        respond = asyncio.create_task(self._respond(), name="voice-respond")
        control = asyncio.create_task(self._control(), name="voice-control")
        self._tasks = [ingest, respond, control]
        try:
            await ingest
        finally:
            await self._shutdown(respond, control)

    async def stop(self, reason: str = _CALL_ENDED_CANCELLED) -> None:
        """Ask the pipeline to wind down (hang-up, abort, process shutdown)."""
        self._ended_reason = reason
        self._stopping.set()
        for task in self._tasks:
            if not task.done():
                task.cancel()

    # -- task 1: ingest -----------------------------------------------------------------------

    async def _ingest(self) -> None:
        try:
            async for frame in self._transport.inbound_audio():
                if self._stopping.is_set():
                    break
                for resampled in self._resampler.process(frame):
                    await self._handle_frame(resampled)
        except asyncio.CancelledError:
            raise
        finally:
            await self._close_call()

    async def _handle_frame(self, frame: AudioFrame) -> None:
        if self._recorder is not None:
            self._recorder.tee("TRAINEE", frame)
        result = await self._vad.process(frame)
        step = self._detector.process(frame, result, playback_active=self.playback_active)
        if step.started is not None:
            await self._append(
                [
                    user_speech_started_event(
                        step.started,
                        call_id=self._call_id,
                        offset_ms=self._appender.offset_ms(),
                        vad_provider=self._vad.provider_name,
                    )
                ]
            )
            if step.started.was_during_playback:
                await self._barge_in()
        if step.finished is not None:
            await self._finish_turn(step.finished)

    async def _finish_turn(self, turn: DetectedTurn) -> None:
        segments: list[StoredAudioSegment] = []
        payload_extra: dict[str, str] = {}
        if self._recorder is not None and not turn.discarded_short:
            segment = self._recorder.segment_for(
                "TRAINEE", start_ms=turn.start_ms, end_ms=turn.end_ms
            )
            segments.append(segment)
            payload_extra["audio_segment_id"] = str(segment.id)
        event = user_speech_ended_event(
            turn,
            call_id=self._call_id,
            offset_ms=self._appender.offset_ms(),
            endpoint_silence_ms=self._config.endpoint_silence_ms,
        )
        if payload_extra:
            event = event.model_copy(update={"payload": {**event.payload, **payload_extra}})
        await self._append([event], segments=segments)
        if turn.discarded_short:
            # §4.4: logged, never transcribed. No ASR, no response, no recording row.
            return
        await self._enqueue(turn)

    async def _enqueue(self, turn: DetectedTurn) -> None:
        """Put the turn on the depth-1 queue, cancelling whatever is in flight (§3.7)."""
        response = self._response_task
        if response is not None and not response.done():
            response.cancel()
        with contextlib.suppress(asyncio.QueueEmpty):
            self._turns.get_nowait()
        await self._turns.put(turn)

    # -- task 2: respond ----------------------------------------------------------------------

    async def _respond(self) -> None:
        while True:
            turn = await self._turns.get()
            task = asyncio.create_task(self._responder.respond(turn, self.context))
            self._response_task = task
            try:
                await task
            except asyncio.CancelledError:
                if self._stopping.is_set():
                    raise
                # A newer turn cancelled this response; that is the design, not a failure.
                logger.debug("response for turn %s cancelled by a newer turn", turn.turn_id)
            except Exception as exc:
                self.responder_failures.append(exc)
                logger.exception("turn responder failed for turn %s", turn.turn_id)
            finally:
                if self._response_task is task:
                    self._response_task = None

    async def _barge_in(self) -> None:
        """SPEC §18 steps 3–4, in the order §6.1 fixes: clear the queue, then stop playback."""
        playback = self._playback
        await self._transport.clear_outbound()
        if playback is not None and playback.is_active():
            await playback.cancel()
        # TODO(E14): steps 2, 5 and 6 — cancel the TTS/LLM streams, emit
        # `CALLER_UTTERANCE_INTERRUPTED` with `delivered_text`, and persist the truncated caller
        # segment. They need a caller utterance to interrupt, which E11 never produces.

    # -- task 3: control ----------------------------------------------------------------------

    async def _control(self) -> None:
        tasks = [asyncio.create_task(self._transport_events(), name="voice-transport-events")]
        if self._cancel_signals is not None:
            tasks.append(asyncio.create_task(self._cancellations(), name="voice-cancel"))
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    async def _transport_events(self) -> None:
        async for event in self._transport.events():
            await self._handle_transport_event(event)

    async def _handle_transport_event(self, event: TransportEvent) -> None:
        downtime_ms = 0
        if event.type is TransportEventType.DISCONNECTED:
            self._disconnected_at_offset_ms = event.at_offset_ms
        elif event.type is TransportEventType.RECONNECTED:
            if self._disconnected_at_offset_ms is not None:
                downtime_ms = max(0, event.at_offset_ms - self._disconnected_at_offset_ms)
            self._disconnected_at_offset_ms = None
        domain_event = transport_event_to_domain_event(
            event, offset_ms=self._appender.offset_ms(), downtime_ms=downtime_ms
        )
        if domain_event is not None:
            await self._append([domain_event])

    async def _cancellations(self) -> None:
        signals = self._cancel_signals
        if signals is None:  # pragma: no cover - guarded by the caller
            return
        async for reason in signals:
            logger.info("voice:cancel for session %s: %s", self._session_id, reason)
            await self.stop(reason)
            return

    # -- shutdown -----------------------------------------------------------------------------

    async def _close_call(self) -> None:
        """The "any | transport closed" row of §4.4, then `CALL_ENDED` (§3.7)."""
        for resampled in self._resampler.flush():
            if self._recorder is not None:
                self._recorder.tee("TRAINEE", resampled)
        step = self._detector.close()
        if step.finished is not None:
            await self._finish_turn(step.finished)
        at_offset_ms = self._appender.offset_ms()
        started = self._call_started_offset_ms or 0
        await self._append(
            [
                call_ended_event(
                    call_id=self._call_id,
                    offset_ms=at_offset_ms,
                    at_offset_ms=at_offset_ms,
                    duration_ms=max(0, at_offset_ms - started),
                    reason=self._ended_reason or _CALL_ENDED_TRANSPORT_CLOSED,
                )
            ]
        )
        if self._recorder is not None:
            self._recorder.close()

    async def _shutdown(self, *tasks: asyncio.Task[None]) -> None:
        response = self._response_task
        if response is not None and not response.done():
            response.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await response
        for task in tasks:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # -- the one append path ------------------------------------------------------------------

    async def _append(
        self, events: Sequence[DomainEvent], *, segments: Sequence[StoredAudioSegment] = ()
    ) -> None:
        async with self._append_lock:
            appended = await self._appender.append(events, segments=segments)
        self.appended.extend(appended)
