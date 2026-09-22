"""`events.py` — pipeline facts become catalogued `SessionEvent`s (§3.2, §3.7, §10.13, D5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

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
from app.domain.enums import (
    ActorType,
    DDSStageState,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.events.catalog import EVENT_PAYLOAD_CATALOG, validate_payload
from app.domain.events.types import EventType
from app.domain.session.session import SimulationSession

from tests.unit.application.voice.conftest import VoiceStore, uow_factory
from tests.unit.domain.session import _builders as sb

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


# -- E20-E2 (R11 follow-up): append() re-stamps monotonic_offset_ms from a fresh, unlocked read
# of the session row (sim_time.running_ms, frozen during ROLE_TRANSITION) — audit-2's "raw wall
# offset" finding. offset_ms() itself stays the raw, quick, in-process estimate it always was;
# only what gets PERSISTED changes. --------------------------------------------------------------

_STARTED_AT = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)


def _session(*, state: SessionState, transition_started_offset_ms: int | None) -> SimulationSession:
    """A session row with nothing in it but the fields `running_ms` reads (mirrors
    `tests.unit.application.simulation.test_sim_time._row`)."""
    session = sb.build_session(
        session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE,
        state=state,
        stages=[
            sb.build_stage(
                order_index=0,
                role_type=RoleType.OPERATOR_112,
                state=Operator112StageState.STAGE_COMPLETED,
                participant_user_id=sb.user("trainee"),
            ),
            sb.build_stage(
                order_index=1,
                role_type=RoleType.DDS,
                state=DDSStageState.RECEIVED,
                participant_user_id=sb.user("trainee"),
            ),
        ],
    )
    return session.model_copy(
        update={
            "started_at": _STARTED_AT,
            "role_transition_started_offset_ms": transition_started_offset_ms,
        }
    )


def _clock_at(offset_ms: int) -> FakeClock:
    """A `FakeClock` pinned `offset_ms` milliseconds after `_STARTED_AT`."""
    clock = FakeClock(start=_STARTED_AT)
    clock.advance_ms(offset_ms)
    return clock


async def test_offset_ms_stays_the_raw_wall_offset_its_own_local_estimate() -> None:
    """`offset_ms()` itself is unaffected by this fix — it is never what gets persisted now."""
    clock = _clock_at(90_000)
    store = VoiceStore()
    appender = VoiceEventAppender(
        session_id=SessionId(uuid.uuid4()),
        uow_factory=uow_factory(store, clock),
        clock=clock,
        started_at=_STARTED_AT,
    )
    assert appender.offset_ms() == 90_000


async def test_append_stamps_the_frozen_running_ms_during_a_role_transition() -> None:
    """A call event appended while its session sits in `ROLE_TRANSITION` is persisted with the
    frozen `running_ms`, not the raw wall-clock elapsed time the event was built with
    (E20-E2, R11 follow-up, audit-2)."""
    session_id = SessionId(uuid.uuid4())
    session = _session(state=SessionState.ROLE_TRANSITION, transition_started_offset_ms=30_000)
    clock = _clock_at(90_000)
    store = VoiceStore()
    store.sessions[session_id] = session
    appender = VoiceEventAppender(
        session_id=session_id, uow_factory=uow_factory(store, clock), clock=clock
    )
    # Built with the raw, unfrozen estimate — deliberately wrong, to prove append() overwrites it.
    turn = a_turn()
    event = user_speech_ended_event(
        turn, call_id=CALL_ID, offset_ms=appender.offset_ms(), endpoint_silence_ms=320
    )

    (appended,) = await appender.append([event])

    assert appended.monotonic_offset_ms == 30_000, "frozen at the offset the transition began at"


async def test_append_stamps_the_unfrozen_running_ms_outside_a_transition() -> None:
    """A normal INTERVIEW-phase event (no open transition) gets `running_ms`'s unfrozen value —
    the same number `offset_ms()` would already have produced, now sourced from the session row."""
    session_id = SessionId(uuid.uuid4())
    session = _session(state=SessionState.ACTIVE, transition_started_offset_ms=None)
    clock = _clock_at(45_000)
    store = VoiceStore()
    store.sessions[session_id] = session
    appender = VoiceEventAppender(
        session_id=session_id, uow_factory=uow_factory(store, clock), clock=clock
    )
    turn = a_turn()
    event = user_speech_ended_event(turn, call_id=CALL_ID, offset_ms=1, endpoint_silence_ms=320)

    (appended,) = await appender.append([event])

    assert appended.monotonic_offset_ms == 45_000


async def test_append_falls_back_to_the_events_own_offset_when_the_session_is_not_found() -> None:
    """No row for `session_id` in the fake store (every pre-existing test's default) -> the events
    pass through unchanged, the same behaviour `append()` always had."""
    clock = _clock_at(12_345)
    store = VoiceStore()
    appender = VoiceEventAppender(
        session_id=SessionId(uuid.uuid4()), uow_factory=uow_factory(store, clock), clock=clock
    )
    turn = a_turn()
    event = user_speech_ended_event(turn, call_id=CALL_ID, offset_ms=5300, endpoint_silence_ms=320)

    (appended,) = await appender.append([event])

    assert appended.monotonic_offset_ms == 5300
