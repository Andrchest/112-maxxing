"""`SqlAlchemyDialogueTurnRepository` over `dialogue_turns` (§20.6, §9, D5).

The write is an `INSERT … ON CONFLICT (session_id, turn_index) DO UPDATE` that sets **only the
columns the caller supplied**, because three epics fill this row in three passes (E12 the speech
boundaries and the operator transcript, E13 the interpretation and the gate output, E14 the caller
side and the latency) and none of them may blank another's work. `COALESCE(EXCLUDED.col, col)` is
not enough on its own for that — it would still overwrite a value with a *given* `None` — so the
update dictionary is built from the fields that were actually set rather than from the model's
full field list.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.dialogue_turn_repository import (
    DialogueTurnUpsert,
    StoredDialogueTurn,
)
from app.db.models.events import DialogueTurn as DialogueTurnRow
from app.domain.common.ids import RoleStageId, SessionId

__all__ = ["SqlAlchemyDialogueTurnRepository"]

_DIALOGUE_TURNS = DialogueTurnRow.__table__

#: The key of the row. Never part of the `DO UPDATE` set.
_KEY_COLUMNS = ("id", "session_id", "role_stage_id", "turn_index")


def _from_row(row: Mapping[str, Any]) -> StoredDialogueTurn:
    return StoredDialogueTurn(
        id=row["id"],
        session_id=SessionId(row["session_id"]),
        role_stage_id=RoleStageId(row["role_stage_id"]),
        turn_index=row["turn_index"],
        user_speech_started_offset_ms=row["user_speech_started_offset_ms"],
        user_speech_ended_offset_ms=row["user_speech_ended_offset_ms"],
        operator_transcript_segment_id=row["operator_transcript_segment_id"],
        caller_transcript_segment_id=row["caller_transcript_segment_id"],
        planned_text=row["planned_text"],
        delivered_text=row["delivered_text"],
        interrupted=row["interrupted"],
        fallback_used=row["fallback_used"],
        speech_end_to_first_audio_ms=row["speech_end_to_first_audio_ms"],
        correlation_id=row["correlation_id"],
        interpretation=row["interpretation"] or {},
        gate_output=row["gate_output"] or {},
    )


class SqlAlchemyDialogueTurnRepository:
    """`DialogueTurnRepository` over PostgreSQL, bound to one `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, turn: DialogueTurnUpsert) -> UUID:
        """Insert or update `(session_id, turn_index)`; returns the row's id."""
        values: dict[str, Any] = {
            "id": turn.id,
            "session_id": UUID(str(turn.session_id)),
            "role_stage_id": UUID(str(turn.role_stage_id)),
            "turn_index": turn.turn_index,
            "user_speech_started_offset_ms": turn.user_speech_started_offset_ms,
        }
        # Only the optional columns the caller actually set, so a second pass by E13/E14 cannot
        # be blanked by a first pass that had nothing to say about them.
        supplied = turn.model_fields_set
        for column in (
            "user_speech_ended_offset_ms",
            "operator_transcript_segment_id",
            "correlation_id",
        ):
            if column in supplied:
                values[column] = getattr(turn, column)
        statement = pg_insert(_DIALOGUE_TURNS).values(**values)
        updates = {name: statement.excluded[name] for name in values if name not in _KEY_COLUMNS}
        statement = statement.on_conflict_do_update(
            index_elements=["session_id", "turn_index"],
            set_=updates or {"turn_index": statement.excluded["turn_index"]},
        ).returning(_DIALOGUE_TURNS.c.id)
        result = await self._session.execute(statement)
        row_id = result.scalar_one()
        return UUID(str(row_id))

    async def set_dialogue_outcome(
        self,
        session_id: SessionId,
        turn_index: int,
        *,
        interpretation: Mapping[str, Any],
        gate_output: Mapping[str, Any],
        planned_text: str,
        fallback_used: bool,
    ) -> None:
        """E13's four columns on an existing row; no row, no write (§20.6)."""
        await self._session.execute(
            sa.update(_DIALOGUE_TURNS)
            .where(
                _DIALOGUE_TURNS.c.session_id == UUID(str(session_id)),
                _DIALOGUE_TURNS.c.turn_index == turn_index,
            )
            .values(
                interpretation=dict(interpretation),
                gate_output=dict(gate_output),
                planned_text=planned_text,
                fallback_used=fallback_used,
            )
        )

    async def set_caller_outcome(
        self,
        session_id: SessionId,
        turn_index: int,
        *,
        caller_transcript_segment_id: UUID | None,
        delivered_text: str,
        interrupted: bool,
    ) -> None:
        """E14's three caller-side columns on an existing row; no row, no write (§20.6, §6.4)."""
        await self._session.execute(
            sa.update(_DIALOGUE_TURNS)
            .where(
                _DIALOGUE_TURNS.c.session_id == UUID(str(session_id)),
                _DIALOGUE_TURNS.c.turn_index == turn_index,
            )
            .values(
                caller_transcript_segment_id=caller_transcript_segment_id,
                delivered_text=delivered_text,
                interrupted=interrupted,
            )
        )

    async def set_speech_end_to_first_audio_ms(
        self, session_id: SessionId, turn_index: int, value: int
    ) -> None:
        """SPEC §27's critical product metric on an existing turn row; no row, no write."""
        await self._session.execute(
            sa.update(_DIALOGUE_TURNS)
            .where(
                _DIALOGUE_TURNS.c.session_id == UUID(str(session_id)),
                _DIALOGUE_TURNS.c.turn_index == turn_index,
            )
            .values(speech_end_to_first_audio_ms=value)
        )

    async def get(self, session_id: SessionId, turn_index: int) -> StoredDialogueTurn | None:
        """One row by its natural key, or `None`."""
        result = await self._session.execute(
            sa.select(_DIALOGUE_TURNS).where(
                _DIALOGUE_TURNS.c.session_id == UUID(str(session_id)),
                _DIALOGUE_TURNS.c.turn_index == turn_index,
            )
        )
        row = result.first()
        return None if row is None else _from_row(row._mapping)

    async def list_for_session(self, session_id: SessionId) -> list[StoredDialogueTurn]:
        """Every turn of one session in `turn_index` order."""
        result = await self._session.execute(
            sa.select(_DIALOGUE_TURNS)
            .where(_DIALOGUE_TURNS.c.session_id == UUID(str(session_id)))
            .order_by(_DIALOGUE_TURNS.c.turn_index)
        )
        return [_from_row(row._mapping) for row in result.all()]
