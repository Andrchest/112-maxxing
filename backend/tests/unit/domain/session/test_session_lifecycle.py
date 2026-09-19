"""`SimulationSession` behaviour: the happy paths, the events each one emits (validated against
`EVENT_PAYLOAD_CATALOG`), and the illegal calls that must raise `InvalidTransitionError` while
leaving the caller's aggregate untouched (SPEC §7, §13, §42 tests 5 and 8).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.state_machine import GuardRuntime
from app.domain.enums import (
    ActorType,
    DDSStageState,
    Operator112StageState,
    ResourceStatus,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.events.catalog import validate_payload
from app.domain.events.types import EventType
from app.domain.session.session import SessionParticipant, SimulationSession

from tests.unit.domain.session import _builders as b

OP = RoleType.OPERATOR_112
DDS = RoleType.DDS
STARTED_AT = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 1, 1, 9, 30, 0, tzinfo=UTC)

OP_TRAINEE = b.actor(ActorType.TRAINEE, "op")
DDS_TRAINEE = b.actor(ActorType.TRAINEE, "dds")


def _session(
    *,
    state: SessionState,
    first_state: Operator112StageState = Operator112StageState.WAITING_FOR_CALL,
    second_state: DDSStageState = DDSStageState.RECEIVED,
    first_started_ms: int | None = None,
    second_started_ms: int | None = None,
) -> SimulationSession:
    stages = [
        b.build_stage(
            order_index=0,
            role_type=OP,
            state=first_state,
            participant_user_id=b.user("op"),
            started_at_offset_ms=first_started_ms,
        ),
        b.build_stage(
            order_index=1,
            role_type=DDS,
            state=second_state,
            participant_user_id=b.user("dds"),
            started_at_offset_ms=second_started_ms,
        ),
    ]
    return b.build_session(
        session_mode=SessionMode.MULTI_TRAINEE,
        state=state,
        stages=stages,
        participants=[
            SessionParticipant(user_id=b.user("op"), assigned_role_type=OP),
            SessionParticipant(user_id=b.user("dds"), assigned_role_type=DDS),
        ],
    )


def _check_payloads(events: list[Any]) -> None:
    for event in events:
        validate_payload(event.event_type, event.payload)


def _unchanged(before: SimulationSession, call: Any) -> None:
    """The call must raise `InvalidTransitionError` and leave `before` byte-for-byte equal."""
    snapshot = before.model_copy(deep=True)
    with pytest.raises(InvalidTransitionError):
        call()
    assert before == snapshot


# ---------------------------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------------------------


def test_current_stage_skips_terminal_stages_and_active_stage_does_not() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.STAGE_COMPLETED,
        first_started_ms=0,
    )
    assert session.current_stage is not None
    assert session.current_stage.order_index == 1
    assert session.active_stage is not None
    assert session.active_stage.order_index == 0


def test_stage_lookup_and_next_stage_after() -> None:
    session = _session(state=SessionState.ACTIVE, first_started_ms=0)
    first = session.stages[0]
    assert session.stage(first.role_stage_id) is first
    next_stage = session.next_stage_after(first)
    assert next_stage is not None and next_stage.order_index == 1
    assert session.next_stage_after(session.stages[1]) is None
    with pytest.raises(KeyError):
        session.stage(b.det_uuid("nope"))  # type: ignore[arg-type]


def test_policy_is_the_mode_policy() -> None:
    session = _session(state=SessionState.CREATED)
    assert session.policy.session_mode is SessionMode.MULTI_TRAINEE
    assert session.policy.transition_pause_seconds == 10


# ---------------------------------------------------------------------------------------------
# validate / start
# ---------------------------------------------------------------------------------------------


def test_validate_moves_created_to_ready_and_emits_nothing() -> None:
    session = _session(state=SessionState.CREATED)
    updated, events = session.validate_session(
        actor=b.SYSTEM, runtime=GuardRuntime(scenario_valid=True)
    )
    assert updated.state is SessionState.READY
    assert events == []
    assert session.state is SessionState.CREATED


def test_start_moves_ready_to_active_and_emits_session_started_then_role_stage_started() -> None:
    session = _session(state=SessionState.READY)
    updated, events = session.start(
        STARTED_AT, actor=b.INSTRUCTOR, now_ms=0, runtime=GuardRuntime(inference_ready=True)
    )
    assert updated.state is SessionState.ACTIVE
    assert updated.started_at == STARTED_AT
    assert updated.stages[0].started_at_offset_ms == 0
    assert updated.stages[1].started_at_offset_ms is None
    assert [e.event_type for e in events] == [
        EventType.SESSION_STARTED,
        EventType.ROLE_STAGE_STARTED,
    ]
    _check_payloads(events)
    assert events[0].payload["first_role_type"] == "OPERATOR_112"
    assert events[1].payload["initial_state"] == "WAITING_FOR_CALL"
    assert events[1].payload["participant_user_id"] == str(b.user("op"))


def test_start_from_created_is_rejected() -> None:
    session = _session(state=SessionState.CREATED)
    _unchanged(
        session,
        lambda: session.start(
            STARTED_AT, actor=b.INSTRUCTOR, runtime=GuardRuntime(inference_ready=True)
        ),
    )


def test_start_by_a_trainee_is_rejected() -> None:
    session = _session(state=SessionState.READY)
    _unchanged(
        session,
        lambda: session.start(
            STARTED_AT, actor=OP_TRAINEE, runtime=GuardRuntime(inference_ready=True)
        ),
    )


def test_validate_by_an_instructor_is_rejected() -> None:
    """`CREATED --validate--> READY` is SYSTEM-only (§10.8)."""
    session = _session(state=SessionState.CREATED)
    _unchanged(
        session,
        lambda: session.validate_session(
            actor=b.INSTRUCTOR, runtime=GuardRuntime(scenario_valid=True)
        ),
    )


# ---------------------------------------------------------------------------------------------
# role transition / complete
# ---------------------------------------------------------------------------------------------


def test_begin_and_finish_role_transition() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.STAGE_COMPLETED,
        first_started_ms=0,
    )
    in_transition, events = session.begin_role_transition(
        actor=b.SYSTEM, now_ms=5_000, runtime=GuardRuntime()
    )
    assert in_transition.state is SessionState.ROLE_TRANSITION
    assert [e.event_type for e in events] == [EventType.ROLE_TRANSITION_STARTED]
    _check_payloads(events)
    assert events[0].payload["pause_seconds"] == 10
    assert events[0].payload["to_role_type"] == "DDS"

    resumed, resume_events = in_transition.finish_role_transition(
        actor=b.SYSTEM, now_ms=20_000, runtime=GuardRuntime(transition_started_ms=5_000)
    )
    assert resumed.state is SessionState.ACTIVE
    assert resumed.stages[1].started_at_offset_ms == 20_000
    assert [e.event_type for e in resume_events] == [
        EventType.ROLE_TRANSITION_COMPLETED,
        EventType.ROLE_STAGE_STARTED,
    ]
    _check_payloads(resume_events)
    assert resume_events[0].payload["incident_id"] == str(b.INCIDENT_ID)
    # SPEC §13: the role change did not create a new incident.
    assert resumed.incident == session.incident


def test_finish_role_transition_before_the_pause_elapsed_is_rejected() -> None:
    session = _session(
        state=SessionState.ROLE_TRANSITION,
        first_state=Operator112StageState.STAGE_COMPLETED,
        first_started_ms=0,
    )
    _unchanged(
        session,
        lambda: session.finish_role_transition(
            actor=b.SYSTEM, now_ms=9_000, runtime=GuardRuntime(transition_started_ms=0)
        ),
    )


def test_begin_role_transition_while_the_stage_is_still_running_is_rejected() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.INTERVIEW,
        first_started_ms=0,
    )
    _unchanged(
        session,
        lambda: session.begin_role_transition(actor=b.SYSTEM, runtime=GuardRuntime()),
    )


def test_complete_moves_active_to_completed() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.STAGE_COMPLETED,
        second_state=DDSStageState.CLOSED,
        first_started_ms=0,
        second_started_ms=20_000,
    )
    updated, events = session.complete(
        COMPLETED_AT, actor=b.SYSTEM, now_ms=60_000, runtime=GuardRuntime()
    )
    assert updated.state is SessionState.COMPLETED
    assert updated.completed_at == COMPLETED_AT
    assert [e.event_type for e in events] == [EventType.SESSION_COMPLETED]
    _check_payloads(events)
    assert events[0].payload["final_session_state"] == "COMPLETED"
    assert updated.incident == session.incident


def test_complete_while_a_later_stage_remains_is_rejected() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.STAGE_COMPLETED,
        first_started_ms=0,
    )
    _unchanged(
        session,
        lambda: session.complete(COMPLETED_AT, actor=b.SYSTEM, runtime=GuardRuntime()),
    )


# ---------------------------------------------------------------------------------------------
# abort
# ---------------------------------------------------------------------------------------------


def test_abort_closes_every_non_terminal_stage_and_emits_session_aborted_last() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.INTERVIEW,
        first_started_ms=0,
    )
    updated, events = session.abort(
        "инструктор остановил сессию", actor=b.INSTRUCTOR, now_ms=12_000, runtime=GuardRuntime()
    )
    assert updated.state is SessionState.ABORTED
    assert updated.abort_reason == "инструктор остановил сессию"
    assert updated.stages[0].state is Operator112StageState.STAGE_COMPLETED
    assert updated.stages[1].state is DDSStageState.CLOSED
    assert all(stage.completed_at_offset_ms == 12_000 for stage in updated.stages)
    assert [e.event_type for e in events] == [
        EventType.STAGE_STATE_CHANGED,
        EventType.STAGE_STATE_CHANGED,
        EventType.SESSION_ABORTED,
    ]
    _check_payloads(events)
    assert events[-1].payload["previous_state"] == "ACTIVE"
    assert events[0].payload["trigger"] == "abort_stage"
    # SPEC §13: aborting does not replace the incident.
    assert updated.incident == session.incident


def test_abort_skips_already_terminal_stages() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.STAGE_COMPLETED,
        first_started_ms=0,
    )
    updated, events = session.abort("stop", actor=b.SYSTEM, now_ms=3_000, runtime=GuardRuntime())
    stage_events = [e for e in events if e.event_type is EventType.STAGE_STATE_CHANGED]
    assert len(stage_events) == 1
    assert stage_events[0].payload["role_type"] == "DDS"
    assert updated.stages[0].completed_at_offset_ms is None


def test_abort_from_created_is_allowed() -> None:
    session = _session(state=SessionState.CREATED)
    updated, _events = session.abort("stop", actor=b.SYSTEM, runtime=GuardRuntime())
    assert updated.state is SessionState.ABORTED


def test_abort_from_completed_is_rejected() -> None:
    session = _session(
        state=SessionState.COMPLETED,
        first_state=Operator112StageState.STAGE_COMPLETED,
        second_state=DDSStageState.CLOSED,
        first_started_ms=0,
    )
    _unchanged(session, lambda: session.abort("stop", actor=b.SYSTEM, runtime=GuardRuntime()))


def test_abort_by_a_trainee_is_rejected() -> None:
    session = _session(state=SessionState.ACTIVE, first_started_ms=0)
    _unchanged(session, lambda: session.abort("stop", actor=OP_TRAINEE, runtime=GuardRuntime()))


# ---------------------------------------------------------------------------------------------
# fire_stage_trigger
# ---------------------------------------------------------------------------------------------


def test_fire_stage_trigger_emits_stage_state_changed_only() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.RINGING,
        first_started_ms=0,
    )
    updated, events = session.fire_stage_trigger(
        session.stages[0].role_stage_id,
        "answer",
        actor=OP_TRAINEE,
        now_ms=4_000,
        runtime=GuardRuntime(),
    )
    assert updated.stages[0].state is Operator112StageState.CONNECTED
    assert [e.event_type for e in events] == [EventType.STAGE_STATE_CHANGED]
    _check_payloads(events)
    assert events[0].payload["previous_state"] == "RINGING"
    assert events[0].payload["new_state"] == "CONNECTED"
    assert events[0].payload["fired_by_user_id"] == str(b.user("op"))


def test_fire_stage_trigger_adds_role_stage_completed_on_a_terminal_target() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.HANDED_OFF,
        first_started_ms=1_000,
    )
    updated, events = session.fire_stage_trigger(
        session.stages[0].role_stage_id,
        "complete_stage",
        actor=OP_TRAINEE,
        now_ms=61_000,
        runtime=GuardRuntime(call_ended=True),
    )
    assert updated.stages[0].state is Operator112StageState.STAGE_COMPLETED
    assert updated.stages[0].completed_at_offset_ms == 61_000
    assert [e.event_type for e in events] == [
        EventType.STAGE_STATE_CHANGED,
        EventType.ROLE_STAGE_COMPLETED,
    ]
    _check_payloads(events)
    assert events[1].payload["duration_ms"] == 60_000
    assert updated.incident == session.incident


def test_fire_stage_trigger_drives_the_dds_machine() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.STAGE_COMPLETED,
        second_state=DDSStageState.RESOURCE_SELECTION,
        first_started_ms=0,
        second_started_ms=20_000,
    )
    updated, events = session.fire_stage_trigger(
        session.stages[1].role_stage_id,
        "dispatch",
        actor=DDS_TRAINEE,
        now_ms=30_000,
        runtime=GuardRuntime(),
        resources=b.resources(ResourceStatus.SELECTED),
    )
    assert updated.stages[1].state is DDSStageState.DISPATCHED
    _check_payloads(events)


def test_a_dds_participant_cannot_fire_an_operator_112_trigger() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.RINGING,
        first_started_ms=0,
    )
    _unchanged(
        session,
        lambda: session.fire_stage_trigger(
            session.stages[0].role_stage_id,
            "answer",
            actor=DDS_TRAINEE,
            runtime=GuardRuntime(),
        ),
    )


def test_a_trainee_cannot_fire_a_simulation_trigger() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.WAITING_FOR_CALL,
        first_started_ms=0,
    )
    _unchanged(
        session,
        lambda: session.fire_stage_trigger(
            session.stages[0].role_stage_id,
            "ring",
            actor=OP_TRAINEE,
            runtime=GuardRuntime(transport_ready=True),
        ),
    )


def test_fire_stage_trigger_rejects_a_trigger_the_stage_state_does_not_offer() -> None:
    session = _session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.WAITING_FOR_CALL,
        first_started_ms=0,
    )
    _unchanged(
        session,
        lambda: session.fire_stage_trigger(
            session.stages[0].role_stage_id,
            "create_handoff",
            actor=OP_TRAINEE,
            runtime=GuardRuntime(),
        ),
    )


def test_fire_stage_trigger_raises_key_error_for_an_unknown_stage() -> None:
    session = _session(state=SessionState.ACTIVE, first_started_ms=0)
    with pytest.raises(KeyError):
        session.fire_stage_trigger(
            b.det_uuid("nope"),  # type: ignore[arg-type]
            "ring",
            actor=b.SIMULATION,
            runtime=GuardRuntime(transport_ready=True),
        )


# ---------------------------------------------------------------------------------------------
# The incident survives every method (SPEC §13, §42 test 5)
# ---------------------------------------------------------------------------------------------


def test_the_incident_is_never_replaced_by_any_method() -> None:
    session = _session(state=SessionState.CREATED)
    incident = session.incident

    ready, _ = session.validate_session(actor=b.SYSTEM, runtime=GuardRuntime(scenario_valid=True))
    active, _ = ready.start(
        STARTED_AT, actor=b.INSTRUCTOR, runtime=GuardRuntime(inference_ready=True)
    )
    answered, _ = active.fire_stage_trigger(
        active.stages[0].role_stage_id,
        "ring",
        actor=b.SIMULATION,
        now_ms=1_000,
        runtime=GuardRuntime(transport_ready=True),
    )
    aborted, _ = answered.abort("stop", actor=b.INSTRUCTOR, now_ms=2_000, runtime=GuardRuntime())

    for value in (ready, active, answered, aborted):
        assert value.incident == incident
        assert {stage.incident_id for stage in value.stages} == {incident.incident_id}
