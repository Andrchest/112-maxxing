"""`getTypicalErrors` — «Типичные ошибки группы», G11 (ТЗ ¶233 REQ-2195, I7 E54, manager decision
`reports/i7/E42-gaps.md` §2 item 13).

**Deterministic, no ML.** ТЗ ¶233 asks for "аналитические рекомендации… (инсайты ИИ по типичным
ошибкам группы)"; the manager's reading (item 13) is the ML half is excluded and the deterministic
aggregate is not — the top rule ids stored sessions in scope failed, with a failed-session count
and its share of the scope, worst first. No evaluator runs and no score moves (D11): the same
"sum stored rows" reading E33's `StatisticsReader` established, over `score_results` alone.

**Two call sites, one query.** The statistics page (`__call__`) reuses `StatisticsFilter` — the
same `trainee_id` / `group_id` / `from` / `to` `getTraineeStatistics` already takes — INSTRUCTOR /
ADMIN only, same reading as `GetTraineeRating`. A lesson's own table (`for_lesson`, embedded in
`getLessonReport`) is that lesson's sessions only, no further scoping: the lesson report's own
visibility already decided who reaches it.

**Ownership (INSTRUCTOR scoped to own lessons, ADMIN all, brief's own wording).** On the
statistics page, an INSTRUCTOR's scope is narrowed to sessions of lessons *they* created
(`StatisticsReader.scoped_session_ids(owner_id=...)`); a standalone session (no lesson) is
therefore outside an INSTRUCTOR's typical-errors view even though it counts for
`getTraineeStatistics` — «группа» here reads as "a class an instructor runs", never a session
nobody's lesson claims. An ADMIN's `owner_id` is `None`: every scored session, exactly like
`getTraineeStatistics`'s own unrestricted read. `for_lesson` applies no ownership check of its
own: `GetLessonReport` already decided whether this caller may see the lesson at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.statistics.ports import StatisticsFilter, StatisticsReader
from app.application.statistics.trainee_statistics import StatisticsSubjectNotFoundError
from app.domain.common.ids import LessonId, SessionId
from app.domain.enums import ScoringCategory

__all__ = ["GetTypicalErrors", "TypicalErrorRowView", "TypicalErrorsView"]


@dataclass(frozen=True, slots=True)
class TypicalErrorRowView:
    """One row: `rule_id`'s own text, its category, how many sessions in scope failed it and
    their share of the scope's session count."""

    rule_id: str
    name_ru: str
    category: ScoringCategory
    failed_session_count: int
    session_count: int
    share_percent: float


@dataclass(frozen=True, slots=True)
class TypicalErrorsView:
    """`TypicalErrors`."""

    rows: tuple[TypicalErrorRowView, ...]


class GetTypicalErrors:
    """`getTypicalErrors` (statistics page) and the lesson report's own table (`for_lesson`)."""

    def __init__(self, reader: StatisticsReader) -> None:
        self._reader = reader

    async def __call__(
        self, query: StatisticsFilter, user: AuthenticatedUser, *, limit: int = 10
    ) -> TypicalErrorsView:
        if not user.is_instructor_or_admin:
            raise ForbiddenForRoleError("typical errors is INSTRUCTOR / ADMIN only")
        if query.group_id is not None and not await self._reader.group_exists(query.group_id):
            raise StatisticsSubjectNotFoundError(f"no trainee group {query.group_id}")
        trainees = await self._reader.trainees(query)
        if query.trainee_id is not None and not trainees:
            raise StatisticsSubjectNotFoundError(f"no trainee account {query.trainee_id}")
        owner_id = None if user.user_role is UserRole.ADMIN else user.user_id
        session_ids = await self._reader.scoped_session_ids(
            user_ids=[trainee.user_id for trainee in trainees],
            owner_id=owner_id,
            from_utc=query.from_utc,
            to_utc=query.to_utc,
        )
        return await self._rows(session_ids, limit)

    async def for_lesson(self, lesson_id: LessonId, *, limit: int = 10) -> TypicalErrorsView:
        """The lesson report's own table: that lesson's sessions, no further scoping (module
        doc) — `GetLessonReport` already decided whether this caller may see the lesson."""
        session_ids = await self._reader.scoped_session_ids(lesson_id=lesson_id)
        return await self._rows(session_ids, limit)

    async def _rows(self, session_ids: Sequence[SessionId], limit: int) -> TypicalErrorsView:
        if not session_ids:
            return TypicalErrorsView(rows=())
        rows = await self._reader.typical_errors(session_ids, limit=limit)
        total = len(session_ids)
        return TypicalErrorsView(
            rows=tuple(
                TypicalErrorRowView(
                    rule_id=row.rule_id,
                    name_ru=row.name_ru,
                    category=ScoringCategory(row.category),
                    failed_session_count=row.failed_session_count,
                    session_count=total,
                    share_percent=100.0 * row.failed_session_count / total,
                )
                for row in rows
            )
        )
