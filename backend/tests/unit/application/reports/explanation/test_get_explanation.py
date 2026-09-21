"""`GetExplanation` (`getReportExplanation`, SPEC §2, §29; DO item 2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.report_explanation_repository import StoredReportExplanation
from app.application.ports.user_repository import UserRole
from app.application.reports.explanation.get_explanation import (
    ExplanationNotFoundError,
    GetExplanation,
)
from app.application.reports.visibility import ReportNotReleasedError
from app.application.sessions.authorisation import ParticipantNotAssignedError
from app.domain.enums import SessionMode, SessionState

from tests.unit.domain.session._builders import (
    SESSION_ID,
    build_session,
    build_stage,
    det_uuid,
    scenario_version,
    user,
)

from ._support import FakeUnitOfWorkFactory

TRAINEE_ID = user("operator")
INSTRUCTOR_ID = user("instructor")
STRANGER_ID = user("stranger")

TRAINEE = AuthenticatedUser(
    user_id=TRAINEE_ID, username="trainee1", display_name_ru="Стажёр", user_role=UserRole.TRAINEE
)
STRANGER = AuthenticatedUser(
    user_id=STRANGER_ID, username="stranger", display_name_ru="Чужой", user_role=UserRole.TRAINEE
)
INSTRUCTOR = AuthenticatedUser(
    user_id=INSTRUCTOR_ID,
    username="instructor1",
    display_name_ru="Инструктор",
    user_role=UserRole.INSTRUCTOR,
)


def _stage():
    from app.domain.enums import Operator112StageState, RoleType

    return build_stage(
        order_index=0,
        role_type=RoleType.OPERATOR_112,
        state=Operator112StageState.STAGE_COMPLETED,
        participant_user_id=TRAINEE_ID,
        started_at_offset_ms=0,
        completed_at_offset_ms=100_000,
    )


def _session(*, session_mode=SessionMode.SINGLE_ROLE, state=SessionState.COMPLETED):
    from app.domain.session.session import SessionParticipant

    return build_session(
        session_mode=session_mode,
        state=state,
        stages=(_stage(),),
        participants=(SessionParticipant(user_id=TRAINEE_ID),),
    )


def _factory(*, session_mode=SessionMode.SINGLE_ROLE, released=False):
    version = scenario_version()
    session = _session(session_mode=session_mode)
    factory = FakeUnitOfWorkFactory(sessions={SESSION_ID: session}, scenario_version=version)
    if released:
        factory.session_repo.release(SESSION_ID, released_by_user_id=INSTRUCTOR_ID)
    return factory


def _explanation(*, checksum: str = "abc123") -> StoredReportExplanation:
    return StoredReportExplanation(
        id=det_uuid("explanation-row"),
        session_id=SESSION_ID,
        audience="TRAINEE",
        text_ru="Готовый разбор.",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        llm_provider="fake",
        llm_model="fake-llm",
        score_report_checksum=checksum,
    )


async def test_returns_the_stored_explanation() -> None:
    factory = _factory()
    await factory.explanations.upsert(_explanation())
    use_case = GetExplanation(factory)

    stored = await use_case(SESSION_ID, TRAINEE, audience="TRAINEE")

    assert stored.text_ru == "Готовый разбор."


async def test_404_when_nothing_was_generated() -> None:
    factory = _factory()
    use_case = GetExplanation(factory)

    with pytest.raises(ExplanationNotFoundError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE")


async def test_a_stranger_is_refused() -> None:
    factory = _factory()
    await factory.explanations.upsert(_explanation())
    use_case = GetExplanation(factory)

    with pytest.raises(ParticipantNotAssignedError):
        await use_case(SESSION_ID, STRANGER, audience="TRAINEE")


async def test_a_trainee_is_refused_before_release_when_the_mode_requires_one() -> None:
    factory = _factory(session_mode=SessionMode.MULTI_TRAINEE, released=False)
    await factory.explanations.upsert(_explanation())
    use_case = GetExplanation(factory)

    with pytest.raises(ReportNotReleasedError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE")


async def test_a_stale_explanation_is_still_returned_with_its_own_checksum() -> None:
    """DO item 2: never silently regenerate; the client compares checksums itself."""
    factory = _factory()
    await factory.explanations.upsert(_explanation(checksum="stale-checksum"))
    use_case = GetExplanation(factory)

    stored = await use_case(SESSION_ID, TRAINEE, audience="TRAINEE")

    assert stored.score_report_checksum == "stale-checksum"


async def test_an_instructor_may_read_regardless_of_release() -> None:
    factory = _factory(session_mode=SessionMode.MULTI_TRAINEE, released=False)
    await factory.explanations.upsert(_explanation())
    use_case = GetExplanation(factory)

    stored = await use_case(SESSION_ID, INSTRUCTOR, audience="TRAINEE")
    assert stored.text_ru == "Готовый разбор."
