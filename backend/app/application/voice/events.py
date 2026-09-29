"""The one place that turns a pipeline fact into a `SessionEvent` (§3.7, D5, D9, SPEC §8).

Every voice event the E11 slice produces is built here and appended through a `UnitOfWork`, for
two reasons the HLD is explicit about:

* **`seq_no` allocation stays under the D5 row lock.** The voice agent is a separate *process*
  that reuses `app.application` in-process (D9); it appends through the same `EventStore` and the
  same `SELECT … FOR UPDATE` on `simulation_sessions.next_seq_no` as the backend, never via REST
  and never around the event store. Two processes appending to one session is exactly the case
  §20.8 was written for.
* **The payloads are the catalog's.** `validate_payload` runs on every payload before it is
  appended, so a key the §10.13 catalog requires can never be quietly missing; where the voice
  path needs a fact the catalog does not list — `turn_id`, `end_reason`, `discarded_short`,
  `was_during_playback` — it is added *beside* the catalogued keys, never instead of one.

The `turn_id` / `turn_index` duality is an HLD gap, resolved here in favour of carrying both:
`10-domain-model.md` §10.13 catalogues `turn_index` (an int, which is what the report timeline and
`dialogue_turns.turn_index` join on) while `50-voice-pipeline.md` §3.2 specifies `turn_id` (a uuid,
which is what correlates an event with an in-flight response across processes). Dropping either
would break a documented consumer. See this task's report under "HLD gaps".

This module emits the boundary signals, the transport transitions, the end of the call and — from
E12 — the ASR events and `MODEL_ERROR`. The dialogue-chain payloads (`DIALOGUE_INTERPRETED`,
`FACT_GATE_EVALUATED`, `CALLER_RESPONSE_PLANNED`, `CALLER_RESPONSE_GENERATED`) live beside the
stage that produces them, in `app.application.dialogue.events` (E13-B2). E14 adds the playback
side — `CALLER_TTS_STARTED`, `CALLER_TTS_ENDED`, `CALLER_UTTERANCE_INTERRUPTED`,
`FACTS_DELIVERED` and the TTS `MODEL_FALLBACK_USED` — here rather than beside the sink, because
they are pipeline facts (what reached the wire), not dialogue decisions.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.call_transport import TransportEvent, TransportEventType
from app.application.ports.clock import Clock
from app.application.ports.dialogue_turn_repository import DialogueTurnUpsert
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.simulation.sim_time import running_ms
from app.application.timebase import session_offset_ms
from app.application.voice.turn_detector import DetectedTurn, SpeechStarted
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId, UserId
from app.domain.enums import ActorType
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.session.session import SimulationSession

__all__ = [
    "VoiceEventAppender",
    "asr_final_event",
    "asr_partial_event",
    "call_ended_event",
    "caller_tts_ended_event",
    "caller_tts_started_event",
    "caller_utterance_interrupted_event",
    "facts_delivered_event",
    "model_error_event",
    "model_fallback_used_event",
    "transport_event_to_domain_event",
    "user_speech_ended_event",
    "user_speech_started_event",
]

_TRAINEE = ActorRef(actor_type=ActorType.TRAINEE)
_MODEL = ActorRef(actor_type=ActorType.MODEL)
_SYSTEM = ActorRef(actor_type=ActorType.SYSTEM)
_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)

#: Which `TransportEventType`s become a catalogued `SessionEvent`. The rest — `CONNECTED`,
#: `PARTICIPANT_JOINED`, `TRACK_SUBSCRIBED` … — are media-plane bookkeeping with no catalog row
#: and no consumer; they drive the pipeline's own state and are logged, not persisted (§3.7).
_TRANSPORT_EVENT_TYPES: Mapping[TransportEventType, EventType] = {
    TransportEventType.DISCONNECTED: EventType.TRANSPORT_DISCONNECTED,
    TransportEventType.RECONNECTED: EventType.TRANSPORT_RECONNECTED,
}

_UNKNOWN_PARTICIPANT = "unknown"
_DEFAULT_DISCONNECT_REASON = "TRANSPORT_DISCONNECTED"


def _event(
    event_type: EventType,
    actor: ActorRef,
    offset_ms: int,
    payload: Mapping[str, Any],
    correlation_id: uuid.UUID | None = None,
) -> DomainEvent:
    """Validate the payload against the §10.13 catalog, then build the event."""
    validate_payload(event_type, payload)
    return DomainEvent(
        event_type=event_type,
        actor=actor,
        monotonic_offset_ms=offset_ms,
        correlation_id=correlation_id,
        payload=dict(payload),
    )


def user_speech_started_event(
    started: SpeechStarted,
    *,
    call_id: uuid.UUID,
    offset_ms: int,
    vad_provider: str,
) -> DomainEvent:
    """`USER_SPEECH_STARTED` at the IDLE/PRE_SPEECH → IN_SPEECH transition (§3.2)."""
    return _event(
        EventType.USER_SPEECH_STARTED,
        _TRAINEE,
        offset_ms,
        {
            "call_id": call_id,
            "turn_index": started.turn_index,
            "at_offset_ms": started.start_ms,
            "vad_provider": vad_provider,
            # Beside the catalogued keys (§3.2): the uuid that correlates this turn across
            # processes, and the barge-in flag SPEC §18 step 1 is decided by.
            "turn_id": str(started.turn_id),
            "was_during_playback": started.was_during_playback,
        },
        correlation_id=started.turn_id,
    )


def user_speech_ended_event(
    turn: DetectedTurn,
    *,
    call_id: uuid.UUID,
    offset_ms: int,
    endpoint_silence_ms: int,
) -> DomainEvent:
    """`USER_SPEECH_ENDED`, including a discarded sub-`min_turn_ms` turn (§4.4).

    A turn below `min_turn_ms` is discarded — no ASR, no response — but **both** boundary events
    are still logged, with `discarded_short: true`, because a trainee's cough is part of the
    audit record even when it is not part of the dialogue.
    """
    return _event(
        EventType.USER_SPEECH_ENDED,
        _TRAINEE,
        offset_ms,
        {
            "call_id": call_id,
            "turn_index": turn.turn_index,
            "at_offset_ms": turn.end_ms,
            "speech_duration_ms": turn.duration_ms,
            "endpoint_silence_ms": endpoint_silence_ms,
            "turn_id": str(turn.turn_id),
            "end_reason": turn.end_reason.value,
            "discarded_short": turn.discarded_short,
            "is_barge_in": turn.is_barge_in,
        },
        correlation_id=turn.turn_id,
    )


def asr_partial_event(
    *,
    call_id: uuid.UUID,
    turn_id: uuid.UUID,
    turn_index: int,
    offset_ms: int,
    text: str,
    start_ms: int,
    end_ms: int,
    asr_provider: str,
    asr_model: str,
    stability: float | None = None,
) -> DomainEvent:
    """`ASR_PARTIAL` — an incremental hypothesis, and nothing more (§4.5, SPEC §17).

    A partial is an **event only**. It never becomes a `transcript_segments` row, never reaches
    the interpreter, never touches the incident card (SPEC §9, §42 item 4) and never counts
    toward the turn's latency: SPEC §17 says the response begins from the finalized turn. Whether
    it is produced at all is `VoiceTurnConfig.partial_asr_enabled`; whether the trainee is shown
    it is `SessionPolicy.show_asr_partials`, enforced by `app.application.realtime.redaction`.

    `stability` is §4.5's field and has no §10.13 catalog key, so it rides beside the catalogued
    ones like `turn_id` does.
    """
    return _event(
        EventType.ASR_PARTIAL,
        _MODEL,
        offset_ms,
        {
            "call_id": call_id,
            "turn_index": turn_index,
            "text": text,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "asr_provider": asr_provider,
            "asr_model": asr_model,
            "turn_id": str(turn_id),
            "stability": stability,
        },
        correlation_id=turn_id,
    )


def asr_final_event(
    *,
    call_id: uuid.UUID,
    turn_id: uuid.UUID,
    turn_index: int,
    offset_ms: int,
    transcript_segment_id: uuid.UUID,
    audio_segment_id: uuid.UUID | None,
    text: str,
    start_ms: int,
    end_ms: int,
    confidence: float | None,
    asr_provider: str,
    asr_model: str,
) -> DomainEvent:
    """`ASR_FINAL` — once per surviving turn (§4.5).

    This is the event the `begin_interview` guard watches (`10-domain-model.md` §10.8): the first
    one moves the operator stage CONNECTED → INTERVIEW. It does so through the simulation runner's
    existing `after_tick` hook and `build_guard_runtime`, never by this module firing a trigger —
    appending an event and deciding a state are two different jobs (D5, D7).
    """
    return _event(
        EventType.ASR_FINAL,
        _MODEL,
        offset_ms,
        {
            "call_id": call_id,
            "turn_index": turn_index,
            "transcript_segment_id": str(transcript_segment_id),
            "audio_segment_id": None if audio_segment_id is None else str(audio_segment_id),
            "text": text,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "confidence": confidence,
            "asr_provider": asr_provider,
            "asr_model": asr_model,
            "turn_id": str(turn_id),
        },
        correlation_id=turn_id,
    )


def model_error_event(
    *,
    offset_ms: int,
    component: str,
    provider: str,
    model: str,
    error_code: str,
    message: str,
    recoverable: bool,
    turn_index: int | None,
    turn_id: uuid.UUID | None = None,
    stage: str | None = None,
) -> DomainEvent:
    """`MODEL_ERROR` — a model call failed and the turn ends quietly (SPEC §42 item 14).

    The payload is §10.13's row. What matters as much as the keys is what this event does *not*
    do: it changes no session state, rolls back no card, discards no earlier event and deletes no
    `audio_segments` row. `60-inference-ops.md` puts it plainly — a failing model "never calls a
    session use case, aborts a session, rolls back an incident or clears a card".
    """
    return _event(
        EventType.MODEL_ERROR,
        _SYSTEM,
        offset_ms,
        {
            "component": component,
            "provider": provider,
            "model": model,
            "error_code": error_code,
            "message": message,
            "recoverable": recoverable,
            "turn_index": turn_index,
            # E18-C: `60-inference-ops.md` §4.4 spells the same field `error_kind`
            # (`MODEL_ERROR {..., error_kind: "OOM", recoverable: false}`) while §10.13's
            # catalogued key is `error_code`. Both are carried, the catalogued one authoritative —
            # the same resolution this module already made for `component` vs `stage`, so a reader
            # of either document finds the key it was promised. See "HLD gaps" in E18-C's report.
            "error_kind": error_code,
            "turn_id": None if turn_id is None else str(turn_id),
            # E14: `50-voice-pipeline.md` §6/§19 name the failing step a *stage*, while §10.13's
            # catalogued key is `component`. Both are carried, the catalogued one authoritative —
            # the same resolution E13 made for `MODEL_FALLBACK_USED.component` vs `stage`.
            "stage": stage if stage is not None else component,
        },
        correlation_id=turn_id,
    )


def transport_event_to_domain_event(
    event: TransportEvent, *, offset_ms: int, downtime_ms: int = 0
) -> DomainEvent | None:
    """`TRANSPORT_DISCONNECTED` / `TRANSPORT_RECONNECTED`, or `None` for an unpersisted type."""
    event_type = _TRANSPORT_EVENT_TYPES.get(event.type)
    if event_type is None:
        return None
    identity = event.participant_identity or _UNKNOWN_PARTICIPANT
    if event_type is EventType.TRANSPORT_DISCONNECTED:
        payload: dict[str, Any] = {
            "call_id": event.call_id,
            "participant_identity": identity,
            "reason": event.detail or _DEFAULT_DISCONNECT_REASON,
            "at_offset_ms": event.at_offset_ms,
        }
    else:
        payload = {
            "call_id": event.call_id,
            "participant_identity": identity,
            "downtime_ms": downtime_ms,
            "at_offset_ms": event.at_offset_ms,
        }
    return _event(event_type, _SYSTEM, offset_ms, payload)


def call_ended_event(
    *,
    call_id: uuid.UUID,
    offset_ms: int,
    at_offset_ms: int,
    duration_ms: int,
    reason: str,
    ended_by: ActorType = ActorType.SIMULATION,
) -> DomainEvent:
    """`CALL_ENDED` when the transport closes (§3.7).

    The actor is `SIMULATION`, not `TRAINEE`: the trainee's own hang-up goes through
    `app.application.operator.end_call` and is already logged there. This is the media plane
    going away underneath a call nobody ended on purpose.
    """
    return _event(
        EventType.CALL_ENDED,
        _SIMULATION if ended_by is ActorType.SIMULATION else _TRAINEE,
        offset_ms,
        {
            "call_id": call_id,
            "at_offset_ms": at_offset_ms,
            "duration_ms": duration_ms,
            "ended_by": ended_by.value,
            "reason": reason,
        },
    )


# ---------------------------------------------------------------------------------------------
# E14: the playback side (§3.7, §6, §9.1, SPEC §18, §19, §25, §26; D9, D10)
# ---------------------------------------------------------------------------------------------
#
# Every payload carries §10.13's catalogued keys; the extra keys `50-voice-pipeline.md` §6.3 and
# this epic's brief name ride *beside* them, the convention `turn_id` established above.


def caller_tts_started_event(
    *,
    call_id: uuid.UUID,
    turn_id: uuid.UUID,
    turn_index: int,
    offset_ms: int,
    text: str,
    voice_id: str,
    provider: str,
    model_version: str,
    first_audio_offset_ms: int,
    voice_id_native: str | None = None,
    style_version: int | None = None,
    seed: int | None = None,
    tempo: float | None = None,
    retried: bool | None = None,
) -> DomainEvent:
    """`CALLER_TTS_STARTED` — the **first** frame has been handed to the transport (§3.7).

    Not "synthesis was requested": SPEC §18's stage order and §27's
    `speech_end_to_first_audio_ms` are both about audio that actually left, so this event is
    emitted from the playback tee and never from the `stream()` call site. `text_sent_to_tts` is
    §10.13's key and SPEC §25's requirement — the *exact* text handed to the provider.

    ADDITIVE `voice_id_native` (E20-G/G6, HLD 10 §10.13): `voice_id` is the SCENARIO-LOGICAL id
    the scenario cast (`ru_female_adult_01`); `voice_id_native` is what the selected provider was
    actually asked to speak with after the active model profile's `tts.voice_map` resolved it
    (`Serena`). Both are recorded because an audit that only has the logical id cannot tell which
    voice was heard, and one that only has the native id cannot tell what the scenario asked for.
    It is a CALLER detail and is dropped for trainees exactly like `planned_text`
    (`app.application.realtime.redaction`, HLD 40 §40.4 row 12 — that row already whitelists only
    `{call_id, turn_index, at_offset_ms}`, so the key never reaches a trainee socket). `None`
    when the provider does not resolve voices (`FakeTTS`) — the key is then absent.

    ADDITIVE, optional (I8 V1): what the provider reports it actually generated for the FIRST unit
    of the utterance (the one this event announces) — `style_version` (the instruct table's
    `STYLE_VERSION`), `seed` (the seed that won; absent when unseeded), `tempo` (the factor
    applied, 1.0 = none) and `retried` (the worker's rate check regenerated it once). Only
    `Qwen3TTS` reports them; each key is absent when `None`. Redacted for trainees like
    `voice_id_native` (not in §40.4 row 12's whitelist).
    """
    synthesis = {
        key: value
        for key, value in (
            ("style_version", style_version),
            ("seed", seed),
            ("tempo", tempo),
            ("retried", retried),
        )
        if value is not None
    }
    return _event(
        EventType.CALLER_TTS_STARTED,
        _SIMULATION,
        offset_ms,
        {
            "call_id": call_id,
            "turn_index": turn_index,
            "text_sent_to_tts": text,
            "tts_provider": provider,
            "tts_model": model_version,
            "voice_id": voice_id,
            "at_offset_ms": first_audio_offset_ms,
            # Beside the catalogued keys:
            "turn_id": str(turn_id),
            "text": text,
            "provider": provider,
            "model_version": model_version,
            "first_audio_offset_ms": first_audio_offset_ms,
            **({"voice_id_native": voice_id_native} if voice_id_native is not None else {}),
            **synthesis,
        },
        correlation_id=turn_id,
    )


def caller_tts_ended_event(
    *,
    call_id: uuid.UUID,
    turn_id: uuid.UUID,
    turn_index: int,
    offset_ms: int,
    at_offset_ms: int,
    total_audio_ms: int,
    audio_segment_id: uuid.UUID | None,
    delivered_text: str,
) -> DomainEvent:
    """`CALLER_TTS_ENDED` — the playback drained naturally (§6.4).

    **An interrupted utterance never produces one** (§6.4, D10): `completed` is therefore always
    `True` here, and the absence of the event is what makes "the facts were not revealed" a
    structural property of the log rather than a flag a reader has to trust.
    """
    return _event(
        EventType.CALLER_TTS_ENDED,
        _SIMULATION,
        offset_ms,
        {
            "call_id": call_id,
            "turn_index": turn_index,
            "at_offset_ms": at_offset_ms,
            "total_audio_ms": total_audio_ms,
            "completed": True,
            "audio_segment_id": None if audio_segment_id is None else str(audio_segment_id),
            # Beside the catalogued keys:
            "turn_id": str(turn_id),
            "delivered_text": delivered_text,
        },
        correlation_id=turn_id,
    )


def caller_utterance_interrupted_event(
    *,
    call_id: uuid.UUID,
    turn_id: uuid.UUID,
    turn_index: int,
    offset_ms: int,
    interrupting_turn_id: uuid.UUID,
    planned_text: str,
    delivered_text: str,
    delivered_audio_ms: int,
    total_audio_ms_generated: int,
    alignment_is_exact: bool,
    fact_ids_not_revealed: Sequence[str],
    cutoff_latency_ms: int,
) -> DomainEvent:
    """`CALLER_UTTERANCE_INTERRUPTED` — §6.3's payload, exactly (INV 12).

    `fact_ids_not_revealed` is **every** fact the utterance would have revealed, not the ones the
    prefix happened to miss: "facts are revealed by code, not by text" (D10), and the code that
    reveals them is the uninterrupted `CALLER_TTS_ENDED` that never happened. A reader of the log
    can therefore offer all of them again on the next turn, which is what INV 12 asserts.
    """
    return _event(
        EventType.CALLER_UTTERANCE_INTERRUPTED,
        _SIMULATION,
        offset_ms,
        {
            "call_id": call_id,
            "turn_index": turn_index,
            "planned_text": planned_text,
            "delivered_text": delivered_text,
            "delivered_audio_ms": delivered_audio_ms,
            "total_audio_ms_generated": total_audio_ms_generated,
            "cutoff_latency_ms": cutoff_latency_ms,
            # Beside the catalogued keys (§6.3's payload block):
            "turn_id": str(turn_id),
            "interrupting_turn_id": str(interrupting_turn_id),
            "alignment_is_exact": alignment_is_exact,
            "fact_ids_not_revealed": list(fact_ids_not_revealed),
        },
        correlation_id=turn_id,
    )


def facts_delivered_event(
    *,
    turn_id: uuid.UUID,
    turn_index: int,
    offset_ms: int,
    at_offset_ms: int,
    fact_ids: Sequence[str],
) -> DomainEvent:
    """`FACTS_DELIVERED` — appended **only** after an uninterrupted `CALLER_TTS_ENDED` (D10).

    `delivered_via` is the catalog's single literal `"TTS_COMPLETED"`, which says the same thing
    the event's position in the log does: a fact is revealed when the trainee has heard it, not
    when the gate allowed it or the generator wrote it.
    """
    return _event(
        EventType.FACTS_DELIVERED,
        _SIMULATION,
        offset_ms,
        {
            "turn_index": turn_index,
            "fact_ids": list(fact_ids),
            "delivered_via": "TTS_COMPLETED",
            "at_offset_ms": at_offset_ms,
            # Beside the catalogued keys:
            "turn_id": str(turn_id),
        },
        correlation_id=turn_id,
    )


def model_fallback_used_event(
    *,
    offset_ms: int,
    component: str,
    reason: str,
    attempt: int,
    fallback_kind: str,
    turn_index: int | None,
    turn_id: uuid.UUID | None = None,
) -> DomainEvent:
    """`MODEL_FALLBACK_USED` for a *voice-path* stage — E14 uses it for `component = "TTS"`.

    `component` is §10.13's catalogued key and `stage` is what §6/§7.8 call the same thing; both
    are carried, exactly as E13 resolved it for the interpreter's fallback.
    """
    return _event(
        EventType.MODEL_FALLBACK_USED,
        _SYSTEM,
        offset_ms,
        {
            "component": component,
            "reason": reason,
            "attempt": attempt,
            "fallback_kind": fallback_kind,
            "turn_index": turn_index,
            # Beside the catalogued keys:
            "stage": component,
            "turn_id": None if turn_id is None else str(turn_id),
        },
        correlation_id=turn_id,
    )


class VoiceEventAppender:
    """Appends voice events through one `UnitOfWork` per batch (D5, D9).

    One transaction per append batch, and the `audio_segments` rows of the batch commit inside
    it (§9.1): `append(..., segments=[...])` is the only way the recorder's index reaches the
    database, so "the row and the event commit together, or neither does" is a property of the
    call site and not of a convention.
    """

    def __init__(
        self,
        *,
        session_id: SessionId,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        started_at: Any = None,
        actor_id: UserId | None = None,
    ) -> None:
        self._session_id = session_id
        self._uow_factory = uow_factory
        self._clock = clock
        self._started_at = started_at
        self._actor_id = actor_id

    @property
    def session_id(self) -> SessionId:
        """The session every append targets."""
        return self._session_id

    def offset_ms(self) -> int:
        """A quick, in-process estimate of the session offset *right now* (SPEC §39, D7).

        Derived from the persisted `started_at` and the injected `Clock`, never from a process
        counter, so it survives a restart. Callers use this synchronously, before `append()` is
        even called, to build an event's payload and to measure in-process relative latencies
        (`application/voice/turn_pipeline.py`'s hot path) — it does not read the database and does
        not need to be exact.

        It is deliberately NOT the value that ends up persisted: `append()` below re-stamps every
        event's `monotonic_offset_ms` from a fresh read of the session row at append time, which
        is what actually freezes during an open `ROLE_TRANSITION` (E20-E2, R11 follow-up). This
        method stays the raw, unfrozen `session_offset_ms` it always was — good enough for a
        payload field and a latency diff, wrong for the one number SPEC §39/D7 care about, which
        is why `append()` no longer trusts it.
        """
        return session_offset_ms(self._clock.now(), self._started_at)

    async def append(
        self,
        events: Sequence[DomainEvent],
        *,
        segments: Sequence[StoredAudioSegment] = (),
        transcript_segments: Sequence[StoredTranscriptSegment] = (),
        dialogue_turns: Sequence[DialogueTurnUpsert] = (),
    ) -> list[SessionEvent]:
        """Append the events and every row that must commit with them, in one transaction.

        §9.1's ordering guarantee covers the transcript exactly as it covers the recording index:
        the `transcript_segments` row and the `ASR_FINAL` that names it are one write, so
        `ASR_FINAL.transcript_segment_id` never points at a row that is not there — and a failure
        on either side leaves neither (E12's atomicity test asserts both directions).

        **The persisted offset comes from here, not from `offset_ms()`** (E20-E2, R11 follow-up:
        the audit-2 "raw wall offset" finding). Every other application-layer writer stamps
        `monotonic_offset_ms` with `app.application.simulation.sim_time.running_ms` — frozen for
        the duration of an open `ROLE_TRANSITION` (`sim_time.py`'s module docstring) — and this
        was the one that did not. Fixed by reading the session row fresh, in the SAME transaction
        this method already opens (`uow.sessions.get(...)`, the plain, UNLOCKED read — never
        `get_for_update`: R14 gives the `simulation_sessions` row exactly one lock mode and one
        acquirer, `EventStore.append`'s own `seq_no` allocation; a second lock here would be a new
        way to deadlock it), and re-stamping every event of the batch with `running_ms(session,
        clock.now())` before it reaches `EventStore.append`. `events` passed in already carry a
        `monotonic_offset_ms` from `offset_ms()` above — that value is what a lookup that finds
        nothing, or fails outright (`SessionRepository.get` raises `LookupError` for a row whose
        `incidents` sibling is missing — a real invariant violation in production, but a shortcut
        some lower-level fixtures take on purpose), falls back to: a session lookup problem
        degrades to the old, raw-offset behaviour rather than refusing the append.
        """
        if not events and not segments and not transcript_segments and not dialogue_turns:
            return []
        async with self._uow_factory() as uow:
            if events:
                session: SimulationSession | None = None
                try:
                    session = await uow.sessions.get(self._session_id)
                except LookupError:
                    # No aggregate for this row (fixtures without an incident): keep the raw
                    # offset already on `events` — never refuse the append for that.
                    session = None
                if session is not None:
                    frozen_offset_ms = running_ms(session, self._clock.now())
                    events = [
                        event.model_copy(update={"monotonic_offset_ms": frozen_offset_ms})
                        for event in events
                    ]
            if segments:
                await uow.audio_segments.add_all(segments)
            for segment in transcript_segments:
                await uow.transcript_segments.add(segment)
            for turn in dialogue_turns:
                await uow.dialogue_turns.upsert(turn)
            appended = await uow.events.append(self._session_id, events)
            await uow.commit()
        return appended
