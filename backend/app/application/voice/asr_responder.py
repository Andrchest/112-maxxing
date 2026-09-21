"""`AsrTurnResponder` — the ASR stage of the turn pipeline (§3.7, §4.5, §9.1, SPEC §17, §19, §27).

The first real `TurnResponder`. It does exactly one thing with the trainee's finalized audio —
transcribe it, persist the transcript and announce it — and then hands the turn to `next_stage`,
which is where E13 plugs the interpreter → gate → generator → validator chain in. It owns no
dialogue of its own, and that is deliberate: the pipeline's responder seam is a chain, not a
god-object, so the epic that adds a stage adds a class rather than editing this one.

**What it writes, and in how many transactions.** One. The `transcript_segments` row, the
`dialogue_turns` upsert and the `ASR_FINAL` append commit together (§9.1's ordering guarantee),
so `ASR_FINAL.transcript_segment_id` and `.audio_segment_id` are references that always resolve
and a failure on any of the three leaves none of them. The metric is the one thing *outside* that
transaction — `MetricsRecorder` opens its own (§2.6), because telemetry must never be able to
fail a turn.

**What it never does (SPEC §2, §42 item 4, INV 4).** It does not touch the incident card, does
not select a service and does not move a workflow state. In particular it does not fire
`begin_interview`: the first `ASR_FINAL` moves the operator stage CONNECTED → INTERVIEW through
the *existing* simulation-runner hook and the `first_finalized_turn` guard fact
(`app.application.sessions.guard_context`), which reads the appended event. Appending a fact and
deciding a state are two jobs, and this class only has the first one (D5, D7).

**When the model fails (SPEC §42 item 14, INV 14).** An exception, a timeout or a cancellation
never erases simulation data. The turn ends quietly with a `MODEL_ERROR` event and a metric whose
status says which; the session state, the card, the events already appended and the
`audio_segments` row of this very turn all stay exactly as they were, and `next_stage` is not
called. `asyncio.CancelledError` — which is how the pipeline signals a barge-in — is recorded as
`CANCELLED` and then re-raised, because a cancelled response must actually stop.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from app.application.ports.asr import ASRProvider, AsrResult
from app.application.ports.clock import Clock
from app.application.ports.dialogue_turn_repository import DialogueTurnUpsert
from app.application.ports.metrics_recorder import (
    InferenceMetric,
    InferenceStage,
    MetricsRecorder,
    MetricStatus,
)
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.voice.config import BYTES_PER_SAMPLE, MS_PER_S, VoiceTurnConfig
from app.application.voice.events import asr_final_event, model_error_event
from app.application.voice.turn_detector import DetectedTurn
from app.application.voice.turn_pipeline import (
    TranscribedTurn,
    TranscribedTurnResponder,
    TurnContext,
)
from app.domain.common.ids import RoleStageId, SessionId

__all__ = [
    "AsrTurnResponder",
    "SessionStageResolver",
    "UnitOfWorkSessionStageResolver",
    "audio_duration_ms",
]

logger = logging.getLogger(__name__)

#: `MODEL_ERROR.component` for this stage — §10.13's value, and `inference_metrics.component`'s.
ASR_COMPONENT = "ASR"
#: `MODEL_ERROR.error_code` when the provider exceeded `asr_timeout_ms`.
ERROR_CODE_TIMEOUT = "TIMEOUT"

SessionStageResolver = Callable[[SessionId], Awaitable[RoleStageId | None]]
"""Which `role_stages` row a turn belongs to — `dialogue_turns.role_stage_id` is `NOT NULL`."""


def audio_duration_ms(audio: bytes, sample_rate: int) -> int:
    """Milliseconds of mono s16le `audio` at `sample_rate`."""
    if sample_rate <= 0:  # pragma: no cover - `VoiceTurnConfig` bounds the rate
        return 0
    return (len(audio) * MS_PER_S) // (sample_rate * BYTES_PER_SAMPLE)


class UnitOfWorkSessionStageResolver:
    """Reads the session's current stage once per session and remembers it.

    `dialogue_turns.role_stage_id` is `NOT NULL` (§20.6) and the turn itself does not carry one:
    the detector knows about audio, not about role stages. The stage is read from the session
    aggregate — the same place `10-domain-model.md` §10.8 reads it — and cached for the life of
    the call, because a call belongs to one stage by construction: the operator stage ends when
    the handoff is made, and a new stage means a new call.
    """

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory
        self._cache: dict[SessionId, RoleStageId] = {}

    async def __call__(self, session_id: SessionId) -> RoleStageId | None:
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached
        async with self._uow_factory() as uow:
            session = await uow.sessions.get(session_id)
        if session is None:
            return None
        stage = session.current_stage or session.active_stage
        if stage is None:
            return None
        self._cache[session_id] = stage.role_stage_id
        return stage.role_stage_id


class AsrTurnResponder:
    """`TurnResponder` that transcribes the turn and appends `ASR_FINAL` (§3.7, §4.5)."""

    def __init__(
        self,
        *,
        asr: ASRProvider,
        metrics: MetricsRecorder,
        clock: Clock,
        config: VoiceTurnConfig,
        stage_resolver: SessionStageResolver,
        timeout_ms: int,
        next_stage: TranscribedTurnResponder | None = None,
    ) -> None:
        self._asr = asr
        self._metrics = metrics
        self._clock = clock
        self._config = config
        self._stage_resolver = stage_resolver
        self._timeout_ms = timeout_ms
        # E13's `DialogueResponder` (interpreter → Fact Access Gate → generator → validator) is
        # what goes here; with `None` the turn stops after `ASR_FINAL`. SPEC §16 fixes the stage
        # order, and a responder that invented a caller answer would be exactly the "LLM is the
        # simulation" failure SPEC §2 forbids.
        # TODO(E14): the TTS stage sits behind E13's, through `CallerSpeechSink`.
        self._next_stage = next_stage

    @property
    def next_stage(self) -> TranscribedTurnResponder | None:
        """The stage this responder hands a non-empty final, transcribed turn to, if any (R1)."""
        return self._next_stage

    async def respond(self, turn: DetectedTurn, context: TurnContext) -> None:
        """Transcribe `turn`, persist it, announce it, and hand it on (§3.7)."""
        self._register_turn(turn)
        duration_ms = audio_duration_ms(turn.audio, self._config.sample_rate)
        request_id = str(turn.turn_id)
        started_at = self._clock.now()
        started_ms = self._clock.monotonic_ms()
        try:
            result = await asyncio.wait_for(
                self._asr.transcribe(turn.audio, self._config.sample_rate, request_id=request_id),
                timeout=self._timeout_ms / MS_PER_S,
            )
        except asyncio.CancelledError:
            # A newer turn arrived: the trainee is talking again (§3.7). Record it and stop.
            await self._record(
                context,
                turn,
                request_id=request_id,
                started_at=started_at,
                started_ms=started_ms,
                duration_ms=duration_ms,
                status="CANCELLED",
                error_kind="BARGE_IN",
            )
            raise
        except TimeoutError:
            await self._fail(
                context,
                turn,
                request_id=request_id,
                started_at=started_at,
                started_ms=started_ms,
                duration_ms=duration_ms,
                status="TIMEOUT",
                error_code=ERROR_CODE_TIMEOUT,
                message=f"ASR exceeded {self._timeout_ms} ms",
                recoverable=True,
            )
            return
        except Exception as exc:
            await self._fail(
                context,
                turn,
                request_id=request_id,
                started_at=started_at,
                started_ms=started_ms,
                duration_ms=duration_ms,
                status="ERROR",
                error_code=type(exc).__name__,
                message=str(exc),
                recoverable=True,
            )
            return

        transcribed = await self._persist(turn, context, result)
        await self._record(
            context,
            turn,
            request_id=request_id,
            started_at=started_at,
            started_ms=started_ms,
            duration_ms=duration_ms,
            status="OK",
            error_kind=None,
        )
        if not result.text.strip():
            # §4.5: silence is still a turn — the event and the row are written — but there is
            # nothing for the caller to answer, so the chain stops here.
            return
        next_stage = self._next_stage
        if next_stage is not None:
            await next_stage.respond_transcribed(transcribed, context)

    # -- the one transaction ------------------------------------------------------------------

    async def _persist(
        self, turn: DetectedTurn, context: TurnContext, result: AsrResult
    ) -> TranscribedTurn:
        """Transcript row + `dialogue_turns` upsert + `ASR_FINAL`, in one Unit of Work (§9.1).

        Returns the `TranscribedTurn` the next stage is handed (R1): the same text, confidence,
        turn index, role stage and transcript id this transaction just committed, so the dialogue
        chain and the audit record can never disagree about what was said.
        """
        transcript_segment_id = uuid.uuid4()
        audio_segment_id = context.audio_segment_ids.get(turn.turn_id)
        segment = StoredTranscriptSegment(
            id=transcript_segment_id,
            session_id=context.session_id,
            audio_segment_id=audio_segment_id,
            speaker="TRAINEE",
            start_ms=turn.start_ms,
            end_ms=turn.end_ms,
            text=result.text,
            is_final=True,
            confidence=result.confidence,
            asr_provider=self._asr.provider_name,
            asr_model=self._asr.model_version,
            turn_index=turn.turn_index,
        )
        turns: list[DialogueTurnUpsert] = []
        role_stage_id = await self._stage_resolver(context.session_id)
        if role_stage_id is None:
            # §20.6 makes `role_stage_id` NOT NULL, so there is no honest row to write. The
            # transcript and the event still are: the turn record is a read model for the report
            # (D5), never the audit source, so losing it costs a rendering, not a fact.
            logger.warning(
                "session %s has no role stage; the dialogue_turns row for turn %d is skipped",
                context.session_id,
                turn.turn_index,
            )
        else:
            turns.append(
                DialogueTurnUpsert(
                    id=uuid.uuid4(),
                    session_id=context.session_id,
                    role_stage_id=role_stage_id,
                    turn_index=turn.turn_index,
                    user_speech_started_offset_ms=turn.start_ms,
                    user_speech_ended_offset_ms=turn.end_ms,
                    operator_transcript_segment_id=transcript_segment_id,
                    correlation_id=turn.turn_id,
                )
                # E13 fills `interpretation`, `gate_output`, `planned_text` and `fallback_used`
                # through `DialogueTurnRepository.set_dialogue_outcome` once the chain has run.
                # TODO(E14): `caller_transcript_segment_id`, `delivered_text`,
                # `interrupted` and `speech_end_to_first_audio_ms`.
            )
        await context.appender.append(
            [
                asr_final_event(
                    call_id=context.call_id,
                    turn_id=turn.turn_id,
                    turn_index=turn.turn_index,
                    offset_ms=context.appender.offset_ms(),
                    transcript_segment_id=transcript_segment_id,
                    audio_segment_id=audio_segment_id,
                    text=result.text,
                    start_ms=turn.start_ms,
                    end_ms=turn.end_ms,
                    confidence=result.confidence,
                    asr_provider=self._asr.provider_name,
                    asr_model=self._asr.model_version,
                )
            ],
            transcript_segments=[segment],
            dialogue_turns=turns,
        )
        return TranscribedTurn(
            turn=turn,
            text=result.text,
            confidence=result.confidence,
            turn_index=turn.turn_index,
            role_stage_id=role_stage_id,
            transcript_segment_id=transcript_segment_id,
        )

    # -- the failure path ---------------------------------------------------------------------

    async def _fail(
        self,
        context: TurnContext,
        turn: DetectedTurn,
        *,
        request_id: str,
        started_at: datetime,
        started_ms: int,
        duration_ms: int,
        status: MetricStatus,
        error_code: str,
        message: str,
        recoverable: bool,
    ) -> None:
        """`MODEL_ERROR` + a metric, and nothing else changes (SPEC §42 item 14)."""
        logger.warning(
            "ASR failed for turn %s of session %s: %s", turn.turn_id, context.session_id, message
        )
        await context.appender.append(
            [
                model_error_event(
                    offset_ms=context.appender.offset_ms(),
                    component=ASR_COMPONENT,
                    provider=self._asr.provider_name,
                    model=self._asr.model_version,
                    error_code=error_code,
                    message=message,
                    recoverable=recoverable,
                    turn_index=turn.turn_index,
                    turn_id=turn.turn_id,
                )
            ]
        )
        await self._record(
            context,
            turn,
            request_id=request_id,
            started_at=started_at,
            started_ms=started_ms,
            duration_ms=duration_ms,
            status=status,
            error_kind=error_code,
        )

    # -- telemetry ----------------------------------------------------------------------------

    def _register_turn(self, turn: DetectedTurn) -> None:
        """Tell a recorder that keys rows by `turn_index` which index this turn's uuid is.

        The port carries `turn_id` and the `inference_metrics` column is `turn_index` (E11-A's
        HLD gap 4); `PgMetricsRecorder` bridges the two through `register_turn`, and a recorder
        that does not need the pairing simply does not offer the method.
        """
        register = getattr(self._metrics, "register_turn", None)
        if callable(register):
            register(turn.turn_id, turn.turn_index)

    async def _record(
        self,
        context: TurnContext,
        turn: DetectedTurn,
        *,
        request_id: str,
        started_at: datetime,
        started_ms: int,
        duration_ms: int,
        status: MetricStatus,
        error_kind: str | None,
    ) -> None:
        """One `InferenceMetric` per call, whatever the outcome (SPEC §27)."""
        finished_at = self._clock.now()
        latency_ms = max(0, self._clock.monotonic_ms() - started_ms)
        metric = InferenceMetric(
            id=uuid.uuid4(),
            session_id=uuid.UUID(str(context.session_id)),
            turn_id=turn.turn_id,
            request_id=request_id,
            stage=InferenceStage.ASR,
            provider=self._asr.provider_name,
            model_version=self._asr.model_version,
            input_tokens=None,
            input_audio_ms=duration_ms,
            output_tokens=None,
            output_audio_ms=None,
            started_at=started_at,
            first_output_at=None,
            finished_at=finished_at,
            ttft_ms=None,
            total_latency_ms=latency_ms,
            tokens_per_second=None,
            realtime_factor=(latency_ms / duration_ms) if duration_ms > 0 else None,
            gpu_memory_used_mb=None,
            fallback_count=0,
            retry_count=0,
            status=status,
            error_kind=error_kind,
        )
        try:
            await self._metrics.record(metric)
        except Exception:
            # §2.6: a metrics failure is logged and swallowed; it never fails a turn.
            logger.exception("recording the ASR metric for turn %s failed", turn.turn_id)
