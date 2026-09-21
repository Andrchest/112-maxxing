"""`createVoiceToken` — who may have a token, and for which room (D9, `openapi.yaml`).

Pure unit tests over a stub Unit of Work: the rule under test is "only a participant of the ACTIVE
`OPERATOR_112` stage whose call is `RINGING` or `CONNECTED`", which is a decision about an
aggregate and a log and needs neither PostgreSQL nor a real minter. The JWT itself is the adapter's
business and has its own test
(`backend/tests/unit/infrastructure/transport/test_livekit_token_service.py`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import (
    ActionNotAvailableError,
    SessionNotActiveError,
)
from app.application.ports.user_repository import UserRole
from app.application.sessions.authorisation import ParticipantNotAssignedError
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.application.testing.fakes import StubVoiceTokenService
from app.application.voice_token.create_voice_token import CreateVoiceToken
from app.domain.common.ids import (
    EventId,
    IncidentId,
    RoleStageId,
    ScenarioVersionId,
    SessionId,
    UserId,
)
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
from app.domain.session.session import Incident, RoleStage, SessionParticipant, SimulationSession

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
OPERATOR = UserId(uuid4())
OTHER = UserId(uuid4())
SESSION = SessionId(uuid4())
CALL_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
ROOM = f"session-{SESSION}"


# -- the stub Unit of Work -------------------------------------------------------------------------


class StubSessions:
    def __init__(self, session: SimulationSession | None) -> None:
        self._session = session

    async def get(self, session_id: SessionId) -> SimulationSession | None:
        return self._session


class StubEvents:
    def __init__(self, events: Sequence[SessionEvent]) -> None:
        self._events = list(events)

    async def read(self, session_id: SessionId) -> list[SessionEvent]:
        return list(self._events)


class StubUnitOfWork:
    """Only the three things `CreateVoiceToken` touches: `sessions.get`, `events.read`, `commit`."""

    def __init__(self, session: SimulationSession | None, events: Sequence[SessionEvent]) -> None:
        self.sessions = StubSessions(session)
        self.events = StubEvents(events)
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def unit_of_work_factory(
    session: SimulationSession | None, events: Sequence[SessionEvent] = ()
) -> Any:
    """A `UnitOfWorkFactory` over `StubUnitOfWork`."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[StubUnitOfWork]:
        yield StubUnitOfWork(session, events)

    return factory


# -- the fixtures the rule is about ----------------------------------------------------------------


def user(user_id: UserId = OPERATOR, role: UserRole = UserRole.TRAINEE) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        username="trainee1",
        display_name_ru="Стажёр",
        user_role=role,
        is_active=True,
    )


def session(
    *,
    state: SessionState = SessionState.ACTIVE,
    role_type: RoleType = RoleType.OPERATOR_112,
    stage_participant: UserId | None = OPERATOR,
    participants: tuple[UserId, ...] = (OPERATOR,),
) -> SimulationSession:
    incident_id = IncidentId(uuid4())
    return SimulationSession(
        id=SESSION,
        scenario_version_id=ScenarioVersionId(uuid4()),
        session_mode=SessionMode.MULTI_TRAINEE,
        state=state,
        session_seed="seed",
        created_by_user_id=UserId(uuid4()),
        started_at=NOW,
        incident=Incident(
            incident_id=incident_id,
            session_id=SESSION,
            scenario_version_id=ScenarioVersionId(uuid4()),
        ),
        stages=(
            RoleStage(
                role_stage_id=RoleStageId(uuid4()),
                session_id=SESSION,
                incident_id=incident_id,
                role_type=role_type,
                order_index=0,
                state=(
                    Operator112StageState.RINGING
                    if role_type is RoleType.OPERATOR_112
                    else DDSStageState.RECEIVED
                ),
                participant_user_id=stage_participant,
            ),
        ),
        participants=tuple(
            SessionParticipant(user_id=member, assigned_role_type=role_type)
            for member in participants
        ),
    )


def event(event_type: EventType, seq_no: int, **payload: object) -> SessionEvent:
    return SessionEvent(
        id=EventId(uuid4()),
        session_id=SESSION,
        seq_no=seq_no,
        event_type=event_type,
        actor_type=ActorType.SIMULATION,
        timestamp_utc=NOW,
        monotonic_offset_ms=seq_no * 1000,
        payload=dict(payload),
    )


def ringing_log() -> list[SessionEvent]:
    return [
        event(
            EventType.CALL_RINGING,
            1,
            call_id=str(CALL_ID),
            room_name=ROOM,
            caller_display_ru="Соседка",
            at_offset_ms=1000,
        )
    ]


def use_case(
    stub_session: SimulationSession | None, events: Sequence[SessionEvent] = ()
) -> tuple[CreateVoiceToken, StubVoiceTokenService]:
    tokens = StubVoiceTokenService()
    return CreateVoiceToken(unit_of_work_factory(stub_session, events), tokens), tokens


# -- the happy path --------------------------------------------------------------------------------


async def test_a_ringing_call_mints_a_token_for_this_room_and_this_user() -> None:
    create, tokens = use_case(session(), ringing_log())

    minted = await create(SESSION, user())

    assert minted.room_name == ROOM
    assert minted.participant_identity == str(OPERATOR)
    assert tokens.calls == [(ROOM, str(OPERATOR))]


async def test_a_connected_call_also_mints() -> None:
    log = [*ringing_log(), event(EventType.CALL_ANSWERED, 2, call_id=str(CALL_ID))]
    create, _tokens = use_case(session(), log)

    minted = await create(SESSION, user())

    assert minted.room_name == ROOM


# -- the refusals, each with the code `openapi.yaml` documents -------------------------------------


async def test_an_unknown_session_is_not_found() -> None:
    create, tokens = use_case(None)

    with pytest.raises(SessionNotFoundError):
        await create(SESSION, user())
    assert tokens.calls == []


@pytest.mark.parametrize(
    "state", [SessionState.READY, SessionState.COMPLETED, SessionState.ABORTED]
)
async def test_a_session_that_is_not_active_is_refused(state: SessionState) -> None:
    create, tokens = use_case(session(state=state), ringing_log())

    with pytest.raises(SessionNotActiveError) as raised:
        await create(SESSION, user())
    assert raised.value.code == "SESSION_NOT_ACTIVE"
    assert tokens.calls == []


async def test_a_non_participant_is_refused() -> None:
    create, tokens = use_case(session(participants=(OPERATOR,)), ringing_log())

    with pytest.raises(ParticipantNotAssignedError) as raised:
        await create(SESSION, user(user_id=OTHER))
    assert raised.value.code == "PARTICIPANT_NOT_ASSIGNED"
    assert tokens.calls == []


async def test_a_participant_who_is_not_the_operator_of_the_active_stage_is_refused() -> None:
    """Assigned to the session, but somebody else is playing the 112 stage."""
    create, tokens = use_case(
        session(stage_participant=OTHER, participants=(OPERATOR, OTHER)), ringing_log()
    )

    with pytest.raises(ForbiddenForRoleError) as raised:
        await create(SESSION, user())
    assert raised.value.code == "FORBIDDEN_FOR_ROLE"
    assert tokens.calls == []


async def test_a_dds_active_stage_is_refused() -> None:
    create, tokens = use_case(session(role_type=RoleType.DDS), ringing_log())

    with pytest.raises(ForbiddenForRoleError):
        await create(SESSION, user())
    assert tokens.calls == []


async def test_no_call_at_all_is_action_not_available() -> None:
    create, tokens = use_case(session(), [])

    with pytest.raises(ActionNotAvailableError) as raised:
        await create(SESSION, user())
    assert raised.value.code == "ACTION_NOT_AVAILABLE"
    assert tokens.calls == []


async def test_an_ended_call_is_action_not_available() -> None:
    """A finished call must not be re-enterable: the room is gone and the log says so."""
    log = [
        *ringing_log(),
        event(EventType.CALL_ANSWERED, 2, call_id=str(CALL_ID)),
        event(EventType.CALL_ENDED, 3, call_id=str(CALL_ID)),
    ]
    create, tokens = use_case(session(), log)

    with pytest.raises(ActionNotAvailableError):
        await create(SESSION, user())
    assert tokens.calls == []
