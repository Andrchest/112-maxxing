"""`result_comments` (migration `0017_result_comments_scenario_archive`, I4 E32; HLD 20 §20.11.2,
§20.9).

The legal INSERT is accepted; UPDATE and DELETE are rejected by the database's own
`result_comments_append_only` trigger — asserted on the error it raises, the same way
`test_audit_log_table.py` asserts `audit_log`'s. The `exactly_one_target` CHECK (exactly one of
`session_id` / `lesson_id`) and the `text_not_empty` CHECK bite too.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _insert(
    session: AsyncSession,
    *,
    author_user_id: UUID,
    session_id: UUID | None,
    lesson_id: UUID | None = None,
    text_value: str = "Хорошая работа.",
) -> UUID:
    result = await session.execute(
        text(
            "INSERT INTO result_comments (session_id, lesson_id, author_user_id, text)"
            " VALUES (:session_id, :lesson_id, :author_user_id, :text) RETURNING id"
        ),
        {
            "session_id": session_id,
            "lesson_id": lesson_id,
            "author_user_id": author_user_id,
            "text": text_value,
        },
    )
    return UUID(str(result.scalar_one()))


async def test_a_legal_insert_on_a_session_is_accepted(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    row_id = await _insert(
        db_session, author_user_id=seed_ids["user"], session_id=seed_ids["session"]
    )
    row = (
        await db_session.execute(
            text(
                "SELECT session_id, lesson_id, replaces_comment_id"
                " FROM result_comments WHERE id = :id"
            ),
            {"id": row_id},
        )
    ).one()
    assert row.session_id == seed_ids["session"]
    assert row.lesson_id is None
    assert row.replaces_comment_id is None


async def test_an_edit_is_a_new_row_pointing_at_the_one_it_replaces(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    first_id = await _insert(
        db_session, author_user_id=seed_ids["user"], session_id=seed_ids["session"]
    )
    result = await db_session.execute(
        text(
            "INSERT INTO result_comments (session_id, author_user_id, text, replaces_comment_id)"
            " VALUES (:session_id, :author_user_id, 'edited text', :replaces) RETURNING id"
        ),
        {
            "session_id": seed_ids["session"],
            "author_user_id": seed_ids["user"],
            "replaces": first_id,
        },
    )
    second_id = UUID(str(result.scalar_one()))

    count = (await db_session.execute(text("SELECT count(*) FROM result_comments"))).scalar_one()
    assert count == 2, "the edit is a second row, never an UPDATE of the first"

    original_text = (
        await db_session.execute(
            text("SELECT text FROM result_comments WHERE id = :id"), {"id": first_id}
        )
    ).scalar_one()
    assert original_text == "Хорошая работа.", "the original row is untouched"

    replaces = (
        await db_session.execute(
            text("SELECT replaces_comment_id FROM result_comments WHERE id = :id"),
            {"id": second_id},
        )
    ).scalar_one()
    assert replaces == first_id


async def test_update_is_rejected(db_session: AsyncSession, seed_ids: dict[str, UUID]) -> None:
    row_id = await _insert(
        db_session, author_user_id=seed_ids["user"], session_id=seed_ids["session"]
    )
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text("UPDATE result_comments SET text = 'changed' WHERE id = :id"), {"id": row_id}
        )
    assert "append-only" in str(excinfo.value)
    assert "UPDATE" in str(excinfo.value)


async def test_delete_is_rejected(db_session: AsyncSession, seed_ids: dict[str, UUID]) -> None:
    row_id = await _insert(
        db_session, author_user_id=seed_ids["user"], session_id=seed_ids["session"]
    )
    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(text("DELETE FROM result_comments WHERE id = :id"), {"id": row_id})
    assert "append-only" in str(excinfo.value)
    assert "DELETE" in str(excinfo.value)


async def test_neither_session_nor_lesson_violates_exactly_one_target(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    with pytest.raises(IntegrityError):
        await _insert(db_session, author_user_id=seed_ids["user"], session_id=None, lesson_id=None)


async def test_both_session_and_lesson_violates_exactly_one_target(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    lesson_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO lessons"
            " (id, title_ru, created_by_user_id, session_mode, participants, scenario_plan)"
            " VALUES (:id, 'Урок', :user_id, 'SINGLE_ROLE', '[]'::jsonb, '[]'::jsonb)"
        ),
        {"id": lesson_id, "user_id": seed_ids["user"]},
    )
    with pytest.raises(IntegrityError):
        await _insert(
            db_session,
            author_user_id=seed_ids["user"],
            session_id=seed_ids["session"],
            lesson_id=lesson_id,
        )


async def test_empty_text_violates_the_check(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    with pytest.raises(IntegrityError):
        await _insert(
            db_session,
            author_user_id=seed_ids["user"],
            session_id=seed_ids["session"],
            text_value="",
        )
