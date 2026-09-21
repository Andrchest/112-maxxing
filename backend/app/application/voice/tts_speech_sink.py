"""`TtsSpeechSink` — the TTS stage of the turn (§3.7, §6, §8, §9.1; SPEC §18, §19, §25, §26, §27).

E13 decides *what* the caller says and hands it over as a `PlannedCallerUtterance`; this is the
`CallerSpeechSink` that decides how it is **heard**, and it is the last stage of SPEC §16's order.
What it does, in this order:

1. build the `TtsVoiceSpec` from the scenario's `CallerProfile` (`voice_id`, `speaking_rate`),
   falling back to `SIM_TTS_VOICE_ID` / `SIM_TTS_SPEAKING_RATE` when a session has no profile, and
   layer `planned.emotion` onto it (MANAGER RULING on E14-B's gap 1: emotion reaches the voice
   through this additive `TtsVoiceSpec` field, never through mutable provider state);
2. `ChunkedTtsStream` over the configured `TTSProvider` — sentence-chunked for *every* provider
   (`sentence_chunker`), because that is what gives `cancel()` the granularity §6.2's budget needs;
3. resample to the transport's rate with the existing `Resampler` when
   `TTSProvider.output_sample_rate` differs, tee every frame into `recorder.tee("CALLER", …)`
   (§9.1) and hand the stream to `CallTransport.play`;
4. register the utterance with the pipeline (`TurnContext.set_active_utterance`) so `_barge_in`
   can reach the TTS stream and the playback handle — the **one** hook this epic adds;
5. `CALLER_TTS_STARTED` when the first frame reaches the transport, then, on a natural end,
   `CALLER_TTS_ENDED` + the caller `audio_segments` row + the `CALLER` `transcript_segments` row +
   the `dialogue_turns` caller columns **in one unit of work**, the way
   `AsrTurnResponder._persist` does it;
6. then, and only then, `FACTS_DELIVERED` and one `FactRevealedTrigger` per delivered fact.

**Facts are revealed by code (D10, INV 12).** `FACTS_DELIVERED` is appended only after an
*uninterrupted* `CALLER_TTS_ENDED`. An interruption is handled by the pipeline's `_barge_in`
through `ActiveCallerUtterance.on_interrupted` — it appends `CALLER_UTTERANCE_INTERRUPTED` with
`fact_ids_not_revealed`, writes §6.4's rows, and appends neither `CALLER_TTS_ENDED` nor
`FACTS_DELIVERED`. The sink's own `speak()` coroutine is cancelled by that same barge-in, and the
`_interrupted` flag is what stops it from racing the pipeline to emit an ending it did not have.

**When the provider fails (INV 14 for TTS).** `MODEL_ERROR{stage: "TTS"}` → the whole utterance is
retried once on `tts_fallback_provider` (`MODEL_FALLBACK_USED`) → if that fails too the turn ends
**silent but complete**: no `CALLER_TTS_ENDED`, no `FACTS_DELIVERED`, the `CALLER` transcript row
is still written with `text = planned_text` so the audit record of what was meant survives, the
turn row records `delivered_text = ""`, the session stays ACTIVE and the next turn works.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import datetime

from app.application.dialogue.emotion_updates import apply_dialogue_emotion_trigger
from app.application.dialogue.speech_sink import PlannedCallerUtterance
from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.call_transport import AudioFrame, DeliveredAudio, PlaybackHandle
from app.application.ports.clock import Clock
from app.application.ports.metrics_recorder import (
    InferenceMetric,
    InferenceStage,
    MetricsRecorder,
    MetricStatus,
)
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.application.ports.tts import TtsChunk, TTSProvider, TtsTimeoutError, TtsVoiceSpec
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.voice.config import MS_PER_S, VoiceTurnConfig
from app.application.voice.events import (
    caller_tts_ended_event,
    caller_tts_started_event,
    caller_utterance_interrupted_event,
    facts_delivered_event,
    model_error_event,
    model_fallback_used_event,
)
from app.application.voice.resampler import Resampler
from app.application.voice.sentence_chunker import DEFAULT_MAX_UNIT_CHARS, ChunkedTtsStream
from app.application.voice.turn_pipeline import TurnContext
from app.domain.caller.emotion import FactRevealedTrigger, InterruptionCountTrigger
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion

__all__ = [
    "TTS_COMPONENT",
    "TtsSpeechSink",
    "delivered_text_for",
]

logger = logging.getLogger(__name__)

#: `MODEL_ERROR.component` / `inference_metrics.component` for this stage — §10.13's value.
TTS_COMPONENT = "TTS"
#: `MODEL_ERROR.error_code` when the provider exceeded `tts_timeout_ms`.
ERROR_CODE_TIMEOUT = "TIMEOUT"
#: `MODEL_FALLBACK_USED.fallback_kind` when the whole utterance is retried on another provider.
FALLBACK_KIND_PROVIDER = "TTS_FALLBACK_PROVIDER"
#: `EmotionTrigger` kinds, as `CALLER_EMOTION_CHANGED.trigger_kind` records them (§10.5).
TRIGGER_FACT_REVEALED = "FACT_REVEALED"
TRIGGER_INTERRUPTION_COUNT = "INTERRUPTION_COUNT"


# ---------------------------------------------------------------------------------------------
# §6.3: `delivered_text`
# ---------------------------------------------------------------------------------------------


def delivered_text_for(
    planned_text: str,
    chunks: Sequence[TtsChunk],
    *,
    delivered_audio_ms: int,
    total_audio_ms_generated: int,
) -> tuple[str, bool]:
    """§6.3's `delivered_text`, and whether the boundary it used was exact.

    Both readings of §6.3 are implemented, and which one applies is a property of the *adapter*,
    not a configuration:

    1. find the last chunk whose cumulative audio is `<= delivered_audio_ms`;
    2. if that chunk carries exact alignment, the answer is `planned_text[: text_offset_end]`;
    3. otherwise take `round(r * len(words))` words, `r = delivered / total`, and say
       `alignment_is_exact = False` so a reader knows the boundary is approximate;
    4. the result is right-stripped, and a trailing partial word is dropped by construction (a
       word boundary is where the proportional branch cuts).

    Pure and synchronous, so the table of edge cases — nothing delivered, everything delivered,
    a delivered figure above the generated total — is a unit test and not a pipeline run.
    """
    if delivered_audio_ms <= 0 or not chunks:
        # Nothing was heard, and that is known exactly: the trainee interrupted before the first
        # frame left, so no prefix of the text reached them.
        return "", True
    if total_audio_ms_generated > 0 and delivered_audio_ms >= total_audio_ms_generated:
        last = chunks[-1]
        if last.alignment_is_exact:
            return planned_text[: last.text_offset_end].rstrip(), True
    cumulative = 0
    boundary: TtsChunk | None = None
    for chunk in chunks:
        cumulative += chunk.audio_ms
        if cumulative <= delivered_audio_ms:
            boundary = chunk
        else:
            break
    if boundary is not None and boundary.alignment_is_exact:
        return planned_text[: boundary.text_offset_end].rstrip(), True
    if total_audio_ms_generated <= 0:
        return "", False
    ratio = min(1.0, max(0.0, delivered_audio_ms / total_audio_ms_generated))
    words = planned_text.split()
    taken = round(ratio * len(words))
    return " ".join(words[:taken]).rstrip(), False


# ---------------------------------------------------------------------------------------------
# The active utterance the pipeline's `_barge_in` reaches
# ---------------------------------------------------------------------------------------------


class _ActiveCallerUtterance:
    """One caller utterance in flight — the `ActiveCallerUtterance` the pipeline registers.

    It is the sink's own inner object rather than a data class the pipeline owns, because steps 5
    and 6 of §6.1 need everything the sink knows: the chunk ledger the `delivered_text` arithmetic
    reads, the planned `fact_ids` that must *not* be revealed, the recorder the caller segment is
    built from and the transcript/turn rows of §6.4.
    """

    def __init__(
        self,
        sink: TtsSpeechSink,
        planned: PlannedCallerUtterance,
        context: TurnContext,
        *,
        stream: ChunkedTtsStream,
        request_id: str,
        provider: TTSProvider,
        voice: TtsVoiceSpec,
    ) -> None:
        self._sink = sink
        self._planned = planned
        self._context = context
        self._stream = stream
        self._request_id = request_id
        self._provider = provider
        self._voice = voice
        self._playback: PlaybackHandle | None = None
        self._chunks: list[TtsChunk] = []
        self._captured_ms = 0
        self._start_offset_ms: int | None = None
        self._interrupted = False
        self._settled = False
        #: A provider exception raised *inside* the frame iterator. `ChunkedPlayback` pulls that
        #: iterator from its own pump task, so an exception there would otherwise never reach the
        #: awaiting `speak()` — the playback would simply stop and the turn would hang on
        #: `wait_done()`. It is captured here and re-raised by the sink instead.
        self.failure: BaseException | None = None

    # -- what the pipeline sees ---------------------------------------------------------------

    @property
    def turn_id(self) -> uuid.UUID:
        """The turn this utterance answers."""
        return self._planned.turn_id

    @property
    def playback(self) -> PlaybackHandle | None:
        """The live `PlaybackHandle`, once `CallTransport.play` has returned one."""
        return self._playback

    @property
    def interrupted(self) -> bool:
        """True once a barge-in has claimed this utterance."""
        return self._interrupted

    def mark_interrupted(self) -> None:
        """Claim the utterance for the barge-in **before** anything is cancelled (§6.1).

        Synchronous and first, so that the `speak()` coroutine — which the same barge-in is about
        to cancel — can never win the race to emit `CALLER_TTS_ENDED` for an utterance that was
        cut off. That would reveal facts nobody heard (INV 12).
        """
        self._interrupted = True

    async def cancel_generation(self) -> None:
        """§6.1 step 2: stop the TTS stream after the unit in flight."""
        await self._stream.cancel()

    async def on_interrupted(
        self,
        *,
        interrupting_turn_id: uuid.UUID,
        delivered: DeliveredAudio | None,
        cutoff_latency_ms: int,
    ) -> None:
        """§6.1 steps 5–6 and §6.4's rows. Called by the pipeline, never by `speak()`."""
        if self._settled:
            return
        self._settled = True
        await self._sink.persist_interrupted(
            self,
            interrupting_turn_id=interrupting_turn_id,
            delivered=delivered,
            cutoff_latency_ms=cutoff_latency_ms,
        )

    # -- what the sink writes into it ---------------------------------------------------------

    def set_playback(self, playback: PlaybackHandle) -> None:
        """Remember the handle `_barge_in` step 4 cancels."""
        self._playback = playback

    def record_chunk(self, chunk: TtsChunk, *, offset_ms: int) -> None:
        """One more chunk handed to the transport — the ledger §6.3's arithmetic reads."""
        if self._start_offset_ms is None:
            self._start_offset_ms = offset_ms
        self._chunks.append(chunk)
        self._captured_ms += chunk.audio_ms

    @property
    def chunks(self) -> tuple[TtsChunk, ...]:
        """Every chunk handed to the transport, in order."""
        return tuple(self._chunks)

    @property
    def captured_ms(self) -> int:
        """Total audio handed to the transport, delivered or still queued."""
        return self._captured_ms

    @property
    def start_offset_ms(self) -> int | None:
        """Session offset of the first frame; `None` until one has been handed over."""
        return self._start_offset_ms

    @property
    def planned(self) -> PlannedCallerUtterance:
        """The utterance E13 decided."""
        return self._planned

    @property
    def context(self) -> TurnContext:
        """The turn context this utterance belongs to."""
        return self._context

    @property
    def request_id(self) -> str:
        """The TTS request id — `inference_metrics.request_id`."""
        return self._request_id

    @property
    def provider(self) -> TTSProvider:
        """The provider that actually synthesised (the fallback, after one)."""
        return self._provider

    def settle(self) -> bool:
        """Claim the natural end. Returns False when a barge-in already claimed it."""
        if self._settled or self._interrupted:
            return False
        self._settled = True
        return True


# ---------------------------------------------------------------------------------------------
# The sink
# ---------------------------------------------------------------------------------------------


class TtsSpeechSink:
    """`CallerSpeechSink` that speaks the planned utterance and records what was heard."""

    def __init__(
        self,
        *,
        provider: TTSProvider,
        metrics: MetricsRecorder,
        clock: Clock,
        config: VoiceTurnConfig,
        uow_factory: UnitOfWorkFactory,
        fallback_provider: TTSProvider | None = None,
        default_voice_id: str = "ru_female_1",
        default_speaking_rate: float = 1.0,
        timeout_ms: int = 8000,
        first_chunk_timeout_ms: int = 1500,
        max_unit_chars: int = DEFAULT_MAX_UNIT_CHARS,
    ) -> None:
        self._provider = provider
        self._fallback = fallback_provider
        self._metrics = metrics
        self._clock = clock
        self._config = config
        self._uow_factory = uow_factory
        self._default_voice_id = default_voice_id
        self._default_speaking_rate = default_speaking_rate
        self._timeout_ms = timeout_ms
        self._first_chunk_timeout_ms = first_chunk_timeout_ms
        self._max_unit_chars = max_unit_chars
        #: `session_id -> the scenario's caller voice`, read once per session (§10).
        self._voices: dict[SessionId, TtsVoiceSpec] = {}

    # -- the CallerSpeechSink port ------------------------------------------------------------

    async def speak(self, planned: PlannedCallerUtterance, context: TurnContext) -> None:
        """Synthesise, play, record and — on an uninterrupted end — reveal the facts."""
        base_voice = await self._voice_for(context.session_id)
        # `_voice_for` caches the scenario's voice per session (§10); the emotion is per-turn, so
        # it is layered on fresh for every `speak()` call rather than cached, and the same `voice`
        # (primary attempt and, on failure, the fallback attempt — MANAGER RULING on E14-B's gap
        # 1) carries `PlannedCallerUtterance.emotion` without any mutable provider-side state.
        voice = replace(base_voice, emotion=planned.emotion)
        attempt = await self._attempt(planned, context, self._provider, voice, retry=False)
        if attempt is not None:
            return
        if self._fallback is None:
            # `SIM_TTS_FALLBACK_PROVIDER=none`: there is no second attempt, so the first failure
            # is already INV 14's last row.
            await self._persist_silent(planned, context)
            return
        # INV 14: the whole utterance is retried once, on the configured fallback provider.
        await context.appender.append(
            [
                model_fallback_used_event(
                    offset_ms=context.appender.offset_ms(),
                    component=TTS_COMPONENT,
                    reason="TTS_PROVIDER_FAILED",
                    attempt=1,
                    fallback_kind=FALLBACK_KIND_PROVIDER,
                    turn_index=planned.turn_index,
                    turn_id=planned.turn_id,
                )
            ]
        )
        fallback = await self._attempt(planned, context, self._fallback, voice, retry=True)
        if fallback is None:
            await self._persist_silent(planned, context)

    # -- one synthesis attempt ----------------------------------------------------------------

    async def _attempt(
        self,
        planned: PlannedCallerUtterance,
        context: TurnContext,
        provider: TTSProvider,
        voice: TtsVoiceSpec,
        *,
        retry: bool,
    ) -> _ActiveCallerUtterance | None:
        """One provider's go at the whole utterance. `None` means it failed (INV 14)."""
        request_id = f"{planned.turn_id}:tts{':retry' if retry else ''}"
        stream = ChunkedTtsStream(
            provider,
            planned.text,
            voice,
            request_id=request_id,
            max_chunk_ms=self._config.tts_chunk_ms,
            max_unit_chars=self._max_unit_chars,
        )
        active = _ActiveCallerUtterance(
            self,
            planned,
            context,
            stream=stream,
            request_id=request_id,
            provider=provider,
            voice=voice,
        )
        register = context.set_active_utterance
        if register is not None:
            register(active)
        started_at = self._clock.now()
        started_ms = self._clock.monotonic_ms()
        first_output_at: datetime | None = None
        try:
            frames = self._frames(active, stream, provider, voice)
            playback = await context.transport.play(frames)
            active.set_playback(playback)
            delivered = await asyncio.wait_for(
                playback.wait_done(), timeout=self._timeout_ms / MS_PER_S
            )
            if active.failure is not None:
                raise active.failure
        except asyncio.CancelledError:
            # A barge-in, or a newer turn. §6.4 wants **one** cancelled metric per stage: when a
            # barge-in claimed this utterance the pipeline's `on_interrupted` already wrote it,
            # so only the "cancelled by a newer turn, nothing was interrupted" case records here.
            if not active.interrupted:
                await self._record(
                    active,
                    started_at=started_at,
                    started_ms=started_ms,
                    first_output_at=None,
                    status="CANCELLED",
                    error_kind="BARGE_IN",
                    retry=retry,
                )
            raise
        except (TimeoutError, TtsTimeoutError) as exc:
            await self._fail(
                active,
                started_at=started_at,
                started_ms=started_ms,
                status="TIMEOUT",
                error_code=ERROR_CODE_TIMEOUT,
                message=str(exc) or f"TTS exceeded {self._timeout_ms} ms",
                retry=retry,
            )
            return None
        except Exception as exc:
            await self._fail(
                active,
                started_at=started_at,
                started_ms=started_ms,
                status="ERROR",
                error_code=type(exc).__name__,
                message=str(exc),
                retry=retry,
            )
            return None

        if not active.settle():
            # A barge-in claimed the utterance while the last frames were draining: the pipeline
            # has already written §6.4's record, and an ending here would contradict it.
            return active
        if active.chunks:
            first_output_at = started_at
        await self._persist_completed(active, delivered)
        await self._record(
            active,
            started_at=started_at,
            started_ms=started_ms,
            first_output_at=first_output_at,
            status="OK",
            error_kind=None,
            retry=retry,
            output_audio_ms=delivered.total_audio_ms_generated,
        )
        await self._reveal_facts(active)
        return active

    # -- the frame stream handed to `CallTransport.play` --------------------------------------

    async def _frames(
        self,
        active: _ActiveCallerUtterance,
        stream: ChunkedTtsStream,
        provider: TTSProvider,
        voice: TtsVoiceSpec,
    ) -> AsyncIterator[AudioFrame]:
        """Chunks → session-stamped `AudioFrame`s, teed into the caller recording (§9.1).

        Two deviations from §9.1's letter, both documented in this task's report:

        * the tee happens **here**, one step before `ChunkedPlayback` captures the frame, because
          `CallTransport.play` takes an iterator and has no `on_frame` hook to pass one through
          (`ChunkedPlayback` itself does; the port above it does not). At most one generated-but-
          never-captured frame therefore reaches the WAV, and the `audio_segments` row is still
          truncated at `delivered_audio_ms`, so the *index* — what a reader is served — is exact;
        * `capture_offset_ms` is re-stamped session-relative. A provider counts from zero inside
          its own utterance, and `SessionRecorder.segment_for` derives `byte_offset` from the
          session timeline (D9); leaving the provider's offset would put every caller utterance
          of a call at byte 0.
        """
        resampler = (
            None
            if provider.output_sample_rate == self._config.sample_rate
            else Resampler(
                target_sample_rate=self._config.sample_rate,
                frame_samples=self._config.frame_samples,
            )
        )
        context = active.context
        elapsed_ms = 0
        base_offset_ms: int | None = None
        first = True
        iterator = stream.__aiter__()
        try:
            while True:
                # §8 row 8 budgets 200 ms to the first chunk; `tts_first_chunk_timeout_ms` is the
                # guard on it, and `tts_timeout_ms` bounds every later pull. A provider that
                # silently stalls is a `MODEL_ERROR{TIMEOUT}` turn, not a hung call.
                budget_ms = self._first_chunk_timeout_ms if first else self._timeout_ms
                try:
                    chunk = await asyncio.wait_for(
                        iterator.__anext__(), timeout=budget_ms / MS_PER_S
                    )
                except StopAsyncIteration:
                    break
                if base_offset_ms is None:
                    base_offset_ms = context.appender.offset_ms()
                produced = [chunk.frame] if resampler is None else resampler.process(chunk.frame)
                for raw in produced:
                    frame = replace(raw, capture_offset_ms=base_offset_ms + elapsed_ms)
                    elapsed_ms += frame.duration_ms
                    if context.recorder is not None:
                        with contextlib.suppress(RuntimeError):
                            context.recorder.tee("CALLER", frame)
                    active.record_chunk(chunk, offset_ms=frame.capture_offset_ms)
                    if first:
                        first = False
                        await self._announce_started(active, frame.capture_offset_ms)
                    yield frame
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # The iterator ends cleanly so `ChunkedPlayback` settles and `wait_done()` returns;
            # `_attempt` re-raises this into INV 14's failure ladder.
            active.failure = exc

    async def _announce_started(
        self, active: _ActiveCallerUtterance, first_audio_offset_ms: int
    ) -> None:
        """`CALLER_TTS_STARTED` + SPEC §27's `speech_end_to_first_audio_ms` (§3.7, §8)."""
        context = active.context
        planned = active.planned
        await context.appender.append(
            [
                caller_tts_started_event(
                    call_id=context.call_id,
                    turn_id=planned.turn_id,
                    turn_index=planned.turn_index,
                    offset_ms=context.appender.offset_ms(),
                    text=planned.text,
                    voice_id=(await self._voice_for(context.session_id)).voice_id,
                    provider=active.provider.provider_name,
                    model_version=active.provider.model_version,
                    first_audio_offset_ms=first_audio_offset_ms,
                )
            ]
        )
        speech_end_ms = context.speech_ended_offset_ms.get(planned.turn_id)
        if speech_end_ms is None:
            return
        with contextlib.suppress(Exception):
            await self._metrics.record_turn_latency(
                uuid.UUID(str(context.session_id)),
                planned.turn_id,
                max(0, first_audio_offset_ms - speech_end_ms),
            )

    # -- persistence ---------------------------------------------------------------------------

    async def _persist_completed(
        self, active: _ActiveCallerUtterance, delivered: DeliveredAudio
    ) -> None:
        """`CALLER_TTS_ENDED` + caller segment + transcript row + turn row, in ONE unit of work."""
        context = active.context
        planned = active.planned
        start_ms = active.start_offset_ms or context.appender.offset_ms()
        total_ms = delivered.total_audio_ms_generated
        segment = self._caller_segment(active, start_ms=start_ms, audio_ms=total_ms)
        transcript_id = uuid.uuid4()
        transcript = StoredTranscriptSegment(
            id=transcript_id,
            session_id=context.session_id,
            audio_segment_id=None if segment is None else segment.id,
            speaker="CALLER",
            start_ms=start_ms,
            end_ms=start_ms + total_ms,
            text=planned.text,
            is_final=True,
            confidence=None,
            # §9.1: the caller's words were generated, not recognised.
            asr_provider=None,
            asr_model=None,
            turn_index=planned.turn_index,
        )
        await context.appender.append(
            [
                caller_tts_ended_event(
                    call_id=context.call_id,
                    turn_id=planned.turn_id,
                    turn_index=planned.turn_index,
                    offset_ms=context.appender.offset_ms(),
                    at_offset_ms=start_ms + total_ms,
                    total_audio_ms=total_ms,
                    audio_segment_id=None if segment is None else segment.id,
                    delivered_text=planned.text,
                )
            ],
            segments=() if segment is None else [segment],
            transcript_segments=[transcript],
        )
        await self._set_caller_outcome(
            context,
            planned.turn_index,
            caller_transcript_segment_id=transcript_id,
            delivered_text=planned.text,
            interrupted=False,
        )

    async def persist_interrupted(
        self,
        active: _ActiveCallerUtterance,
        *,
        interrupting_turn_id: uuid.UUID,
        delivered: DeliveredAudio | None,
        cutoff_latency_ms: int,
    ) -> None:
        """§6.1 steps 5–6 and §6.4's table. Called by `TurnPipeline._barge_in`."""
        context = active.context
        planned = active.planned
        total_ms = (
            delivered.total_audio_ms_generated if delivered is not None else active.captured_ms
        )
        delivered_ms = delivered.delivered_audio_ms if delivered is not None else 0
        delivered_text, alignment_is_exact = delivered_text_for(
            planned.text,
            active.chunks,
            delivered_audio_ms=delivered_ms,
            total_audio_ms_generated=total_ms,
        )
        start_ms = active.start_offset_ms or context.appender.offset_ms()
        segment = self._caller_segment(active, start_ms=start_ms, audio_ms=delivered_ms)
        transcript_id = uuid.uuid4()
        transcript = StoredTranscriptSegment(
            id=transcript_id,
            session_id=context.session_id,
            audio_segment_id=None if segment is None else segment.id,
            speaker="CALLER",
            start_ms=start_ms,
            end_ms=start_ms + delivered_ms,
            # §6.4: the transcript is what was *heard*; `planned_text` lives in the event payload
            # and on the turn row, never here.
            text=delivered_text,
            is_final=True,
            confidence=None,
            asr_provider=None,
            asr_model=None,
            turn_index=planned.turn_index,
        )
        await context.appender.append(
            [
                caller_utterance_interrupted_event(
                    call_id=context.call_id,
                    turn_id=planned.turn_id,
                    turn_index=planned.turn_index,
                    offset_ms=context.appender.offset_ms(),
                    interrupting_turn_id=interrupting_turn_id,
                    planned_text=planned.text,
                    delivered_text=delivered_text,
                    delivered_audio_ms=delivered_ms,
                    total_audio_ms_generated=total_ms,
                    alignment_is_exact=alignment_is_exact,
                    # INV 12: **every** fact the utterance would have revealed, not the ones the
                    # delivered prefix happened to miss.
                    fact_ids_not_revealed=planned.fact_ids,
                    cutoff_latency_ms=cutoff_latency_ms,
                )
            ],
            segments=() if segment is None else [segment],
            transcript_segments=[transcript],
        )
        await self._set_caller_outcome(
            context,
            planned.turn_index,
            caller_transcript_segment_id=transcript_id,
            delivered_text=delivered_text,
            interrupted=True,
        )
        await self._record(
            active,
            started_at=self._clock.now(),
            started_ms=self._clock.monotonic_ms(),
            first_output_at=None,
            status="CANCELLED",
            error_kind="BARGE_IN",
            retry=False,
            output_audio_ms=delivered_ms,
        )
        await self._apply_interruption_trigger(context)

    async def _persist_silent(self, planned: PlannedCallerUtterance, context: TurnContext) -> None:
        """INV 14's last row: the turn ends silent but **complete** (no event, no facts).

        §20.6 has no "undelivered" flag on `transcript_segments`, so §6.4's permitted reading is
        the one the brief names: the transcript row still carries `text = planned_text` — losing
        the record of what the caller was going to say would be exactly the data loss SPEC §42
        item 14 forbids — and `dialogue_turns.delivered_text = ""` is what says nothing was heard.
        `planned_text` on the same row (E13's column) is what it would have been.
        """
        offset_ms = context.appender.offset_ms()
        transcript_id = uuid.uuid4()
        await context.appender.append(
            (),
            transcript_segments=[
                StoredTranscriptSegment(
                    id=transcript_id,
                    session_id=context.session_id,
                    audio_segment_id=None,
                    speaker="CALLER",
                    start_ms=offset_ms,
                    end_ms=offset_ms,
                    text=planned.text,
                    is_final=True,
                    confidence=None,
                    asr_provider=None,
                    asr_model=None,
                    turn_index=planned.turn_index,
                )
            ],
        )
        await self._set_caller_outcome(
            context,
            planned.turn_index,
            caller_transcript_segment_id=transcript_id,
            delivered_text="",
            interrupted=False,
        )

    def _caller_segment(
        self, active: _ActiveCallerUtterance, *, start_ms: int, audio_ms: int
    ) -> StoredAudioSegment | None:
        recorder = active.context.recorder
        if recorder is None or audio_ms <= 0:
            return None
        return recorder.segment_for("CALLER", start_ms=start_ms, end_ms=start_ms + audio_ms)

    async def _set_caller_outcome(
        self,
        context: TurnContext,
        turn_index: int,
        *,
        caller_transcript_segment_id: uuid.UUID,
        delivered_text: str,
        interrupted: bool,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.dialogue_turns.set_caller_outcome(
                context.session_id,
                turn_index,
                caller_transcript_segment_id=caller_transcript_segment_id,
                delivered_text=delivered_text,
                interrupted=interrupted,
            )
            await uow.commit()

    # -- facts and emotion ---------------------------------------------------------------------

    async def _reveal_facts(self, active: _ActiveCallerUtterance) -> None:
        """`FACTS_DELIVERED` + one `FactRevealedTrigger` per fact (D10, §10.5)."""
        planned = active.planned
        if not planned.fact_ids:
            return
        context = active.context
        at_offset_ms = context.appender.offset_ms()
        await context.appender.append(
            [
                facts_delivered_event(
                    turn_id=planned.turn_id,
                    turn_index=planned.turn_index,
                    offset_ms=at_offset_ms,
                    at_offset_ms=at_offset_ms,
                    fact_ids=planned.fact_ids,
                )
            ]
        )
        for fact_id in planned.fact_ids:
            with contextlib.suppress(Exception):
                await apply_dialogue_emotion_trigger(
                    self._uow_factory,
                    context.session_id,
                    FactRevealedTrigger(fact_id=fact_id),
                    clock=self._clock,
                    trigger_kind=TRIGGER_FACT_REVEALED,
                )

    async def _apply_interruption_trigger(self, context: TurnContext) -> None:
        """§10.5's `INTERRUPTION_COUNT`, folded from the log (E13's helper closes its TODO)."""
        count = await self._interruption_count(context.session_id)
        with contextlib.suppress(Exception):
            await apply_dialogue_emotion_trigger(
                self._uow_factory,
                context.session_id,
                InterruptionCountTrigger(at_least=count),
                clock=self._clock,
                trigger_kind=TRIGGER_INTERRUPTION_COUNT,
            )

    async def _interruption_count(self, session_id: SessionId) -> int:
        """How many `CALLER_UTTERANCE_INTERRUPTED` events this session has, including the one
        just appended — the trigger is "at least N", so it is folded, never counted in memory."""
        async with self._uow_factory() as uow:
            events = await uow.events.read(session_id)
        return sum(
            1 for event in events if event.event_type is EventType.CALLER_UTTERANCE_INTERRUPTED
        )

    # -- the voice ------------------------------------------------------------------------------

    async def _voice_for(self, session_id: SessionId) -> TtsVoiceSpec:
        """§10's voice binding: the scenario's `CallerProfile`, else the `SIM_TTS_*` defaults.

        Returns the cached, session-scoped voice with `emotion = None`; `speak()` layers the
        per-turn `PlannedCallerUtterance.emotion` on top with `dataclasses.replace` before this
        spec reaches a provider (see `speak()`).

        HLD gap: neither §2.4 nor §5.2 defines an emotion → `speaking_rate` mapping, so the rate
        is the persona's constant one. Inventing a curve here would be a product requirement this
        epic has no source for; it is listed in the report.
        """
        cached = self._voices.get(session_id)
        if cached is not None:
            return cached
        voice = TtsVoiceSpec(
            voice_id=self._default_voice_id,
            speaking_rate=self._default_speaking_rate,
        )
        try:
            async with self._uow_factory() as uow:
                session = await uow.sessions.get(session_id)
                document = (
                    None
                    if session is None
                    else await uow.scenarios.get_version_document(session.scenario_version_id)
                )
            if document is not None:
                profile = ScenarioVersion.model_validate(dict(document)).caller_profile
                voice = TtsVoiceSpec(
                    voice_id=profile.voice_id,
                    speaking_rate=profile.speaking_rate,
                    language=profile.language or "ru",
                )
        except Exception:
            logger.warning(
                "the caller voice for session %s could not be read; using the configured default",
                session_id,
            )
        self._voices[session_id] = voice
        return voice

    # -- failure and telemetry -------------------------------------------------------------------

    async def _fail(
        self,
        active: _ActiveCallerUtterance,
        *,
        started_at: datetime,
        started_ms: int,
        status: MetricStatus,
        error_code: str,
        message: str,
        retry: bool,
    ) -> None:
        """`MODEL_ERROR{stage: "TTS"}` + a metric, and nothing else changes (INV 14)."""
        context = active.context
        planned = active.planned
        logger.warning(
            "TTS failed for turn %s of session %s: %s",
            planned.turn_id,
            context.session_id,
            message,
        )
        await context.appender.append(
            [
                model_error_event(
                    offset_ms=context.appender.offset_ms(),
                    component=TTS_COMPONENT,
                    provider=active.provider.provider_name,
                    model=active.provider.model_version,
                    error_code=error_code,
                    message=message,
                    recoverable=True,
                    turn_index=planned.turn_index,
                    turn_id=planned.turn_id,
                    stage=TTS_COMPONENT,
                )
            ]
        )
        await self._record(
            active,
            started_at=started_at,
            started_ms=started_ms,
            first_output_at=None,
            status=status,
            error_kind=error_code,
            retry=retry,
        )

    async def _record(
        self,
        active: _ActiveCallerUtterance,
        *,
        started_at: datetime,
        started_ms: int,
        first_output_at: datetime | None,
        status: MetricStatus,
        error_kind: str | None,
        retry: bool,
        output_audio_ms: int | None = None,
    ) -> None:
        """One `InferenceMetric` per provider call, whatever the outcome (SPEC §27)."""
        context = active.context
        planned = active.planned
        latency_ms = max(0, self._clock.monotonic_ms() - started_ms)
        chunks = active.chunks
        ttft_ms = chunks[0].audio_ms if chunks else None
        audio_ms = output_audio_ms if output_audio_ms is not None else active.captured_ms
        metric = InferenceMetric(
            id=uuid.uuid4(),
            session_id=uuid.UUID(str(context.session_id)),
            turn_id=planned.turn_id,
            request_id=active.request_id,
            stage=InferenceStage.TTS,
            provider=active.provider.provider_name,
            model_version=active.provider.model_version,
            input_tokens=None,
            input_audio_ms=None,
            output_tokens=None,
            output_audio_ms=audio_ms,
            started_at=started_at,
            first_output_at=first_output_at,
            finished_at=self._clock.now(),
            ttft_ms=ttft_ms,
            total_latency_ms=latency_ms,
            tokens_per_second=None,
            # §7.3's `rtf`: how long synthesis took per millisecond of audio produced.
            realtime_factor=(latency_ms / audio_ms) if audio_ms else None,
            gpu_memory_used_mb=None,
            fallback_count=1 if retry else 0,
            retry_count=1 if retry else 0,
            status=status,
            error_kind=error_kind,
        )
        try:
            await self._metrics.record(metric)
        except Exception:
            # §2.6: a metrics failure is logged and swallowed; it never fails a turn.
            logger.exception("recording the TTS metric for turn %s failed", planned.turn_id)
