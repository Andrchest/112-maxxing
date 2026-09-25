"""`SqlAlchemyResultCommentRepository` over `result_comments` (§20.11.2, I4 E32).

`superseded` is computed with a correlated `EXISTS`, not folded in Python: "some other row's
`replaces_comment_id` points at this one" is exactly what the subquery states, and it stays correct
however many edits a comment has accumulated.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.result_comment_repository import NewResultComment, StoredResultComment
from app.db.models.reference import User as UserRow
from app.db.models.reports import ResultComment as ResultCommentRow
from app.domain.common.ids import LessonId, SessionId, UserId

__all__ = ["SqlAlchemyResultCommentRepository"]

_COMMENTS = ResultCommentRow.__table__
_USERS = UserRow.__table__


class SqlAlchemyResultCommentRepository:
    """`ResultCommentRepository` over PostgreSQL, bound to one `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, comment: NewResultComment) -> UUID:
        await self._session.execute(
            sa.insert(_COMMENTS).values(
                id=comment.id,
                session_id=None if comment.session_id is None else UUID(str(comment.session_id)),
                lesson_id=None if comment.lesson_id is None else UUID(str(comment.lesson_id)),
                author_user_id=UUID(str(comment.author_user_id)),
                text=comment.text,
                replaces_comment_id=comment.replaces_comment_id,
                created_at=comment.created_at,
            )
        )
        return comment.id

    async def get(self, comment_id: UUID) -> StoredResultComment | None:
        result = await self._session.execute(self._select().where(_COMMENTS.c.id == comment_id))
        row = result.mappings().one_or_none()
        return None if row is None else _from_row(row)

    async def list_for_session(self, session_id: SessionId) -> list[StoredResultComment]:
        result = await self._session.execute(
            self._select()
            .where(_COMMENTS.c.session_id == UUID(str(session_id)))
            .order_by(_COMMENTS.c.created_at)
        )
        return [_from_row(row) for row in result.mappings()]

    async def list_for_lesson(self, lesson_id: LessonId) -> list[StoredResultComment]:
        result = await self._session.execute(
            self._select()
            .where(_COMMENTS.c.lesson_id == UUID(str(lesson_id)))
            .order_by(_COMMENTS.c.created_at)
        )
        return [_from_row(row) for row in result.mappings()]

    def _select(self) -> sa.Select[tuple[object, ...]]:
        superseding = _COMMENTS.alias("superseding")
        superseded = (
            sa.select(sa.literal(1))
            .where(superseding.c.replaces_comment_id == _COMMENTS.c.id)
            .exists()
        )
        return sa.select(
            _COMMENTS.c.id,
            _COMMENTS.c.session_id,
            _COMMENTS.c.lesson_id,
            _COMMENTS.c.author_user_id,
            _USERS.c.display_name_ru.label("author_display_name_ru"),
            _COMMENTS.c.text,
            _COMMENTS.c.replaces_comment_id,
            _COMMENTS.c.created_at,
            superseded.label("superseded"),
        ).select_from(_COMMENTS.join(_USERS, _USERS.c.id == _COMMENTS.c.author_user_id))


def _from_row(row: sa.RowMapping) -> StoredResultComment:
    return StoredResultComment(
        id=UUID(str(row["id"])),
        session_id=None if row["session_id"] is None else SessionId(UUID(str(row["session_id"]))),
        lesson_id=None if row["lesson_id"] is None else LessonId(UUID(str(row["lesson_id"]))),
        author_user_id=UserId(UUID(str(row["author_user_id"]))),
        author_display_name_ru=str(row["author_display_name_ru"]),
        text=str(row["text"]),
        replaces_comment_id=(
            None if row["replaces_comment_id"] is None else UUID(str(row["replaces_comment_id"]))
        ),
        created_at=row["created_at"],
        superseded=bool(row["superseded"]),
    )
