"""§40.1's effective realtime role, and the fold that re-derives it (E7-C).

The three bullets of §40.1, plus the property that makes the third one cheap: a
`FULL_CYCLE_SINGLE_TRAINEE` socket's role moves when the stage events it is *already being pushed*
say so, with no query per event.
"""

from __future__ import annotations

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.realtime.effective_role import INSTRUCTOR, connection_of, fold_role
from app.application.sessions.authorisation import ParticipantNotAssignedError
from app.domain.common.ids import UserId
from app.domain.enums import (
    DDSStageState,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.events.types import EventType
from app.domain.session.session import SessionParticipant

from tests.unit.domain.session._builders import build_session, build_stage, user


def _account(name: str, role: UserRole) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=UserId(user(name)), username=name, display_name_ru=name, user_role=role
    )


def _two_stage_session(*, session_mode: SessionMode, participants: tuple[SessionParticipant, ...]):
    """A 112 → DDS session whose first stage is running, the demo `role_chain`."""
    return build_session(
        session_mode=session_mode,
        state=SessionState.ACTIVE,
        stages=(
            build_stage(
                order_index=0,
                role_type=RoleType.OPERATOR_112,
                state=Operator112StageState.INTERVIEW,
                started_at_offset_ms=0,
            ),
            build_stage(order_index=1, role_type=RoleType.DDS, state=DDSStageState.RECEIVED),
        ),
        participants=participants,
    )


def test_an_instructor_account_is_the_instructor_console() -> None:
    """§40.1 bullet 3: "`INSTRUCTOR` or `ADMIN` → `INSTRUCTOR` (the instructor console, not a
    `RoleType`)" — including for an instructor who is not a participant at all."""
    session = _two_stage_session(session_mode=SessionMode.MULTI_TRAINEE, participants=())
    connection = connection_of(session, _account("instructor1", UserRole.INSTRUCTOR))
    assert connection.role == INSTRUCTOR
    assert connection.dynamic is False


def test_an_admin_account_is_also_the_instructor_console() -> None:
    session = _two_stage_session(session_mode=SessionMode.MULTI_TRAINEE, participants=())
    assert connection_of(session, _account("admin1", UserRole.ADMIN)).role == INSTRUCTOR


@pytest.mark.parametrize("assigned", [RoleType.OPERATOR_112, RoleType.DDS])
def test_a_participant_assigned_to_a_stage_is_fixed_at_that_role(assigned: RoleType) -> None:
    """§40.1 bullet 1 — and it does not move, whatever the session does afterwards."""
    participants = (SessionParticipant(user_id=UserId(user("t1")), assigned_role_type=assigned),)
    session = _two_stage_session(session_mode=SessionMode.MULTI_TRAINEE, participants=participants)
    connection = connection_of(session, _account("t1", UserRole.TRAINEE))
    assert connection.role is assigned
    assert connection.dynamic is False

    moved = fold_role(connection, EventType.ROLE_STAGE_STARTED, {"role_type": "DDS"})
    assert moved.role is assigned, "a fixed-role connection never renegotiates (§40.1)"


def test_a_full_cycle_trainee_starts_at_the_active_stage_and_follows_it() -> None:
    """§40.1 bullet 2: the role is the currently active stage's, "re-derived on every push"."""
    participants = (SessionParticipant(user_id=UserId(user("t1")), assigned_role_type=None),)
    session = _two_stage_session(
        session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE, participants=participants
    )
    connection = connection_of(session, _account("t1", UserRole.TRAINEE))
    assert connection.role is RoleType.OPERATOR_112
    assert connection.dynamic is True

    # The transition *starting* does not move the role: the trainee is still on the stage they
    # just finished until the transition completes.
    during = fold_role(
        connection, EventType.ROLE_TRANSITION_STARTED, {"to_role_type": RoleType.DDS.value}
    )
    assert during.role is RoleType.OPERATOR_112

    after = fold_role(
        during, EventType.ROLE_TRANSITION_COMPLETED, {"to_role_type": RoleType.DDS.value}
    )
    assert after.role is RoleType.DDS

    # `ROLE_STAGE_STARTED` says the same thing, whichever the runner emits first.
    assert (
        fold_role(connection, EventType.ROLE_STAGE_STARTED, {"role_type": RoleType.DDS.value}).role
        is RoleType.DDS
    )


def test_an_unrelated_event_never_moves_the_role() -> None:
    participants = (SessionParticipant(user_id=UserId(user("t1")), assigned_role_type=None),)
    session = _two_stage_session(
        session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE, participants=participants
    )
    connection = connection_of(session, _account("t1", UserRole.TRAINEE))
    unchanged = fold_role(connection, EventType.CARD_FIELD_CHANGED, {"field_path": "address"})
    assert unchanged is connection


def test_a_stranger_has_no_effective_role() -> None:
    """§40.1's third gate, as an exception the socket turns into close `4403`."""
    session = _two_stage_session(session_mode=SessionMode.MULTI_TRAINEE, participants=())
    with pytest.raises(ParticipantNotAssignedError):
        connection_of(session, _account("t9", UserRole.TRAINEE))
