"""`session_events` relational guarantees (epic E4, HLD §20.6, D5).

`UNIQUE(session_id, seq_no)` is what makes the `seq_no` allocation protocol of §20.8 safe: two
appenders racing on the same session can never both win the same number.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_INSERT_EVENT = text(
    "INSERT INTO session_events"
    " (session_id, seq_no, event_type, monotonic_offset_ms, actor_type)"
    " VALUES (:session_id, :seq_no, :event_type, :offset_ms, :actor_type)"
)


async def test_duplicate_session_seq_no_is_rejected(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    """`seed_ids` already appended `seq_no = 1`; a second row with that number must fail."""
    with pytest.raises(IntegrityError) as excinfo:
        await db_session.execute(
            _INSERT_EVENT,
            {
                "session_id": seed_ids["session"],
                "seq_no": 1,
                "event_type": "SESSION_STARTED",
                "offset_ms": 10,
                "actor_type": "SYSTEM",
            },
        )
    assert "uq_session_events_session_seq" in str(excinfo.value)


async def test_next_seq_no_is_accepted(db_session: AsyncSession, seed_ids: dict[str, UUID]) -> None:
    """The same session may of course append the next number."""
    await db_session.execute(
        _INSERT_EVENT,
        {
            "session_id": seed_ids["session"],
            "seq_no": 2,
            "event_type": "SESSION_STARTED",
            "offset_ms": 10,
            "actor_type": "SYSTEM",
        },
    )
    result = await db_session.execute(
        text("SELECT count(*) FROM session_events WHERE session_id = :id"),
        {"id": seed_ids["session"]},
    )
    assert int(result.scalar_one()) == 2


async def test_unknown_event_type_is_rejected(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    """The `event_type` CHECK is generated from the domain `EventType` enum (HLD §20.6)."""
    with pytest.raises(IntegrityError) as excinfo:
        await db_session.execute(
            _INSERT_EVENT,
            {
                "session_id": seed_ids["session"],
                "seq_no": 2,
                "event_type": "NOT_AN_EVENT_TYPE",
                "offset_ms": 10,
                "actor_type": "SYSTEM",
            },
        )
    assert "ck_session_events_event_type" in str(excinfo.value)


async def test_model_may_not_write_a_card_revision(
    db_session: AsyncSession, seed_ids: dict[str, UUID]
) -> None:
    """SPEC §9 / §42 test 4: only TRAINEE and INSTRUCTOR may author a card revision."""
    with pytest.raises(IntegrityError) as excinfo:
        await db_session.execute(
            text(
                "INSERT INTO incident_card_revisions"
                " (card_id, revision_no, field_path, value_type, actor_type, at_offset_ms)"
                " VALUES (:card_id, 2, 'location.address', 'STRING', 'MODEL', 300)"
            ),
            {"card_id": seed_ids["card"]},
        )
    assert "ck_incident_card_revisions_actor_type" in str(excinfo.value)
