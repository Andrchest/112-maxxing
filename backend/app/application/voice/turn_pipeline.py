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

**The pipeline owns no dialogue.** ASR, the interpreter, the Fact Access Gate, the generator, the
validator and TTS are the `TurnResponder` seam; E11 shipped `NullTurnResponder`, which emits
nothing at all, and E12's `app.application.voice.asr_responder.AsrTurnResponder` is the first real
one. The seam is typed and chained so that an epic adds a class rather than rewriting this file.

The one stage the pipeline runs *itself* is §4.5's partial ASR, and it does so for a structural
reason: a partial describes the **open** turn, which only the `_ingest` task and the detector can
see. It is handed to a `PartialAsrEmitter` that reads the detector's accumulation read-only and
whose every task is cancelled at `USER_SPEECH_ENDED` — a partial never outlives its turn, never
becomes a transcript row and never reaches a responder (SPEC §17).

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
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from app.application.ports.asr import ASRProvider
from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.call_transport import (
    AudioFrame,
    CallTransport,
    DeliveredAudio,
    PlaybackHandle,
    TransportEvent,
    TransportEventType,
)
from app.application.ports.clock import Clock
from app.application.ports.inference_guard import (
    STAGE_VAD,
    InferenceGuard,
    NoOpInferenceGuard,
)
from app.application.ports.vad import VadFrameResult, VADProvider
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import (
    VoiceEventAppender,
    call_ended_event,
    transport_event_to_domain_event,
    user_speech_ended_event,
    user_speech_started_event,
)
from app.application.voice.partial_asr import PartialAsrEmitter
from app.application.voice.recorder import SessionRecorder
from app.application.voice.resampler import Resampler
from app.application.voice.turn_detector import DetectedTurn, SpeechStarted, TurnDetector
from app.domain.common.ids import RoleStageId, SessionId
from app.domain.events.session_event import DomainEvent, SessionEvent

__all__ = [
    "BARGE_IN_BUDGET_CLEAR_OUTBOUND_MS",
    "BARGE_IN_BUDGET_DETECTOR_HANDOFF_MS",
    "BARGE_IN_BUDGET_NETWORK_JITTER_MS",
    "ActiveCallerUtterance",
    "NullTurnResponder",
    "ShowAsrPartials",
    "TranscribedTurn",
    "TranscribedTurnResponder",
    "TurnContext",
    "TurnPipeline",
    "TurnResponder",
]

logger = logging.getLogger(__name__)

ShowAsrPartials = Callable[[SessionId], Awaitable[bool]]
"""Reads `SessionPolicy.show_asr_partials` for one session (§4.5, D6).

It is a coroutine because the policy comes from the session aggregate, and it is called **once**,
when the call's pipeline starts: a session's mode cannot change mid-call, and a database round
trip per audio frame would be in the worst possible place.
"""

_CALL_ENDED_TRANSPORT_CLOSED = "TRANSPORT_CLOSED"
_CALL_ENDED_CANCELLED = "CANCELLED"
#: `60-inference-ops.md` §6 row 5 / SPEC §39 item 5: a media-plane disconnect that outlasts
#: `VoiceTurnConfig.reconnect_grace_s` ends the call. `CALL_ENDED.reason` is a free `str` in the
#: §10.13 catalog, so this needs no catalog change — the value is the HLD's, literally.
_CALL_ENDED_TRANSPORT_LOST = "TRANSPORT_LOST"

SleepMs = Callable[[int], Awaitable[None]]
"""How the reconnect-grace timer waits.

Injected rather than called as `asyncio.sleep` directly so the grace period is testable without a
test that actually waits thirty seconds: the fake transport drives a `FakeClock`, and a test
injects a sleeper that returns immediately. Nothing else in the pipeline sleeps."""


async def _real_sleep_ms(milliseconds: int) -> None:
    """The production `SleepMs`."""
    await asyncio.sleep(milliseconds / 1000)


@runtime_checkable
class ActiveCallerUtterance(Protocol):
    """One caller utterance in flight, as `_barge_in` needs to see it (§6.1 steps 2, 5, 6).

    This is E14's **one** hook into the pipeline, registered through
    `TurnContext.set_active_utterance`. `set_playback` stays beside it (E11's, and tests use it),
    but a `PlaybackHandle` alone is not enough for §6.1: steps 2, 5 and 6 need the TTS stream to
    cancel, the planned text and `fact_ids` the interrupted event carries, and the chunk ledger
    §6.3's `delivered_text` arithmetic reads. Rather than teach the pipeline about any of them,
    the responder registers one object that knows all of it and answers three questions.

    The implementation is `app.application.voice.tts_speech_sink._ActiveCallerUtterance`; the
    Protocol lives here because the pipeline may not import the sink (the sink imports
    `TurnContext`).
    """

    @property
    def playback(self) -> PlaybackHandle | None:
        """The live playback for this utterance, or `None` before the first frame."""

    def mark_interrupted(self) -> None:
        """Claim the utterance for a barge-in. Synchronous, and called *first* (§6.1)."""
        ...

    async def cancel_generation(self) -> None:
        """§6.1 step 2: stop the TTS stream after the unit in flight."""
        ...

    async def on_interrupted(
        self,
        *,
        interrupting_turn_id: uuid.UUID,
        delivered: DeliveredAudio | None,
        cutoff_latency_ms: int,
    ) -> None:
        """§6.1 steps 5-6: `CALLER_UTTERANCE_INTERRUPTED` and §6.4's rows."""
        ...


SetActiveUtterance = Callable[["ActiveCallerUtterance | None"], None]
"""How a responder tells the pipeline which caller utterance is in flight (E14)."""


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
    audio_segment_ids: Mapping[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    """`turn_id -> audio_segments.id` for every finalized, recorded turn of this call (§9.1).

    The recording row is created by `_finish_turn`, before the responder ever sees the turn, so
    `transcript_segments.audio_segment_id` can point at the very segment the `USER_SPEECH_ENDED`
    of the same turn named. It is a read-only view of the pipeline's own mapping — a responder
    looks a turn up, it never registers one.
    """

    speech_ended_offset_ms: Mapping[uuid.UUID, int] = field(default_factory=dict)
    """`turn_id -> USER_SPEECH_ENDED` offset, for SPEC §27's `speech_end_to_first_audio_ms` (E14).

    The responder cannot derive it: `DetectedTurn.end_ms` is where the *speech* ended, while the
    metric is measured from the moment the pipeline finalized the turn and the response chain
    began. Read-only, like the mapping above."""

    set_active_utterance: SetActiveUtterance | None = None
    """E14's one hook: register the caller utterance `_barge_in` must be able to reach (§6.1)."""


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


@dataclass(frozen=True, slots=True)
class TranscribedTurn:
    """A finalized trainee turn **plus its text** — the seam between ASR and the dialogue chain.

    `TurnResponder.respond` hands over a `DetectedTurn`, which is audio and timing and nothing
    else, so the stage behind ASR could not start: it would have to transcribe the audio a second
    time to learn what was said. This carries the values `AsrTurnResponder` already has after its
    one transaction, so the chain starts from the *same* transcript the `ASR_FINAL` event and the
    `transcript_segments` row carry, and can never drift from them (R1).

    `role_stage_id` is optional for the same reason `AsrTurnResponder._persist` tolerates a
    missing one: §20.6 makes `dialogue_turns.role_stage_id` NOT NULL, and a session with no role
    stage gets a transcript and an event but no turn row. The dialogue chain still runs — losing
    a read-model row must not lose the caller's answer.
    """

    turn: DetectedTurn
    text: str
    confidence: float | None
    turn_index: int
    role_stage_id: RoleStageId | None
    transcript_segment_id: uuid.UUID | None


@runtime_checkable
class TranscribedTurnResponder(Protocol):
    """What `AsrTurnResponder` hands a non-empty final transcript to (§3.7, R1).

    The second link of the responder chain: E13's interpret → gate → generate → validate, and
    behind it E14's TTS. Like `TurnResponder` it is cancelled — not asked to stop — when a newer
    turn arrives, so an implementation must treat `asyncio.CancelledError` as "the trainee is
    talking again" (§6.1 step 2).
    """

    async def respond_transcribed(self, transcribed: TranscribedTurn, context: TurnContext) -> None:
        """Produce the caller's answer to the transcribed turn."""
        ...


class NullTurnResponder:
    """A `TurnResponder` that does nothing (D13, E11).

    E11 builds the transport, the detector, the playback and the recording; it deliberately has
    no dialogue to produce, and a stub that invented one would be a silently unmet requirement.
    `responded` records the turns it was handed, so the pipeline's wiring is assertable without a
    single model.

    E12 replaced it in the wiring with `AsrTurnResponder`; it stays because a pipeline test that
    is about the *pipeline* should not need a model, fake or otherwise.

    E13 put the interpreter → Fact Access Gate → generator → validator chain behind
    `AsrTurnResponder.next_stage` (`app.application.dialogue.responder.DialogueResponder`), not
    here: this responder is the *pipeline's* stub and stays modelless on purpose.

    E14 put streaming TTS behind `DialogueResponder`'s `CallerSpeechSink`
    (`app.application.voice.tts_speech_sink.TtsSpeechSink`) and the outbound half of barge-in in
    `_barge_in` above; this responder still speaks nothing, which is the point of it.
    """

    def __init__(self) -> None:
        #: Every turn handed over, in arrival order.
        self.responded: list[DetectedTurn] = []

    async def respond(self, turn: DetectedTurn, context: TurnContext) -> None:
        """Record the turn and return; no event, no audio, no model."""
        self.responded.append(turn)


#: §6.2's fixed budget rows that are not read off any `VoiceTurnConfig` field — rows 3 and 4
#: (in-process hand-off and the local `clear_outbound()` FFI call) and row 6 (network + browser
#: jitter buffer, UNVERIFIED, measured by `benchmark_e2e.py`). Named here, beside `_barge_in`
#: (the method that measures the real `cutoff_latency_ms`), so a documented-budget test can assert
#: `vad_frame_ms + barge_in_min_speech_ms + row3 + row4 + tts_chunk_ms + row6 < 250` without a
#: second copy of the doc's numbers (this task's report, CHANGE item 3).
BARGE_IN_BUDGET_DETECTOR_HANDOFF_MS = 5
"""§6.2 row 3: detector + task hand-off, in-process, one `asyncio` queue put + a coroutine step."""

BARGE_IN_BUDGET_CLEAR_OUTBOUND_MS = 5
"""§6.2 row 4: `clear_outbound()` round trip — a local FFI call, no network."""

BARGE_IN_BUDGET_NETWORK_JITTER_MS = 40
"""§6.2 row 6: network + jitter buffer to the browser. UNVERIFIED — measured by
`benchmark_e2e.py`."""


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
        asr: ASRProvider | None = None,
        show_asr_partials: ShowAsrPartials | None = None,
        guard: InferenceGuard | None = None,
        sleep_ms: SleepMs | None = None,
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
        #: §4.4's `guard_inference(stage)`. The default observes nothing, so a pipeline built
        #: without one behaves exactly as it did before E18 (D13).
        self._guard: InferenceGuard = guard if guard is not None else NoOpInferenceGuard()
        self._sleep_ms: SleepMs = sleep_ms if sleep_ms is not None else _real_sleep_ms
        #: §4.5's partials are the pipeline's own stage; without a provider there are none.
        self._asr = asr
        self._show_asr_partials = show_asr_partials
        self._partials: PartialAsrEmitter | None = None
        #: `turn_id -> audio_segments.id`, handed to every responder through `TurnContext`.
        self._audio_segment_ids: dict[uuid.UUID, uuid.UUID] = {}
        #: `turn_id -> USER_SPEECH_ENDED` offset (SPEC §27's `speech_end_to_first_audio_ms`, E14).
        self._speech_ended_offset_ms: dict[uuid.UUID, int] = {}
        #: The caller utterance E14's sink registered, if one is in flight (§6.1).
        self._active_utterance: ActiveCallerUtterance | None = None
        self._turns: asyncio.Queue[DetectedTurn] = asyncio.Queue(maxsize=1)
        self._append_lock = asyncio.Lock()
        self._response_task: asyncio.Task[None] | None = None
        self._playback: PlaybackHandle | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._call_started_offset_ms: int | None = None
        self._disconnected_at_offset_ms: int | None = None
        #: The live `reconnect_grace_s` timer, if the transport is currently disconnected (§6).
        self._grace_task: asyncio.Task[None] | None = None
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
            audio_segment_ids=MappingProxyType(self._audio_segment_ids),
            speech_ended_offset_ms=MappingProxyType(self._speech_ended_offset_ms),
            set_active_utterance=self.set_active_utterance,
        )

    @property
    def playback_active(self) -> bool:
        """True while a caller utterance is being played out (the detector's barge-in flag)."""
        playback = self._live_playback()
        return playback is not None and playback.is_active()

    def _live_playback(self) -> PlaybackHandle | None:
        """The handle to cancel: the registered utterance's, else `set_playback`'s (E14)."""
        active = self._active_utterance
        if active is not None and active.playback is not None:
            return active.playback
        return self._playback

    def set_playback(self, handle: PlaybackHandle | None) -> None:
        """Tell the pipeline which `PlaybackHandle` is live (called by the responder, E14).

        Kept beside `set_active_utterance` because a test that is about *playback* should not
        have to build a whole caller utterance; a registered utterance wins when both are set.
        """
        self._playback = handle

    def set_active_utterance(self, handle: ActiveCallerUtterance | None) -> None:
        """E14's hook: the caller utterance `_barge_in` must be able to reach (§6.1 steps 2/5/6).

        One hook, not three: §6.1 needs the TTS stream, the playback handle and the record of
        what was planned, and a pipeline that held all three separately could be told about them
        in an order that leaves it cancelling a stream whose utterance it cannot describe.
        """
        self._active_utterance = handle
        if handle is None:
            self._playback = None

    async def run(self) -> None:
        """Run the three tasks until the transport closes or `stop()` is called."""
        self._detector.reset()
        self._resampler.reset()
        self._vad.reset()
        self._call_started_offset_ms = self._appender.offset_ms()
        await self._start_partials()
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

    async def _start_partials(self) -> None:
        """Build the `PartialAsrEmitter` for this call, if §4.5's two gates are both open.

        The session policy is read here and only here — once per call. A session that switches
        partials off (`ASSESSMENT`, §10.10) gets an emitter that is constructed and disabled
        rather than no emitter at all, so the "why are there no partials" answer is one attribute
        rather than a `None` that could mean three different things.
        """
        if self._asr is None:
            self._partials = None
            return
        enabled = self._config.partial_asr_enabled
        if enabled and self._show_asr_partials is not None:
            enabled = await self._show_asr_partials(self._session_id)
        self._partials = PartialAsrEmitter(
            asr=self._asr,
            append=self._append,
            call_id=self._call_id,
            config=self._config,
            offset_ms=self._appender.offset_ms,
            enabled=enabled,
        )

    @property
    def partials(self) -> PartialAsrEmitter | None:
        """The call's partial-ASR emitter, once `run()` has started it."""
        return self._partials

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
        result = await self._guard.run(
            STAGE_VAD,
            lambda: self._vad.process(frame),
            fallback=lambda: self._silent_frame_result(frame),
        )
        step = self._detector.process(frame, result, playback_active=self.playback_active)
        if step.started is not None:
            if self._partials is not None:
                self._partials.start_turn(
                    turn_id=step.started.turn_id,
                    turn_index=step.started.turn_index,
                    start_ms=step.started.start_ms,
                )
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
                await self._barge_in(step.started)
        if self._partials is not None and self._detector.turn_open:
            await self._partials.on_frame(
                frame,
                accumulated=self._detector.accumulated_audio,
                accumulated_ms=self._detector.accumulated_ms,
            )
        if step.finished is not None:
            # §4.5: every partial task dies with the turn it was describing, before the final
            # transcription starts. Its result is discarded, never merged.
            if self._partials is not None:
                await self._partials.end_turn()
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
            self._audio_segment_ids[turn.turn_id] = segment.id
        ended_offset_ms = self._appender.offset_ms()
        self._speech_ended_offset_ms[turn.turn_id] = ended_offset_ms
        event = user_speech_ended_event(
            turn,
            call_id=self._call_id,
            offset_ms=ended_offset_ms,
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

    async def _barge_in(self, started: SpeechStarted) -> None:
        """SPEC §18 / §6.1 steps 2-6, in the order §6.1 fixes.

        Steps 2-4 run concurrently under one `asyncio.gather`, and **step 3 is the first member**:
        clearing the outbound queue is what actually stops sound, and §6.1 says it must never
        wait on step 2. Step 7 needs no code — the detector is already IN_SPEECH and the trainee's
        turn goes down the ordinary path.

        A barge-in that arrives while the response is still being generated (no audio yet) cancels
        the responder, appends **no** `CALLER_UTTERANCE_INTERRUPTED` — nothing was spoken, so
        there is nothing to have interrupted — and leaves the responder to record its own
        `CANCELLED` metric (E12/E13 already do).
        """
        active = self._active_utterance
        playback = self._live_playback()
        # First, and synchronously: claim the utterance, so the sink's own `speak()` coroutine —
        # which step 2 is about to cancel — can never emit `CALLER_TTS_ENDED` for it (INV 12).
        if active is not None:
            active.mark_interrupted()
        delivered: DeliveredAudio | None = None

        async def _clear_queue() -> None:
            """Step 3."""
            await self._transport.clear_outbound()

        async def _cancel_generation() -> None:
            """Step 2: the TTS stream, and the responder task that owns the LLM stream."""
            if active is not None:
                await active.cancel_generation()
            response = self._response_task
            if response is not None and not response.done():
                response.cancel()

        async def _stop_playback() -> None:
            """Step 4."""
            nonlocal delivered
            if playback is not None and playback.is_active():
                delivered = await playback.cancel()

        await asyncio.gather(_clear_queue(), _cancel_generation(), _stop_playback())
        # §6.3: measured every time, never assumed — `clear_outbound()` completion minus the
        # trainee's speech **onset**.
        #
        # HLD gap (see this task's report): §6.3 says "minus the `USER_SPEECH_STARTED` offset",
        # but that event's `at_offset_ms` is `SpeechStarted.start_ms`, which §4.4 defines as
        # `capture_offset_ms - pre_roll_ms` — the start of the *kept pre-roll*, up to 300 ms
        # before the trainee made a sound. Measuring from it would add `pre_roll_ms` of audio
        # that predates the barge-in to every reading and put the §6.2 budget out of reach by
        # construction. §6.2's own definition — "onset is the first sample of trainee speech" —
        # is the reading closest to SPEC §18, so the pre-roll is added back here.
        onset_ms = started.start_ms + self._config.pre_roll_ms
        cutoff_latency_ms = max(0, self._appender.offset_ms() - onset_ms)
        if active is None:
            return
        # Steps 5 and 6. They live on the utterance because only it knows the planned text, the
        # chunk alignment ledger and the `fact_ids` that must stay unrevealed (§6.4, INV 12).
        await active.on_interrupted(
            interrupting_turn_id=started.turn_id,
            delivered=delivered,
            cutoff_latency_ms=cutoff_latency_ms,
        )
        self._active_utterance = None
        self._playback = None

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

    async def _silent_frame_result(self, frame: AudioFrame) -> VadFrameResult:
        """The VAD stage's deterministic fallback: "this frame is not speech" (§4.4 step 2).

        VAD is the one guarded stage with no fallback ladder of its own — the detector cannot be
        handed an exception — so the guard produces the answer here. Scoring the frame as silence
        is the conservative choice: a turn is never *started* by a failed model, an open turn ends
        on the configured endpoint silence, and the trainee's audio is still recorded and still
        teed. A failing VAD therefore degrades to "nobody is speaking", never to a phantom turn.
        """
        return VadFrameResult(
            speech_probability=0.0,
            frame_start_ms=frame.capture_offset_ms,
            frame_duration_ms=frame.duration_ms,
        )

    async def _handle_transport_event(self, event: TransportEvent) -> None:
        downtime_ms = 0
        if event.type is TransportEventType.DISCONNECTED:
            self._disconnected_at_offset_ms = event.at_offset_ms
            self._start_reconnect_grace()
        elif event.type is TransportEventType.RECONNECTED:
            if self._disconnected_at_offset_ms is not None:
                downtime_ms = max(0, event.at_offset_ms - self._disconnected_at_offset_ms)
            self._disconnected_at_offset_ms = None
            self._cancel_reconnect_grace()
        domain_event = transport_event_to_domain_event(
            event, offset_ms=self._appender.offset_ms(), downtime_ms=downtime_ms
        )
        if domain_event is not None:
            await self._append([domain_event])

    # -- the reconnect grace period (§6 row 5, SPEC §39 item 5) -------------------------------

    def _start_reconnect_grace(self) -> None:
        """Arm the `reconnect_grace_s` timer on a DISCONNECTED (idempotent).

        The timer lives **here**, in the application pipeline, and never in the LiveKit SDK
        wrapper: the transport's job is to say what the media plane did, and "how long a
        disconnect may last before the call is over" is a configured product rule (SPEC §17),
        testable against the fake transport and a fake clock with no SDK in sight.
        """
        if self._grace_task is not None and not self._grace_task.done():
            return
        self._grace_task = asyncio.create_task(
            self._reconnect_grace(), name="voice-reconnect-grace"
        )

    def _cancel_reconnect_grace(self) -> None:
        """Disarm the timer: a RECONNECTED inside the grace period changes nothing else.

        Session and domain state survive untouched — the pipeline keeps its detector, its open
        turn bookkeeping and its appended events, and the only trace of the whole episode is the
        `TRANSPORT_DISCONNECTED` / `TRANSPORT_RECONNECTED` pair (§6 row 5).
        """
        task = self._grace_task
        self._grace_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _reconnect_grace(self) -> None:
        """Wait out `reconnect_grace_s`; if still disconnected, end the call as TRANSPORT_LOST."""
        grace_ms = self._config.reconnect_grace_s * 1000
        try:
            await self._sleep_ms(grace_ms)
        except asyncio.CancelledError:
            return
        if self._stopping.is_set() or self._disconnected_at_offset_ms is None:
            return
        logger.info(
            "transport gone for more than reconnect_grace_s=%d s; ending call %s as %s",
            self._config.reconnect_grace_s,
            self._call_id,
            _CALL_ENDED_TRANSPORT_LOST,
        )
        # Through the ordinary call-end path: `stop()` sets the reason and `_close_call()` appends
        # the one `CALL_ENDED`. Nothing here writes `simulation_sessions.state` — the session is
        # left ACTIVE "for the instructor to decide" (§6 row 5), which is also SPEC §39's closing
        # rule: never silently reset the simulation.
        await self.stop(_CALL_ENDED_TRANSPORT_LOST)

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
        if self._partials is not None:
            await self._partials.aclose()
        if self._recorder is not None:
            self._recorder.close()

    async def _shutdown(self, *tasks: asyncio.Task[None]) -> None:
        self._cancel_reconnect_grace()
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
