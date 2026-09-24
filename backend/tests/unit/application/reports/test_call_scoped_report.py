"""The report groups a session's calls by `call_id` and labels their party (I3 E6c, HLD
`80-telephony.md` §80.6.1, §80.6.2; the manager's addendum C to E6b).

A session with the ДДС phone holds more than one call — the 112 call and ДДС calls whose turns
reuse the same pipeline events. The report timeline and transcript therefore carry each row's
`call_id` and the call's party label («Вызов 112: абонент», «Звонок ДДС: Начальник караула ПСЧ»),
a ДДС call's own turns are titled as the ДДС's (not «оператор» / «абонент»), and the timeline is
call-scoped for a trainee exactly as the sockets are: a ДДС call's turns reach the ДДС viewer and
never the operator one.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.realtime.redaction import RealtimeEnvelope, SourceEvent
from app.application.reports.assemble_report import _transcript_visible
from app.application.reports.timeline import call_parties, timeline_entry
from app.application.reports.transcript import turn_calls
from app.application.reports.visibility import report_visibility
from app.domain.common.ids import EventId, SessionId, UserId
from app.domain.dds.call import dds_call_ids
from app.domain.enums import (
    ActorType,
    DDSStageState,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.session.session import SessionParticipant

from tests.unit.domain.session._builders import build_session, build_stage, user

FIXED = datetime.fromisoformat("2026-09-24T10:00:00+00:00")
CALL_112 = uuid.UUID("00000000-0000-4000-8000-000000000112")
HEAD = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
CLAIMANT = uuid.UUID("00000000-0000-4000-8000-0000000000a2")
SESSION = SessionId(uuid.UUID("00000000-0000-4000-8000-0000000005e5"))


def stored(seq_no: int, event_type: EventType, payload: dict[str, Any]) -> SessionEvent:
    return SessionEvent(
        id=EventId(uuid.uuid4()),
        session_id=SESSION,
        seq_no=seq_no,
        event_type=event_type,
        timestamp_utc=FIXED,
        monotonic_offset_ms=seq_no * 100,
        actor_type=ActorType.SIMULATION,
        actor_id=None,
        payload=payload,
    )


def the_log() -> list[SessionEvent]:
    return [
        stored(1, EventType.CALL_RINGING, {"call_id": str(CALL_112)}),
        stored(2, EventType.ASR_FINAL, {"call_id": str(CALL_112), "turn_index": 0}),
        stored(
            3,
            EventType.DDS_CALL_STARTED,
            {"call_id": str(HEAD), "kind": "SERVICE_HEAD", "persona_id": "BRIGADE_101"},
        ),
        stored(4, EventType.ASR_FINAL, {"call_id": str(HEAD), "turn_index": 1}),
        stored(5, EventType.CALLER_TTS_STARTED, {"call_id": str(HEAD), "turn_index": 1}),
        stored(6, EventType.DDS_CALL_STARTED, {"call_id": str(CLAIMANT), "kind": "CLAIMANT"}),
    ]


def test_every_call_gets_its_party_label() -> None:
    parties = call_parties(the_log(), {"BRIGADE_101": "Начальник караула ПСЧ"})
    assert parties == {
        str(CALL_112): "Вызов 112: абонент",
        str(HEAD): "Звонок ДДС: Начальник караула ПСЧ",
        str(CLAIMANT): "Звонок ДДС: заявитель",
    }
    # Without the persona's title the kind names the party.
    assert call_parties(the_log())[str(HEAD)] == "Звонок ДДС: старший службы"


def _envelope(event_type: EventType, call_id: uuid.UUID) -> RealtimeEnvelope:
    return RealtimeEnvelope(
        seq_no=5,
        event_type=event_type,
        timestamp_utc=FIXED,
        monotonic_offset_ms=500,
        payload={"call_id": str(call_id), "turn_index": 1},
        actor_type=ActorType.SIMULATION,
    )


def test_a_dds_calls_turns_are_titled_as_the_dds_and_labelled_with_the_call() -> None:
    log = the_log()
    parties = call_parties(log, {"BRIGADE_101": "Начальник караула ПСЧ"})
    ids = dds_call_ids(log)
    head = timeline_entry(
        _envelope(EventType.CALLER_TTS_STARTED, HEAD),
        actor_id=None,
        parties=parties,
        dds_call_ids=ids,
    )
    assert head.call_id == HEAD
    assert head.call_party_ru == "Звонок ДДС: Начальник караула ПСЧ"
    assert head.summary_ru == "Собеседник начал говорить — реплика: 1"
    caller = timeline_entry(
        _envelope(EventType.CALLER_TTS_STARTED, CALL_112),
        actor_id=None,
        parties=parties,
        dds_call_ids=ids,
    )
    assert caller.call_party_ru == "Вызов 112: абонент"
    assert caller.summary_ru == "Абонент начал говорить — реплика: 1"


def _viewer(name: str, role: UserRole = UserRole.TRAINEE) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=UserId(user(name)), username=name, display_name_ru=name, user_role=role
    )


def _session() -> Any:
    return build_session(
        session_mode=SessionMode.MULTI_TRAINEE,
        state=SessionState.COMPLETED,
        stages=(
            build_stage(
                order_index=0,
                role_type=RoleType.OPERATOR_112,
                state=Operator112StageState.STAGE_COMPLETED,
                started_at_offset_ms=0,
            ),
            build_stage(order_index=1, role_type=RoleType.DDS, state=DDSStageState.CLOSED),
        ),
        participants=(
            SessionParticipant(
                user_id=UserId(user("op")), assigned_role_type=RoleType.OPERATOR_112
            ),
            SessionParticipant(user_id=UserId(user("dds")), assigned_role_type=RoleType.DDS),
        ),
    )


def _source(event_type: EventType, call_id: uuid.UUID) -> SourceEvent:
    return SourceEvent(
        seq_no=9,
        event_type=event_type,
        timestamp_utc=FIXED,
        monotonic_offset_ms=0,
        actor_type=ActorType.SIMULATION,
        payload={"call_id": str(call_id), "turn_index": 1, "at_offset_ms": 0},
    )


def test_the_report_timeline_is_call_scoped_for_a_trainee() -> None:
    """A ДДС call's turn reaches the ДДС viewer's report and never the operator viewer's."""
    session = _session()
    ids = dds_call_ids(the_log())
    operator = report_visibility(session, _viewer("op"), released=True)
    dds = report_visibility(session, _viewer("dds"), released=True)
    instructor = report_visibility(session, _viewer("i", UserRole.INSTRUCTOR), released=True)
    head_turn = _source(EventType.CALLER_TTS_STARTED, HEAD)
    call_112_turn = _source(EventType.CALLER_TTS_STARTED, CALL_112)
    assert operator.timeline_entry(head_turn, dds_call_ids=ids) is None
    assert dds.timeline_entry(head_turn, dds_call_ids=ids) is not None
    assert operator.timeline_entry(call_112_turn, dds_call_ids=ids) is not None
    assert dds.timeline_entry(call_112_turn, dds_call_ids=ids) is None
    assert instructor.timeline_entry(head_turn, dds_call_ids=ids) is not None


def test_transcript_rows_follow_their_call() -> None:
    log = the_log()
    calls = turn_calls(log)
    assert calls == {0: str(CALL_112), 1: str(HEAD)}
    ids = dds_call_ids(log)
    session = _session()
    operator = report_visibility(session, _viewer("op"), released=True)
    dds = report_visibility(session, _viewer("dds"), released=True)
    assert _transcript_visible(operator, 0, calls, ids) is True
    assert _transcript_visible(operator, 1, calls, ids) is False
    assert _transcript_visible(dds, 1, calls, ids) is True
    assert _transcript_visible(dds, 0, calls, ids) is False
