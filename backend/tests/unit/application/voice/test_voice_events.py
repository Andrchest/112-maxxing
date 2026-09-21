"""`events.py` — pipeline facts become catalogued `SessionEvent`s (§3.2, §3.7, §10.13, D5)."""

from __future__ import annotations

import uuid

import pytest
from app.application.ports.call_transport import TransportEvent, TransportEventType
from app.application.testing.fakes import FakeClock
from app.application.voice.events import (
    VoiceEventAppender,
    call_ended_event,
    transport_event_to_domain_event,
    user_speech_ended_event,
    user_speech_started_event,
)
from app.application.voice.turn_detector import DetectedTurn, SpeechStarted, TurnEndReason
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType
from app.domain.events.catalog import EVENT_PAYLOAD_CATALOG, validate_payload
from app.domain.events.types import EventType

from tests.unit.application.voice.conftest import VoiceStore, uow_factory

CALL_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def a_turn(*, discarded_short: bool = False, is_barge_in: bool = False) -> DetectedTurn:
    return DetectedTurn(
        turn_id=uuid.uuid4(),
        turn_index=3,
        audio=b"\x00\x00" * 1600,
        start_ms=4000,
        end_ms=5200,
        is_barge_in=is_barge_in,
        pre_roll_ms=300,
        end_reason=TurnEndReason.ENDPOINT_SILENCE,
        discarded_short=discarded_short,
    )


def test_user_speech_started_carries_the_catalogued_keys_and_the_trainee_actor() -> None:
    """§10.13's `USER_SPEECH_STARTED` row: `{call_id, turn_index, at_offset_ms, vad_provider}`."""
    started = SpeechStarted(
        turn_id=uuid.uuid4(), turn_index=0, start_ms=1200, was_during_playback=False
    )
    event = user_speech_started_event(
        started, call_id=CALL_ID, offset_ms=1500, vad_provider="energy"
    )

    spec = EVENT_PAYLOAD_CATALOG[EventType.USER_SPEECH_STARTED]
    assert set(spec.payload_keys) <= set(event.payload)
    assert event.actor.actor_type in spec.actor_types
    assert event.actor.actor_type is ActorType.TRAINEE
    assert event.payload["vad_provider"] == "energy"
    assert event.payload["turn_id"] == str(started.turn_id)
    assert event.correlation_id == started.turn_id
    validate_payload(EventType.USER_SPEECH_STARTED, event.payload)


def test_user_speech_ended_reports_discarded_short() -> None:
    """§4.4: a sub-`min_turn_ms` turn is still logged, flagged `discarded_short`."""
    turn = a_turn(discarded_short=True)
    event = user_speech_ended_event(turn, call_id=CALL_ID, offset_ms=5300, endpoint_silence_ms=320)

    spec = EVENT_PAYLOAD_CATALOG[EventType.USER_SPEECH_ENDED]
    assert set(spec.payload_keys) <= set(event.payload)
    assert event.payload["discarded_short"] is True
    assert event.payload["end_reason"] == TurnEndReason.ENDPOINT_SILENCE.value
    assert event.payload["endpoint_silence_ms"] == 320
    assert event.payload["speech_duration_ms"] == turn.duration_ms
    validate_payload(EventType.USER_SPEECH_ENDED, event.payload)


@pytest.mark.parametrize(
    ("transport_type", "event_type"),
    [
        (TransportEventType.DISCONNECTED, EventType.TRANSPORT_DISCONNECTED),
        (TransportEventType.RECONNECTED, EventType.TRANSPORT_RECONNECTED),
    ],
)
def test_transport_transitions_map_to_their_catalogued_events(
    transport_type: TransportEventType, event_type: EventType
) -> None:
    """§3.7: the two transitions that have a catalog row become events; the rest do not."""
    event = transport_event_to_domain_event(
        TransportEvent(
            type=transport_type,
            call_id=CALL_ID,
            at_offset_ms=9000,
            participant_identity="trainee-1",
        ),
        offset_ms=9100,
        downtime_ms=450,
    )
    assert event is not None
    assert event.event_type is event_type
    assert event.actor.actor_type is ActorType.SYSTEM
    validate_payload(event_type, event.payload)
    if event_type is EventType.TRANSPORT_RECONNECTED:
        assert event.payload["downtime_ms"] == 450


@pytest.mark.parametrize(
    "transport_type",
    [
        TransportEventType.CONNECTED,
        TransportEventType.PARTICIPANT_JOINED,
        TransportEventType.TRACK_SUBSCRIBED,
        TransportEventType.RECONNECTING,
        TransportEventType.TRANSPORT_ERROR,
    ],
)
def test_media_plane_bookkeeping_is_not_persisted(transport_type: TransportEventType) -> None:
    """A type with no catalog row must not be invented into one (§10.13 is closed, D5)."""
    assert (
        transport_event_to_domain_event(
            TransportEvent(type=transport_type, call_id=CALL_ID, at_offset_ms=1),
            offset_ms=1,
        )
        is None
    )


def test_call_ended_on_transport_close_is_a_simulation_actor() -> None:
    """§3.7: the trainee's own hang-up is `end_call`'s event; this is the media plane going away."""
    event = call_ended_event(
        call_id=CALL_ID,
        offset_ms=20_000,
        at_offset_ms=20_000,
        duration_ms=18_000,
        reason="TRANSPORT_CLOSED",
    )
    spec = EVENT_PAYLOAD_CATALOG[EventType.CALL_ENDED]
    assert event.actor.actor_type is ActorType.SIMULATION
    assert event.actor.actor_type in spec.actor_types
    assert event.payload["ended_by"] == ActorType.SIMULATION.value
    validate_payload(EventType.CALL_ENDED, event.payload)


async def test_the_appender_commits_events_and_audio_rows_in_one_transaction() -> None:
    """§9.1's ordering guarantee: the `audio_segments` row and the event commit together."""
    clock = FakeClock()
    store = VoiceStore()
    session_id = SessionId(uuid.uuid4())
    appender = VoiceEventAppender(
        session_id=session_id, uow_factory=uow_factory(store, clock), clock=clock
    )
    turn = a_turn()
    event = user_speech_ended_event(turn, call_id=CALL_ID, offset_ms=5300, endpoint_silence_ms=320)

    appended = await appender.append([event])

    assert [e.event_type for e in appended] == [EventType.USER_SPEECH_ENDED]
    assert store.commits == 1
    assert [e.seq_no for e in store.events] == [1]


async def test_an_empty_append_is_a_no_op() -> None:
    """No transaction, no `seq_no` burned (`EventStore.append`'s documented empty case)."""
    clock = FakeClock()
    store = VoiceStore()
    appender = VoiceEventAppender(
        session_id=SessionId(uuid.uuid4()), uow_factory=uow_factory(store, clock), clock=clock
    )
    assert await appender.append([]) == []
    assert store.commits == 0


async def test_offsets_come_from_started_at_and_the_clock_not_from_a_process_counter() -> None:
    """SPEC §39 / D7: an offset survives a restart because it is derived from persisted state."""
    clock = FakeClock()
    store = VoiceStore()
    appender = VoiceEventAppender(
        session_id=SessionId(uuid.uuid4()),
        uow_factory=uow_factory(store, clock),
        clock=clock,
        started_at=clock.now(),
    )
    assert appender.offset_ms() == 0
    clock.advance_ms(7_500)
    assert appender.offset_ms() == 7_500
