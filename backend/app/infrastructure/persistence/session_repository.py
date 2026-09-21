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

from app.application.ports.session_repository import StoredParticipant, StoredSessionListing
from app.db.models.reference import Scenario as ScenarioRow
from app.db.models.reference import ScenarioVersion as ScenarioVersionRow
from app.db.models.session import Incident as IncidentRow
from app.db.models.session import RoleStage as RoleStageRow
from app.db.models.session import SessionParticipant as ParticipantRow
from app.db.models.session import SimulationSession as SessionRow
from app.domain.common.ids import SessionId, UserId
from app.domain.enums import RoleType, SessionMode, SessionState
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
_SCENARIOS = ScenarioRow.__table__
_VERSIONS = ScenarioVersionRow.__table__

#: `session_participants` reduced to what `my_role_type` needs; aliased per query so a session
#: listing can LEFT JOIN it restricted to one viewer without colliding with the write path.
_MY_PARTICIPATION = sa.select(
    _PARTICIPANTS.c.session_id, _PARTICIPANTS.c.user_id, _PARTICIPANTS.c.assigned_role_type
).subquery("my_participation")

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

    async def list_active_session_ids(self) -> list[SessionId]:
        """Every `ACTIVE` session's id, ordered by id — the runner's adoption read (D7).

        Ids only, and no row lock: adoption must not block a command, and the runner takes the
        §20.8 lock per session when it actually ticks one.
        """
        result = await self._session.execute(
            sa.select(_SESSIONS.c.id)
            .where(_SESSIONS.c.state == SessionState.ACTIVE.value)
            .order_by(_SESSIONS.c.id)
        )
        return [SessionId(UUID(str(row[0]))) for row in result.all()]

    # -- read paths for `listSessions` / `getSession` (E7) --------------------------------------

    async def list_sessions(
        self,
        *,
        viewer_user_id: UserId,
        mine_only: bool,
        state: SessionState | None,
        limit: int,
        offset: int,
    ) -> tuple[list[StoredSessionListing], int]:
        """One page of `SessionListItem` rows, newest first, plus the unpaged total.

        One statement, three joins: `scenario_versions` and `scenarios` for the slug and version
        number, and a LEFT JOIN of `session_participants` restricted to the viewer for
        `my_role_type`. `scope=MINE` becomes a `WHERE (created_by = viewer OR that join matched)`,
        so the filter and the `COUNT(*)` see exactly the same set.
        """
        viewer = UUID(str(viewer_user_id))
        mine = _MY_PARTICIPATION.alias("mine")
        source = (
            _SESSIONS.join(_VERSIONS, _VERSIONS.c.id == _SESSIONS.c.scenario_version_id)
            .join(_SCENARIOS, _SCENARIOS.c.id == _VERSIONS.c.scenario_id)
            .outerjoin(
                mine,
                sa.and_(
                    mine.c.session_id == _SESSIONS.c.id,
                    mine.c.user_id == viewer,
                ),
            )
        )
        conditions: list[sa.ColumnElement[bool]] = []
        if state is not None:
            conditions.append(_SESSIONS.c.state == state.value)
        if mine_only:
            conditions.append(
                sa.or_(_SESSIONS.c.created_by_user_id == viewer, mine.c.session_id.isnot(None))
            )

        total_result = await self._session.execute(
            sa.select(sa.func.count()).select_from(source).where(*conditions)
        )
        total = int(total_result.scalar_one())

        result = await self._session.execute(
            self._listing_select(mine)
            .select_from(source)
            .where(*conditions)
            .order_by(_SESSIONS.c.created_at.desc(), _SESSIONS.c.id)
            .limit(limit)
            .offset(offset)
        )
        return [_session_listing(row) for row in result.all()], total

    async def get_listing(
        self, session_id: SessionId, *, viewer_user_id: UserId
    ) -> StoredSessionListing | None:
        """The listing row of one session, or `None` (the `SessionDetail` join columns)."""
        viewer = UUID(str(viewer_user_id))
        mine = _MY_PARTICIPATION.alias("mine")
        result = await self._session.execute(
            self._listing_select(mine)
            .select_from(
                _SESSIONS.join(_VERSIONS, _VERSIONS.c.id == _SESSIONS.c.scenario_version_id)
                .join(_SCENARIOS, _SCENARIOS.c.id == _VERSIONS.c.scenario_id)
                .outerjoin(
                    mine,
                    sa.and_(mine.c.session_id == _SESSIONS.c.id, mine.c.user_id == viewer),
                )
            )
            .where(_SESSIONS.c.id == UUID(str(session_id)))
        )
        row = result.one_or_none()
        return None if row is None else _session_listing(row)

    async def list_participants(self, session_id: SessionId) -> list[StoredParticipant]:
        """This session's participants with their `joined_at`, in join order (§20.3)."""
        result = await self._session.execute(
            sa.select(
                _PARTICIPANTS.c.user_id,
                _PARTICIPANTS.c.assigned_role_type,
                _PARTICIPANTS.c.joined_at,
            )
            .where(_PARTICIPANTS.c.session_id == UUID(str(session_id)))
            .order_by(_PARTICIPANTS.c.joined_at, _PARTICIPANTS.c.id)
        )
        return [
            StoredParticipant(
                user_id=UserId(UUID(str(row.user_id))),
                assigned_role_type=(
                    None
                    if row.assigned_role_type is None
                    else RoleType(str(row.assigned_role_type))
                ),
                joined_at=row.joined_at,
            )
            for row in result.all()
        ]

    def _listing_select(self, mine: sa.Alias) -> sa.Select[Any]:
        """The `SessionListItem` columns; `mine` is the viewer-restricted participant alias."""
        return sa.select(
            _SESSIONS.c.id,
            _SCENARIOS.c.slug.label("scenario_slug"),
            _VERSIONS.c.version.label("scenario_version"),
            _SESSIONS.c.session_mode,
            _SESSIONS.c.state,
            _SESSIONS.c.created_at,
            _SESSIONS.c.created_by_user_id,
            mine.c.assigned_role_type.label("my_role_type"),
        )

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


def _session_listing(row: sa.Row[tuple[Any, ...]]) -> StoredSessionListing:
    """One joined session row as `openapi.yaml`'s `SessionListItem` projection."""
    return StoredSessionListing(
        session_id=SessionId(UUID(str(row.id))),
        scenario_slug=str(row.scenario_slug),
        scenario_version=int(row.scenario_version),
        session_mode=SessionMode(str(row.session_mode)),
        state=SessionState(str(row.state)),
        created_at=row.created_at,
        created_by_user_id=UserId(UUID(str(row.created_by_user_id))),
        my_role_type=None if row.my_role_type is None else RoleType(str(row.my_role_type)),
    )
