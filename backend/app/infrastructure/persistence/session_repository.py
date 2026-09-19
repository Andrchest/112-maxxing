"""`SqlAlchemySessionRepository` — the session aggregate over PostgreSQL (§20.3, D5).

The aggregate spans four tables (`simulation_sessions`, `incidents`, `role_stages`,
`session_participants`) and is written and read as one unit. ORM rows never leave this module:
every conversion goes through `app.infrastructure.persistence.mappers` (D2), so the application
layer only ever sees `SimulationSession`.

Two invariants this class exists to keep:

* `next_seq_no` is never written. Sequence allocation belongs to `SqlAlchemyEventStore` under the
  §20.8 row lock; an UPDATE from here that touched the column would race it.
* `get_for_update` takes `SELECT … FOR UPDATE` on the `simulation_sessions` row *before* the
  aggregate is read, so the whole read-decide-write cycle of a command is serialised against
  another command on the same session for the life of the Unit of Work transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.session import Incident as IncidentRow
from app.db.models.session import RoleStage as RoleStageRow
from app.db.models.session import SessionParticipant as ParticipantRow
from app.db.models.session import SimulationSession as SessionRow
from app.domain.common.ids import SessionId
from app.domain.session.session import SimulationSession
from app.infrastructure.persistence.mappers import (
    incident_row_values,
    participant_row_values,
    role_stage_row_values,
    session_from_rows,
    session_row_values,
)

__all__ = ["SqlAlchemySessionRepository"]

_SESSIONS = SessionRow.__table__
_INCIDENTS = IncidentRow.__table__
_STAGES = RoleStageRow.__table__
_PARTICIPANTS = ParticipantRow.__table__

#: Columns an UPDATE of an existing session row may change. `id`, `scenario_version_id`,
#: `session_mode`, `session_seed`, `created_by_user_id`, `created_at` are immutable once created,
#: and `next_seq_no` belongs to the event store (§20.8).
_MUTABLE_SESSION_COLUMNS: tuple[str, ...] = (
    "state",
    "time_scale",
    "started_at",
    "paused_total_ms",
    "completed_at",
    "abort_reason",
)


class SqlAlchemySessionRepository:
    """`SessionRepository` over PostgreSQL, bound to one `AsyncSession` (one transaction)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- writes -------------------------------------------------------------------------------

    async def add(self, session: SimulationSession) -> None:
        """Insert the session, its incident, its stages and its participants, in FK order."""
        await self._session.execute(sa.insert(_SESSIONS).values(**session_row_values(session)))
        await self._session.execute(
            sa.insert(_INCIDENTS).values(**incident_row_values(session.incident))
        )
        if session.stages:
            await self._session.execute(
                sa.insert(_STAGES), [role_stage_row_values(stage) for stage in session.stages]
            )
        if session.participants:
            await self._session.execute(
                sa.insert(_PARTICIPANTS),
                [
                    participant_row_values(session.id, participant)
                    for participant in session.participants
                ],
            )

    async def save(self, session: SimulationSession) -> None:
        """Update the four tables from `session`; never `next_seq_no` (§20.8)."""
        values = session_row_values(session)
        await self._session.execute(
            sa.update(_SESSIONS)
            .where(_SESSIONS.c.id == UUID(str(session.id)))
            .values(**{column: values[column] for column in _MUTABLE_SESSION_COLUMNS})
        )

        incident = incident_row_values(session.incident)
        await self._session.execute(
            sa.update(_INCIDENTS)
            .where(_INCIDENTS.c.id == incident["id"])
            .values(
                closed_at_offset_ms=incident["closed_at_offset_ms"],
                closure_reason=incident["closure_reason"],
            )
        )

        for stage in session.stages:
            row = role_stage_row_values(stage)
            await self._session.execute(
                sa.update(_STAGES)
                .where(_STAGES.c.id == row["id"])
                .values(
                    state=row["state"],
                    participant_user_id=row["participant_user_id"],
                    started_at_offset_ms=row["started_at_offset_ms"],
                    completed_at_offset_ms=row["completed_at_offset_ms"],
                )
            )

        for participant in session.participants:
            row = participant_row_values(session.id, participant)
            result = await self._session.execute(
                sa.update(_PARTICIPANTS)
                .where(_PARTICIPANTS.c.id == row["id"])
                .values(user_id=row["user_id"], assigned_role_type=row["assigned_role_type"])
                .returning(_PARTICIPANTS.c.id)
            )
            if result.one_or_none() is None:
                await self._session.execute(sa.insert(_PARTICIPANTS).values(**row))

    # -- reads --------------------------------------------------------------------------------

    async def get(self, session_id: SessionId) -> SimulationSession | None:
        """The aggregate, without taking a row lock."""
        return await self._load(session_id, for_update=False)

    async def get_for_update(self, session_id: SessionId) -> SimulationSession | None:
        """The aggregate, with `SELECT … FOR UPDATE` on `simulation_sessions` (§20.8)."""
        return await self._load(session_id, for_update=True)

    # -- internals ----------------------------------------------------------------------------

    async def _load(self, session_id: SessionId, *, for_update: bool) -> SimulationSession | None:
        key = UUID(str(session_id))
        statement = sa.select(_SESSIONS).where(_SESSIONS.c.id == key)
        if for_update:
            statement = statement.with_for_update()
        session_row = (await self._session.execute(statement)).one_or_none()
        if session_row is None:
            return None

        incident_row = (
            await self._session.execute(sa.select(_INCIDENTS).where(_INCIDENTS.c.session_id == key))
        ).one_or_none()
        if incident_row is None:
            raise LookupError(
                f"session {session_id} has no incidents row; uq_incidents_session (§20.3) says "
                "every session has exactly one"
            )

        stage_rows = await self._rows(
            sa.select(_STAGES).where(_STAGES.c.session_id == key).order_by(_STAGES.c.order_index)
        )
        participant_rows = await self._rows(
            sa.select(_PARTICIPANTS)
            .where(_PARTICIPANTS.c.session_id == key)
            .order_by(_PARTICIPANTS.c.joined_at, _PARTICIPANTS.c.id)
        )
        return session_from_rows(
            session_row._mapping, incident_row._mapping, stage_rows, participant_rows
        )

    async def _rows(self, statement: sa.Select[Any]) -> Sequence[Mapping[str, Any]]:
        result = await self._session.execute(statement)
        return [row._mapping for row in result.all()]
