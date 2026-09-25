"""`ResultCommentRepository` port — `result_comments` (HLD §20.11.2, I4 E32, ТЗ ¶236, ¶237).

Instructor feedback on a session or a lesson result. The table is append-only: an edit is a new
row whose `replaces_comment_id` points at the row it supersedes, so this port exposes no update or
delete method at all — only `add` and the two list reads. `superseded` is carried on every row
returned by a list, computed by the adapter (whether some other row's `replaces_comment_id` points
at this one), so a client never has to fold the list itself to find the current text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.common.ids import LessonId, SessionId, UserId

__all__ = ["NewResultComment", "ResultCommentRepository", "StoredResultComment"]


@dataclass(frozen=True, slots=True)
class NewResultComment:
    """The fields `createSessionComment` / `createLessonComment` write (exactly one of
    `session_id` / `lesson_id` is set — the use case enforces this, the migration's `CHECK`
    guarantees it)."""

    id: UUID
    session_id: SessionId | None
    lesson_id: LessonId | None
    author_user_id: UserId
    text: str
    replaces_comment_id: UUID | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredResultComment:
    """One `result_comments` row, joined with its author's display name (`openapi.yaml`'s
    `ResultCommentView`)."""

    id: UUID
    session_id: SessionId | None
    lesson_id: LessonId | None
    author_user_id: UserId
    author_display_name_ru: str
    text: str
    replaces_comment_id: UUID | None
    created_at: datetime
    superseded: bool
    """`True` when some other row's `replaces_comment_id` points at this one (an edit exists)."""


@runtime_checkable
class ResultCommentRepository(Protocol):
    """Append-only access to `result_comments`."""

    async def add(self, comment: NewResultComment) -> UUID:
        """Insert one row; never an update (append-only, §20.9's `trg_reject_mutation()`)."""
        ...

    async def get(self, comment_id: UUID) -> StoredResultComment | None:
        """One row by id, or `None` — used to validate `replaces_comment_id` before an insert."""
        ...

    async def list_for_session(self, session_id: SessionId) -> list[StoredResultComment]:
        """Every comment of `session_id`, oldest first (`listSessionComments`)."""
        ...

    async def list_for_lesson(self, lesson_id: LessonId) -> list[StoredResultComment]:
        """Every comment of `lesson_id`, oldest first (`listLessonComments`)."""
        ...
