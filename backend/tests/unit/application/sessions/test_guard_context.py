"""`build_guard_runtime` — the event-log projection of `GuardRuntime` (§10.8, D5).

Pure function, so every case is a hand-built `SessionEvent` list: no database, no use case.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.application.sessions.guard_context import build_guard_runtime
from app.domain.common.ids import EventId, SessionId
from app.domain.enums import ActorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

SESSION = SessionId(uuid4())
_AT = datetime(2026, 1, 1, tzinfo=UTC)


def event(event_type: EventType, seq_no: int, monotonic_offset_ms: int = 0) -> SessionEvent:
    """One persisted event; only `event_type` and `monotonic_offset_ms` are ever read."""
    return SessionEvent(
        id=EventId(uuid4()),
        session_id=SESSION,
        seq_no=seq_no,
        event_type=event_type,
        timestamp_utc=_AT,
        monotonic_offset_ms=monotonic_offset_ms,
        actor_type=ActorType.SYSTEM,
        payload={},
    )


def runtime(*events: SessionEvent, scenario_valid: bool = True, inference_ready: bool = True):  # type: ignore[no-untyped-def]
    return build_guard_runtime(
        list(events), scenario_valid=scenario_valid, inference_ready=inference_ready
    )


def test_empty_log_denies_every_runtime_dependent_transition() -> None:
    result = runtime(scenario_valid=False, inference_ready=False)
    assert result.scenario_valid is False
    assert result.inference_ready is False
    assert result.first_finalized_turn is False
    assert result.call_connected is False
    assert result.call_ended is False
    assert result.resolution_condition_met is False
    assert result.transition_started_ms is None


def test_the_two_caller_supplied_facts_pass_through() -> None:
    result = runtime(scenario_valid=True, inference_ready=True)
    assert result.scenario_valid is True
    assert result.inference_ready is True


def test_asr_final_sets_first_finalized_turn() -> None:
    assert runtime(event(EventType.ASR_PARTIAL, 1)).first_finalized_turn is False
    assert runtime(event(EventType.ASR_FINAL, 1)).first_finalized_turn is True


def test_call_answered_connects_and_call_ended_disconnects() -> None:
    answered = runtime(event(EventType.CALL_ANSWERED, 1))
    assert (answered.call_connected, answered.call_ended) == (True, False)

    ended = runtime(event(EventType.CALL_ANSWERED, 1), event(EventType.CALL_ENDED, 2))
    assert (ended.call_connected, ended.call_ended) == (False, True)


def test_a_second_call_reopens_the_connection() -> None:
    result = runtime(
        event(EventType.CALL_ANSWERED, 1),
        event(EventType.CALL_ENDED, 2),
        event(EventType.CALL_ANSWERED, 3),
    )
    assert (result.call_connected, result.call_ended) == (True, False)


def test_transition_started_ms_is_the_offset_of_the_open_role_transition() -> None:
    started = runtime(event(EventType.ROLE_TRANSITION_STARTED, 1, monotonic_offset_ms=4200))
    assert started.transition_started_ms == 4200

    finished = runtime(
        event(EventType.ROLE_TRANSITION_STARTED, 1, monotonic_offset_ms=4200),
        event(EventType.ROLE_TRANSITION_COMPLETED, 2, monotonic_offset_ms=9000),
    )
    assert finished.transition_started_ms is None

    second = runtime(
        event(EventType.ROLE_TRANSITION_STARTED, 1, monotonic_offset_ms=4200),
        event(EventType.ROLE_TRANSITION_COMPLETED, 2, monotonic_offset_ms=9000),
        event(EventType.ROLE_TRANSITION_STARTED, 3, monotonic_offset_ms=15000),
    )
    assert second.transition_started_ms == 15000


def test_transport_ready_is_never_derived_from_the_log() -> None:
    """TODO(E11): no catalogued event states that the `CallTransport` is up, so the flag stays
    at its conservative default even after the transport events the catalog does have."""
    result = runtime(
        event(EventType.TRANSPORT_RECONNECTED, 1),
        event(EventType.CALL_RINGING, 2),
        event(EventType.CALL_ANSWERED, 3),
    )
    assert result.transport_ready is False


def test_unrelated_events_change_nothing() -> None:
    result = runtime(
        event(EventType.SESSION_CREATED, 1),
        event(EventType.SESSION_STARTED, 2),
        event(EventType.CARD_FIELD_CHANGED, 3),
    )
    assert result == runtime()
