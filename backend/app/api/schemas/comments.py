"""`comments` schemas (I4 E32, `docs/hld/contracts/i4-openapi-delta.yaml` — `ResultComment*`).

Property names are literal copies of the delta: `ResultCommentRequest`, `ResultCommentView`,
`ResultCommentList`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.instructor.comments import NewCommentRequest
from app.application.ports.result_comment_repository import StoredResultComment

__all__ = [
    "ResultCommentListSchema",
    "ResultCommentRequestSchema",
    "ResultCommentViewSchema",
    "result_comment_schema",
]


class ResultCommentRequestSchema(ApiModel):
    """`openapi.yaml`'s (delta) `ResultCommentRequest`."""

    text: str = Field(min_length=1)
    replaces_comment_id: UUID | None = None

    def to_command(self) -> NewCommentRequest:
        return NewCommentRequest(text=self.text, replaces_comment_id=self.replaces_comment_id)


class ResultCommentViewSchema(ApiModel):
    """`openapi.yaml`'s (delta) `ResultCommentView`."""

    comment_id: UUID
    session_id: UUID | None
    lesson_id: UUID | None
    author_user_id: UUID
    author_display_name_ru: str
    text: str
    created_at: datetime
    replaces_comment_id: UUID | None
    superseded: bool


class ResultCommentListSchema(ApiModel):
    """`openapi.yaml`'s (delta) `ResultCommentList`."""

    items: list[ResultCommentViewSchema]


def result_comment_schema(comment: StoredResultComment) -> ResultCommentViewSchema:
    """`StoredResultComment` → `ResultCommentView`."""
    return ResultCommentViewSchema(
        comment_id=comment.id,
        session_id=None if comment.session_id is None else UUID(str(comment.session_id)),
        lesson_id=None if comment.lesson_id is None else UUID(str(comment.lesson_id)),
        author_user_id=UUID(str(comment.author_user_id)),
        author_display_name_ru=comment.author_display_name_ru,
        text=comment.text,
        created_at=comment.created_at,
        replaces_comment_id=comment.replaces_comment_id,
        superseded=comment.superseded,
    )
