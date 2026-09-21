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

This module emits the E11 events only — the boundary signals, the transport transitions and the
end of the call. `ASR_*`, `DIALOGUE_INTERPRETED`, `FACT_GATE_EVALUATED`, `CALLER_*` and
`FACTS_DELIVERED` are TODO(E12) / TODO(E13) / TODO(E14): the epics that first produce the fact are
the epics that get to say what it is.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.call_transport import TransportEvent, TransportEventType
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.timebase import session_offset_ms
from app.application.voice.turn_detector import DetectedTurn, SpeechStarted
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId, UserId
from app.domain.enums import ActorType
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType

__all__ = [
    "VoiceEventAppender",
    "call_ended_event",
    "transport_event_to_domain_event",
    "user_speech_ended_event",
    "user_speech_started_event",
]

_TRAINEE = ActorRef(actor_type=ActorType.TRAINEE)
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
        """The session offset an event appended *now* is stamped with (SPEC §39, D7).

        Derived from the persisted `started_at` and the injected `Clock`, never from a process
        counter, so an event appended after a restart lines up with the ones before it.
        """
        return session_offset_ms(self._clock.now(), self._started_at)

    async def append(
        self,
        events: Sequence[DomainEvent],
        *,
        segments: Sequence[StoredAudioSegment] = (),
    ) -> list[SessionEvent]:
        """Append the events and the audio-segment rows in one transaction."""
        if not events and not segments:
            return []
        async with self._uow_factory() as uow:
            if segments:
                await uow.audio_segments.add_all(segments)
            appended = await uow.events.append(self._session_id, events)
            await uow.commit()
        return appended
