"""`RescoreSession` (`rescoreSession`, SPEC §28, §42 test 9, D11, epic E15-B).

Fakes only, over the real `good_log()` / demo scenario / real `score()` (E15-A is done). The
integration half of INV 9 (through the real HTTP endpoint and PostgreSQL) lives in
`backend/tests/invariants/test_inv_09_rescore_endpoint.py`.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.scoring.rescore_session import ReportNotReadyError, RescoreSession
from app.application.scoring.score_session import score_session
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import UserId
from app.domain.enums import SessionState
from app.domain.scoring.engine import report_checksum

from tests.unit.application.scoring._support import FakeUnitOfWorkFactory
from tests.unit.domain.scoring._event_log_builders import SESSION_ID, good_log

INSTRUCTOR = AuthenticatedUser(
    user_id=UserId(UUID(int=1)),
    username="instructor1",
    display_name_ru="Инструктор",
    user_role=UserRole.INSTRUCTOR,
)
TRAINEE = AuthenticatedUser(
    user_id=UserId(UUID(int=2)),
    username="trainee1",
    display_name_ru="Стажёр",
    user_role=UserRole.TRAINEE,
)


def _rescore(factory: FakeUnitOfWorkFactory) -> RescoreSession:
    return RescoreSession(factory)


async def test_a_trainee_may_not_rescore() -> None:
    factory = FakeUnitOfWorkFactory(SESSION_ID, events=good_log())
    with pytest.raises(ForbiddenForRoleError):
        await _rescore(factory)(SESSION_ID, TRAINEE, persist=False)


async def test_an_unknown_session_is_not_found() -> None:
    factory = FakeUnitOfWorkFactory(SESSION_ID, events=good_log(), session_state=None)
    with pytest.raises(SessionNotFoundError):
        await _rescore(factory)(SESSION_ID, INSTRUCTOR, persist=False)


async def test_a_session_that_has_not_completed_is_not_ready() -> None:
    factory = FakeUnitOfWorkFactory(
        SESSION_ID, events=good_log(), session_state=SessionState.ACTIVE
    )
    with pytest.raises(ReportNotReadyError):
        await _rescore(factory)(SESSION_ID, INSTRUCTOR, persist=False)


async def test_a_never_scored_session_has_a_null_stored_checksum_and_full_differences() -> None:
    factory = FakeUnitOfWorkFactory(SESSION_ID, events=good_log())

    outcome = await _rescore(factory)(SESSION_ID, INSTRUCTOR, persist=False)

    assert outcome.stored_checksum is None
    assert outcome.identical_to_stored is False
    assert outcome.persisted is False
    assert len(outcome.differences) == len(outcome.recomputed.results)
    assert all(difference.stored_points is None for difference in outcome.differences)
    # persist=False: nothing was written.
    async with factory() as uow:
        assert await uow.scores.load_report(SESSION_ID) is None


async def test_persist_false_leaves_the_store_untouched_after_a_prior_score() -> None:
    factory = FakeUnitOfWorkFactory(SESSION_ID, events=good_log())
    async with factory() as uow:
        await score_session(uow, SESSION_ID)
        await uow.commit()

    outcome = await _rescore(factory)(SESSION_ID, INSTRUCTOR, persist=False)

    assert outcome.stored_checksum is not None
    assert outcome.identical_to_stored is True
    assert outcome.recomputed_checksum == outcome.stored_checksum
    assert outcome.differences == ()
    assert outcome.persisted is False


async def test_a_tampered_stored_row_is_reported_as_a_difference() -> None:
    factory = FakeUnitOfWorkFactory(SESSION_ID, events=good_log())
    async with factory() as uow:
        await score_session(uow, SESSION_ID)
        await uow.commit()

    stored = await factory.score_repo.load_report(SESSION_ID)
    assert stored is not None
    tampered_rule = stored[0]
    factory.score_repo.rows[SESSION_ID] = (
        factory.score_repo.rows[SESSION_ID][0],
        (
            tampered_rule.model_copy(update={"points_awarded": tampered_rule.points_awarded + 999}),
            *stored[1:],
        ),
    )

    outcome = await _rescore(factory)(SESSION_ID, INSTRUCTOR, persist=False)

    assert outcome.identical_to_stored is False
    assert outcome.stored_checksum != outcome.recomputed_checksum
    tampered = next(d for d in outcome.differences if d.rule_id == tampered_rule.rule_id)
    assert tampered.stored_points == tampered_rule.points_awarded + 999
    assert tampered.recomputed_points == tampered_rule.points_awarded
    assert outcome.persisted is False


async def test_persist_true_repairs_a_tampered_row() -> None:
    factory = FakeUnitOfWorkFactory(SESSION_ID, events=good_log())
    async with factory() as uow:
        await score_session(uow, SESSION_ID)
        await uow.commit()

    stored = await factory.score_repo.load_report(SESSION_ID)
    assert stored is not None
    tampered_rule = stored[0]
    factory.score_repo.rows[SESSION_ID] = (
        factory.score_repo.rows[SESSION_ID][0],
        (
            tampered_rule.model_copy(update={"points_awarded": 0.0}),
            *stored[1:],
        ),
    )

    outcome = await _rescore(factory)(SESSION_ID, INSTRUCTOR, persist=True)

    assert outcome.persisted is True
    repaired = await factory.score_repo.load_report(SESSION_ID)
    assert repaired is not None
    assert repaired[0].points_awarded == tampered_rule.points_awarded

    # A second rescore now finds the repaired row identical.
    again = await _rescore(factory)(SESSION_ID, INSTRUCTOR, persist=False)
    assert again.identical_to_stored is True


async def test_checksum_matches_report_checksum_of_the_recomputed_report() -> None:
    factory = FakeUnitOfWorkFactory(SESSION_ID, events=good_log())
    outcome = await _rescore(factory)(SESSION_ID, INSTRUCTOR, persist=False)
    assert outcome.recomputed_checksum == report_checksum(outcome.recomputed)
