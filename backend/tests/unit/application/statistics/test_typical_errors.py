"""`getTypicalErrors` (I7 E54, G11) — without a database.

* INSTRUCTOR / ADMIN only — a TRAINEE is refused;
* an unknown `trainee_id` / `group_id` is `404`, same as `getTraineeStatistics`;
* an INSTRUCTOR's scope is narrowed to sessions of lessons *they* created; an ADMIN's is not;
* `for_lesson` (the lesson report's own table) is one lesson's sessions, no ownership filter;
* the view's `session_count` / `share_percent` are derived from the scope size, never re-summed
  per row — a scope of zero sessions answers an empty `rows`, never a division by zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.statistics.ports import StatisticsFilter, TraineeAccount, TypicalErrorRow
from app.application.statistics.trainee_statistics import StatisticsSubjectNotFoundError
from app.application.statistics.typical_errors import GetTypicalErrors
from app.domain.common.ids import LessonId, SessionId, TraineeGroupId, UserId
from app.domain.enums import ScoringCategory

TRAINEE1 = UserId(UUID(int=1))
TRAINEE2 = UserId(UUID(int=2))
INSTRUCTOR1_ID = UserId(UUID(int=10))
INSTRUCTOR2_ID = UserId(UUID(int=11))
ADMIN_ID = UserId(UUID(int=20))
LESSON1 = LessonId(UUID(int=100))
SESSION_A = SessionId(UUID(int=200))
SESSION_B = SessionId(UUID(int=201))


def _user(user_id: UserId, role: UserRole) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id, username=str(user_id), display_name_ru="x", user_role=role
    )


INSTRUCTOR1 = _user(INSTRUCTOR1_ID, UserRole.INSTRUCTOR)
INSTRUCTOR2 = _user(INSTRUCTOR2_ID, UserRole.INSTRUCTOR)
ADMIN = _user(ADMIN_ID, UserRole.ADMIN)
TRAINEE = _user(TRAINEE1, UserRole.TRAINEE)


class FakeReader:
    """A minimal `StatisticsReader`: `INSTRUCTOR1_ID` owns `LESSON1`'s two sessions."""

    def __init__(self) -> None:
        self.trainee_accounts = {
            TRAINEE1: TraineeAccount(TRAINEE1, "Первый"),
            TRAINEE2: TraineeAccount(TRAINEE2, "Второй"),
        }
        self.rows_by_session: dict[frozenset, tuple[TypicalErrorRow, ...]] = {}

    async def trainees(self, query: StatisticsFilter) -> tuple[TraineeAccount, ...]:
        return tuple(self.trainee_accounts.values())

    async def accounts(self, user_ids: Sequence[UserId]) -> tuple[TraineeAccount, ...]:
        return tuple(self.trainee_accounts[u] for u in user_ids if u in self.trainee_accounts)

    async def group_exists(self, group_id: TraineeGroupId) -> bool:
        return False

    async def scored_sessions(self, user_ids: Sequence[UserId], **_: object) -> tuple:  # type: ignore[type-arg]
        return ()

    async def scoped_session_ids(
        self,
        *,
        user_ids: Sequence[UserId] | None = None,
        lesson_id: LessonId | None = None,
        owner_id: UserId | None = None,
        from_utc: datetime | None = None,
        to_utc: datetime | None = None,
    ) -> tuple[SessionId, ...]:
        if lesson_id is not None:
            return (SESSION_A, SESSION_B) if lesson_id == LESSON1 else ()
        if owner_id is not None:
            return (SESSION_A, SESSION_B) if owner_id == INSTRUCTOR1_ID else ()
        return (SESSION_A, SESSION_B)

    async def typical_errors(
        self, session_ids: Sequence[SessionId], *, limit: int = 10
    ) -> tuple[TypicalErrorRow, ...]:
        if not session_ids:
            return ()
        return (
            TypicalErrorRow(
                rule_id="r1",
                category=ScoringCategory.CARD_QUALITY.value,
                name_ru="Rule one",
                failed_session_count=len(session_ids),
            ),
        )[:limit]


async def test_a_trainee_is_refused() -> None:
    with pytest.raises(ForbiddenForRoleError):
        await GetTypicalErrors(FakeReader())(StatisticsFilter(), TRAINEE)


async def test_an_unknown_trainee_id_is_404() -> None:
    reader = FakeReader()
    reader.trainee_accounts = {}
    with pytest.raises(StatisticsSubjectNotFoundError):
        await GetTypicalErrors(reader)(StatisticsFilter(trainee_id=uuid4()), INSTRUCTOR1)  # type: ignore[arg-type]


async def test_an_unknown_group_id_is_404() -> None:
    with pytest.raises(StatisticsSubjectNotFoundError):
        await GetTypicalErrors(FakeReader())(
            StatisticsFilter(group_id=TraineeGroupId(uuid4())), INSTRUCTOR1
        )


async def test_an_instructor_sees_only_their_own_lessons() -> None:
    view = await GetTypicalErrors(FakeReader())(StatisticsFilter(), INSTRUCTOR1)
    assert len(view.rows) == 1
    assert view.rows[0].session_count == 2
    assert view.rows[0].failed_session_count == 2
    assert view.rows[0].share_percent == 100.0


async def test_a_different_instructor_sees_no_rows() -> None:
    view = await GetTypicalErrors(FakeReader())(StatisticsFilter(), INSTRUCTOR2)
    assert view.rows == ()


async def test_an_admin_is_not_scoped_to_any_owner() -> None:
    view = await GetTypicalErrors(FakeReader())(StatisticsFilter(), ADMIN)
    assert len(view.rows) == 1
    assert view.rows[0].session_count == 2


async def test_for_lesson_ignores_ownership() -> None:
    """The lesson report's own table: one lesson's sessions, no `owner_id` filter — whoever may
    open the lesson report already decided (`GetLessonReport`'s own visibility)."""
    view = await GetTypicalErrors(FakeReader()).for_lesson(LESSON1)
    assert len(view.rows) == 1
    assert view.rows[0].session_count == 2


async def test_for_lesson_with_no_sessions_is_empty_not_a_division_by_zero() -> None:
    view = await GetTypicalErrors(FakeReader()).for_lesson(LessonId(uuid4()))
    assert view.rows == ()
