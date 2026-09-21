"""The one rule that decides who sees which section of a report (E16 R3, D3, D6, D11).

A table test, because the rule *is* a table: seven viewers against one two-stage session, each
row naming exactly what that viewer may see. The point of writing it this way is that adding a
section, or a mode, means adding a column or a row — never a second copy of the rule somewhere
else in the codebase.

The release gate is tested against both halves of D6's §10.10 table: the two modes whose
`report_visible_to_trainee_before_release` is `true` (`SINGLE_ROLE`,
`FULL_CYCLE_SINGLE_TRAINEE`) and the two whose is `false` (`MULTI_TRAINEE`, `ASSESSMENT`).
"""

from __future__ import annotations

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.realtime.redaction import SourceEvent
from app.application.reports.visibility import (
    ReportNotReleasedError,
    report_visibility,
    viewer_roles_of,
)
from app.domain.common.ids import UserId
from app.domain.enums import (
    ActorType,
    DDSStageState,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.events.types import EventType
from app.domain.session.session import SessionParticipant

from tests.unit.domain.session._builders import build_session, build_stage, user

FIXED_TIME = "2026-09-22T10:00:00+00:00"


def _account(name: str, role: UserRole) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=UserId(user(name)), username=name, display_name_ru=name, user_role=role
    )


def _session(*, session_mode: SessionMode, participants: tuple[SessionParticipant, ...]):
    """A completed 112 -> DDS session, the demo `role_chain`."""
    return build_session(
        session_mode=session_mode,
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
        participants=participants,
    )


def _event(event_type: EventType, **payload: object) -> SourceEvent:
    from datetime import datetime

    return SourceEvent(
        seq_no=1,
        event_type=event_type,
        timestamp_utc=datetime.fromisoformat(FIXED_TIME),
        monotonic_offset_ms=0,
        actor_type=ActorType.TRAINEE,
        payload=payload,
    )


_OPERATOR = SessionParticipant(user_id=UserId(user("op")), assigned_role_type=RoleType.OPERATOR_112)
_DDS = SessionParticipant(user_id=UserId(user("dds")), assigned_role_type=RoleType.DDS)
_BOTH = SessionParticipant(user_id=UserId(user("both")), assigned_role_type=None)


# ---------------------------------------------------------------------------------------------
# viewer_roles: which roles does a viewer speak for?
# ---------------------------------------------------------------------------------------------


def test_an_assigned_participant_covers_exactly_their_role() -> None:
    session = _session(session_mode=SessionMode.MULTI_TRAINEE, participants=(_OPERATOR, _DDS))
    assert viewer_roles_of(session, _account("op", UserRole.TRAINEE)) == {RoleType.OPERATOR_112}
    assert viewer_roles_of(session, _account("dds", UserRole.TRAINEE)) == {RoleType.DDS}


def test_an_unassigned_participant_covers_the_whole_chain() -> None:
    """§10.10's `ALL_STAGES_ONE_PARTICIPANT`: the full-cycle trainee played both stages, so their
    own report is the union — not either role alone, which would hide half their own session."""
    session = _session(session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE, participants=(_BOTH,))
    assert viewer_roles_of(session, _account("both", UserRole.TRAINEE)) == {
        RoleType.OPERATOR_112,
        RoleType.DDS,
    }


def test_a_non_participant_covers_nothing() -> None:
    session = _session(session_mode=SessionMode.MULTI_TRAINEE, participants=(_OPERATOR,))
    assert viewer_roles_of(session, _account("stranger", UserRole.TRAINEE)) == frozenset()


# ---------------------------------------------------------------------------------------------
# The section table (R3)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "role", "participants", "operator_sections", "handoff", "dds_sections"),
    [
        # instructor: everything, always
        ("instructor1", UserRole.INSTRUCTOR, (_OPERATOR, _DDS), True, True, True),
        ("admin1", UserRole.ADMIN, (_OPERATOR, _DDS), True, True, True),
        # operator-only trainee: their own transcript/card/diff and the handoff they created,
        # but not what the DDS then did with it
        ("op", UserRole.TRAINEE, (_OPERATOR, _DDS), True, True, False),
        # DDS-only trainee: the handoff they received and their own decisions, never the call
        ("dds", UserRole.TRAINEE, (_OPERATOR, _DDS), False, True, True),
    ],
    ids=["instructor", "admin", "operator-only-trainee", "dds-only-trainee"],
)
def test_the_section_table(
    who: str,
    role: UserRole,
    participants: tuple[SessionParticipant, ...],
    operator_sections: bool,
    handoff: bool,
    dds_sections: bool,
) -> None:
    session = _session(session_mode=SessionMode.MULTI_TRAINEE, participants=participants)
    visibility = report_visibility(session, _account(who, role), released=True)
    assert visibility.shows_operator_sections is operator_sections
    assert visibility.shows_handoff is handoff
    assert visibility.shows_dds_sections is dds_sections


def test_a_full_cycle_trainee_sees_both_halves_of_their_own_session() -> None:
    session = _session(session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE, participants=(_BOTH,))
    visibility = report_visibility(session, _account("both", UserRole.TRAINEE), released=False)
    assert visibility.shows_operator_sections is True
    assert visibility.shows_handoff is True
    assert visibility.shows_dds_sections is True
    assert visibility.role_chain == (RoleType.OPERATOR_112, RoleType.DDS)


def test_a_non_participant_sees_no_section() -> None:
    """Defence in depth: the use case refuses a stranger before this point, but if it ever did
    not, an empty `viewer_roles` must open nothing rather than everything."""
    session = _session(session_mode=SessionMode.MULTI_TRAINEE, participants=(_OPERATOR,))
    visibility = report_visibility(session, _account("stranger", UserRole.TRAINEE), released=True)
    assert visibility.shows_operator_sections is False
    assert visibility.shows_handoff is False
    assert visibility.shows_dds_sections is False


# ---------------------------------------------------------------------------------------------
# The release gate (D6 §10.10)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "session_mode", [SessionMode.MULTI_TRAINEE, SessionMode.ASSESSMENT], ids=lambda m: m.value
)
def test_a_gated_mode_refuses_a_trainee_before_release(session_mode: SessionMode) -> None:
    session = _session(session_mode=session_mode, participants=(_OPERATOR,))
    with pytest.raises(ReportNotReleasedError) as excinfo:
        report_visibility(session, _account("op", UserRole.TRAINEE), released=False)
    assert excinfo.value.code == "REPORT_NOT_RELEASED"


@pytest.mark.parametrize(
    "session_mode", [SessionMode.MULTI_TRAINEE, SessionMode.ASSESSMENT], ids=lambda m: m.value
)
def test_a_gated_mode_admits_a_trainee_after_release(session_mode: SessionMode) -> None:
    session = _session(session_mode=session_mode, participants=(_OPERATOR,))
    visibility = report_visibility(session, _account("op", UserRole.TRAINEE), released=True)
    assert visibility.released is True
    assert visibility.shows_operator_sections is True


@pytest.mark.parametrize(
    "session_mode",
    [SessionMode.SINGLE_ROLE, SessionMode.FULL_CYCLE_SINGLE_TRAINEE],
    ids=lambda m: m.value,
)
def test_an_ungated_mode_needs_no_release(session_mode: SessionMode) -> None:
    session = _session(session_mode=session_mode, participants=(_OPERATOR,))
    visibility = report_visibility(session, _account("op", UserRole.TRAINEE), released=False)
    assert visibility.released is False
    assert visibility.shows_operator_sections is True


@pytest.mark.parametrize(
    "session_mode", [SessionMode.MULTI_TRAINEE, SessionMode.ASSESSMENT], ids=lambda m: m.value
)
def test_an_instructor_never_waits_for_a_release(session_mode: SessionMode) -> None:
    session = _session(session_mode=session_mode, participants=(_OPERATOR,))
    visibility = report_visibility(
        session, _account("instructor1", UserRole.INSTRUCTOR), released=False
    )
    assert visibility.is_instructor is True


# ---------------------------------------------------------------------------------------------
# The timeline rule
# ---------------------------------------------------------------------------------------------


def test_the_instructor_timeline_is_unredacted() -> None:
    session = _session(session_mode=SessionMode.MULTI_TRAINEE, participants=())
    visibility = report_visibility(
        session, _account("instructor1", UserRole.INSTRUCTOR), released=False
    )
    entry = visibility.timeline_entry(_event(EventType.WORLD_TRUTH_MUTATED, revision=1))
    assert entry is not None
    assert entry.redacted_keys == ()


def test_a_trainee_never_sees_world_truth_in_the_timeline() -> None:
    """D3, through the *existing* whitelist: `WORLD_TRUTH_MUTATED` is in no trainee role's
    `visible_event_types`, so no role of theirs lets it through and the event is absent."""
    session = _session(session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE, participants=(_BOTH,))
    visibility = report_visibility(session, _account("both", UserRole.TRAINEE), released=True)
    assert visibility.timeline_entry(_event(EventType.WORLD_TRUTH_MUTATED, revision=1)) is None


def test_a_full_cycle_trainee_sees_an_event_either_of_their_roles_may_see() -> None:
    """The union R3 asks for: a DDS-only event reaches the trainee who also played DDS."""
    both_session = _session(
        session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE, participants=(_BOTH,)
    )
    both = report_visibility(both_session, _account("both", UserRole.TRAINEE), released=True)
    operator_session = _session(
        session_mode=SessionMode.MULTI_TRAINEE, participants=(_OPERATOR, _DDS)
    )
    operator_only = report_visibility(
        operator_session, _account("op", UserRole.TRAINEE), released=True
    )

    event = _event(EventType.RESOURCE_DISPATCHED, assignment_id=str(user("a")), resource_ids=[])
    assert both.timeline_entry(event) is not None
    assert operator_only.timeline_entry(event) is None


def test_scoring_rule_evaluated_is_visible_to_every_report_viewer() -> None:
    """R3's one addition: the rule evaluations are what the report is *about*, and no live
    `RoleModule` whitelists them because nothing is scored mid-stage."""
    session = _session(session_mode=SessionMode.MULTI_TRAINEE, participants=(_OPERATOR, _DDS))
    for name in ("op", "dds"):
        visibility = report_visibility(session, _account(name, UserRole.TRAINEE), released=True)
        entry = visibility.timeline_entry(
            _event(EventType.SCORING_RULE_EVALUATED, rule_id="r1", points_awarded=5.0)
        )
        assert entry is not None, f"{name} must see the rules they were graded by"
        assert entry.payload["rule_id"] == "r1"


# ---------------------------------------------------------------------------------------------
# Per-rule filtering — and the totals that are *not* filtered
# ---------------------------------------------------------------------------------------------


def test_a_rule_that_always_applies_is_shown_to_everyone() -> None:
    session = _session(session_mode=SessionMode.MULTI_TRAINEE, participants=(_OPERATOR, _DDS))
    visibility = report_visibility(session, _account("dds", UserRole.TRAINEE), released=True)
    assert visibility.shows_rule(()) is True


def test_a_role_scoped_rule_is_shown_only_to_a_viewer_of_that_role() -> None:
    session = _session(session_mode=SessionMode.MULTI_TRAINEE, participants=(_OPERATOR, _DDS))
    dds_view = report_visibility(session, _account("dds", UserRole.TRAINEE), released=True)
    op_view = report_visibility(session, _account("op", UserRole.TRAINEE), released=True)
    assert dds_view.shows_rule((RoleType.OPERATOR_112,)) is False
    assert op_view.shows_rule((RoleType.OPERATOR_112,)) is True


def test_an_instructor_sees_every_rule() -> None:
    session = _session(session_mode=SessionMode.MULTI_TRAINEE, participants=())
    visibility = report_visibility(
        session, _account("instructor1", UserRole.INSTRUCTOR), released=False
    )
    assert visibility.shows_rule((RoleType.DDS,)) is True
