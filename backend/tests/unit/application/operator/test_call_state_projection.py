"""`project_call_state` — the phone widget's state, folded from the log alone (D5, SPEC §8).

Call state has no table and no Redis hash of its own (the `session:{id}:call_state` key of §40.6
is deliberately not implemented — TODO(E11)). It is a pure fold over `session_events`, which is
the audit source, so these tests are pure too: no database, no clock, no container.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.operator.views import CallPhase, project_call_state
from app.domain.common.ids import EventId, SessionId
from app.domain.enums import ActorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

SESSION = SessionId(UUID("00000000-0000-4000-8000-0000000000aa"))
CALL = uuid4()
ROOM = "session-00000000-0000-4000-8000-0000000000aa"


def event(event_type: EventType, offset_ms: int, seq_no: int, **payload: object) -> SessionEvent:
    """One persisted event, with only the payload keys the fold reads."""
    return SessionEvent(
        id=EventId(uuid4()),
        session_id=SESSION,
        seq_no=seq_no,
        event_type=event_type,
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        monotonic_offset_ms=offset_ms,
        actor_type=ActorType.SIMULATION,
        payload=payload,
    )


def ringing(offset_ms: int = 100, seq_no: int = 1) -> SessionEvent:
    return event(
        EventType.CALL_RINGING,
        offset_ms,
        seq_no,
        call_id=str(CALL),
        room_name=ROOM,
        caller_display_ru="Неизвестный абонент",
    )


def test_an_empty_log_is_no_call() -> None:
    state = project_call_state([])
    assert state.phase is CallPhase.NO_CALL
    assert state.call_id is None
    assert state.room_name is None
    assert state.duration_ms is None
    assert state.caller_speaking is False


def test_call_ringing_opens_the_call_and_carries_its_identifiers() -> None:
    state = project_call_state([ringing()])
    assert state.phase is CallPhase.RINGING
    assert state.call_id == CALL
    assert state.room_name == ROOM
    assert state.caller_display_ru == "Неизвестный абонент"
    assert state.started_at_offset_ms == 100
    assert state.answered_at_offset_ms is None
    assert state.duration_ms is None


def test_call_answered_connects_it() -> None:
    state = project_call_state([ringing(), event(EventType.CALL_ANSWERED, 2_000, 2)])
    assert state.phase is CallPhase.CONNECTED
    assert state.answered_at_offset_ms == 2_000
    assert state.duration_ms is None, "an open call has no duration yet"


def test_call_ended_closes_it_and_the_duration_is_answer_to_hangup() -> None:
    """Not ring-to-hangup: the duration is the call the trainee actually conducted."""
    state = project_call_state(
        [
            ringing(offset_ms=100),
            event(EventType.CALL_ANSWERED, 2_000, 2),
            event(EventType.CALL_ENDED, 5_000, 3),
        ]
    )
    assert state.phase is CallPhase.ENDED
    assert state.ended_at_offset_ms == 5_000
    assert state.duration_ms == 3_000


def test_an_unanswered_call_that_ends_has_no_duration() -> None:
    state = project_call_state([ringing(), event(EventType.CALL_ENDED, 9_000, 2)])
    assert state.phase is CallPhase.ENDED
    assert state.duration_ms is None


def test_caller_tts_drives_the_speaking_flag() -> None:
    base = [ringing(), event(EventType.CALL_ANSWERED, 2_000, 2)]
    speaking = project_call_state([*base, event(EventType.CALLER_TTS_STARTED, 3_000, 3)])
    assert speaking.caller_speaking is True
    quiet = project_call_state(
        [
            *base,
            event(EventType.CALLER_TTS_STARTED, 3_000, 3),
            event(EventType.CALLER_TTS_ENDED, 4_000, 4),
        ]
    )
    assert quiet.caller_speaking is False


def test_a_barge_in_stops_the_speaking_flag() -> None:
    """SPEC §42 test 12: an interruption cancels the audio, so the meter must not keep running."""
    state = project_call_state(
        [
            ringing(),
            event(EventType.CALL_ANSWERED, 2_000, 2),
            event(EventType.CALLER_TTS_STARTED, 3_000, 3),
            event(EventType.CALLER_UTTERANCE_INTERRUPTED, 3_500, 4),
        ]
    )
    assert state.caller_speaking is False


def test_hanging_up_while_the_caller_speaks_stops_the_flag() -> None:
    state = project_call_state(
        [
            ringing(),
            event(EventType.CALL_ANSWERED, 2_000, 2),
            event(EventType.CALLER_TTS_STARTED, 3_000, 3),
            event(EventType.CALL_ENDED, 3_500, 4),
        ]
    )
    assert state.caller_speaking is False


def test_a_second_call_ringing_starts_the_fold_over() -> None:
    """A re-dial is a new call: its offsets must not be mixed with the previous one's."""
    second_call = uuid4()
    state = project_call_state(
        [
            ringing(offset_ms=100),
            event(EventType.CALL_ANSWERED, 2_000, 2),
            event(EventType.CALL_ENDED, 5_000, 3),
            event(
                EventType.CALL_RINGING,
                9_000,
                4,
                call_id=str(second_call),
                room_name="second-room",
                caller_display_ru="Второй звонок",
            ),
        ]
    )
    assert state.phase is CallPhase.RINGING
    assert state.call_id == second_call
    assert state.room_name == "second-room"
    assert state.started_at_offset_ms == 9_000
    assert state.answered_at_offset_ms is None
    assert state.ended_at_offset_ms is None


def test_an_unrelated_event_changes_nothing() -> None:
    """The fold reads five event types; everything else in the log is none of its business."""
    with_noise = project_call_state(
        [
            ringing(),
            event(EventType.CARD_FIELD_CHANGED, 2_500, 2),
            event(EventType.ASR_FINAL, 2_600, 3),
            event(EventType.CALL_ANSWERED, 3_000, 4),
        ]
    )
    without_noise = project_call_state([ringing(), event(EventType.CALL_ANSWERED, 3_000, 2)])
    assert with_noise == without_noise
