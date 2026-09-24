"""`SqlAlchemySessionRepository` — the session aggregate over PostgreSQL (§20.3, D5).

The aggregate spans four tables (`simulation_sessions`, `incidents`, `role_stages`,
`session_participants`) and is written and read as one unit. ORM rows never leave this module:
every conversion goes through `app.infrastructure.persistence.mappers` (D2), so the application
layer only ever sees `SimulationSession`.

Two invariants this class exists to keep:

* `next_seq_no` is never written. Sequence allocation belongs to `SqlAlchemyEventStore` under the
  §20.8 row lock; an UPDATE from here that touched the column would race it.
* `get_for_update` takes `SELECT … FOR NO KEY UPDATE` on the `simulation_sessions` row *before*
  the aggregate is read, so the whole read-decide-write cycle of a command is serialised against
  another command on the same session for the life of the Unit of Work transaction.

  The mode is `FOR NO KEY UPDATE`, the same one `SqlAlchemyEventStore` allocates `seq_no` under,
  and for the same reason (R14, E19-E3 bug #6): it conflicts with itself — so two commands, or a
  command and a runner tick, are still strictly serialised — while staying compatible with the
  `FOR KEY SHARE` that PostgreSQL takes on this row for every insert into a table with a foreign
  key to it. `FOR UPDATE` is not, and a voice-agent transaction that had already written an
  `audio_segments` / `transcript_segments` / `dialogue_turns` row therefore had to *upgrade* its
  lock, which deadlocked against a second such transaction. `SqlAlchemyEventStore`'s module
  docstring carries the full account and the lock order every writer follows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.session_repository import (
    ReportRelease,
    StoredIncidentRow,
    StoredParticipant,
    StoredSessionListing,
)
from app.db.models.reference import Scenario as ScenarioRow
from app.db.models.reference import ScenarioVersion as ScenarioVersionRow
from app.db.models.session import Incident as IncidentRow
from app.db.models.session import RoleStage as RoleStageRow
from app.db.models.session import SessionParticipant as ParticipantRow
from app.db.models.session import SimulationSession as SessionRow
from app.domain.common.ids import IncidentId, LessonId, SessionId, UserId
from app.domain.dds.card_status import CardStatus
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
    "role_transition_started_offset_ms",
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

    async def get_report_release(self, session_id: SessionId) -> ReportRelease | None:
        """The release record of `session_id`, or `None` (E16, D6, D11)."""
        result = await self._session.execute(
            sa.select(_SESSIONS.c.report_released_at, _SESSIONS.c.report_released_by_user_id).where(
                _SESSIONS.c.id == UUID(str(session_id))
            )
        )
        row = result.one_or_none()
        if row is None or row.report_released_at is None:
            return None
        return _report_release(session_id, row.report_released_at, row.report_released_by_user_id)

    async def release_report(
        self, session_id: SessionId, *, released_by_user_id: UserId, released_at: datetime
    ) -> ReportRelease:
        """One conditional UPDATE, then a read of whatever is now stored (idempotent, E16 R2).

        `WHERE report_released_at IS NULL` is the whole idempotence: the second caller's UPDATE
        matches no row, and the follow-up read returns the first release unchanged rather than
        overwriting its timestamp and its author.
        """
        await self._session.execute(
            sa.update(_SESSIONS)
            .where(
                sa.and_(
                    _SESSIONS.c.id == UUID(str(session_id)),
                    _SESSIONS.c.report_released_at.is_(None),
                )
            )
            .values(
                report_released_at=released_at,
                report_released_by_user_id=UUID(str(released_by_user_id)),
            )
        )
        stored = await self.get_report_release(session_id)
        if stored is None:  # pragma: no cover - the caller proved the session row exists
            raise RuntimeError(f"session {session_id} vanished while releasing its report")
        return stored

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
                .values(
                    user_id=row["user_id"],
                    assigned_role_type=row["assigned_role_type"],
                    assigned_service_id=row["assigned_service_id"],
                )
                .returning(_PARTICIPANTS.c.id)
            )
            if result.one_or_none() is None:
                await self._session.execute(sa.insert(_PARTICIPANTS).values(**row))

    # -- the card-status read model (HLD 70 §70.4.6, I3 E4a) -----------------------------------

    async def get_card_status(self, session_id: SessionId) -> CardStatus | None:
        """`incidents.card_status` of the session's one incident, or `None`."""
        result = await self._session.execute(
            sa.select(_INCIDENTS.c.card_status).where(
                _INCIDENTS.c.session_id == UUID(str(session_id))
            )
        )
        value = result.scalar_one_or_none()
        return None if value is None else CardStatus(str(value))

    async def set_card_status(self, session_id: SessionId, status: CardStatus) -> None:
        """Materialise `incidents.card_status`, inside the caller's transaction."""
        await self._session.execute(
            sa.update(_INCIDENTS)
            .where(_INCIDENTS.c.session_id == UUID(str(session_id)))
            .values(card_status=status.value)
        )

    async def list_incident_rows(
        self, *, viewer_user_id: UserId, lesson_id: LessonId | None
    ) -> list[StoredIncidentRow]:
        """The viewer's sessions (participant or creator), newest start first, one statement."""
        viewer = UUID(str(viewer_user_id))
        mine = _MY_PARTICIPATION.alias("mine")
        conditions: list[sa.ColumnElement[bool]] = [
            sa.or_(_SESSIONS.c.created_by_user_id == viewer, mine.c.session_id.isnot(None))
        ]
        if lesson_id is not None:
            conditions.append(_SESSIONS.c.lesson_id == UUID(str(lesson_id)))
        result = await self._session.execute(
            sa.select(
                _SESSIONS.c.id,
                _SESSIONS.c.lesson_id,
                _SESSIONS.c.lesson_position,
                _SESSIONS.c.state,
                _SESSIONS.c.started_at,
                _SESSIONS.c.created_at,
                _SESSIONS.c.created_by_user_id,
                _INCIDENTS.c.id.label("incident_id"),
                _INCIDENTS.c.display_number,
                _INCIDENTS.c.card_status,
                mine.c.session_id.label("participation"),
                mine.c.assigned_role_type.label("my_role_type"),
            )
            .select_from(
                _SESSIONS.join(_INCIDENTS, _INCIDENTS.c.session_id == _SESSIONS.c.id).outerjoin(
                    mine,
                    sa.and_(mine.c.session_id == _SESSIONS.c.id, mine.c.user_id == viewer),
                )
            )
            .where(*conditions)
            .order_by(
                _SESSIONS.c.started_at.desc().nulls_last(),
                _SESSIONS.c.created_at.desc(),
                _SESSIONS.c.id,
            )
        )
        return [
            StoredIncidentRow(
                session_id=SessionId(UUID(str(row.id))),
                incident_id=IncidentId(UUID(str(row.incident_id))),
                display_number=int(row.display_number),
                lesson_id=None if row.lesson_id is None else LessonId(UUID(str(row.lesson_id))),
                lesson_position=row.lesson_position,
                card_status=CardStatus(str(row.card_status)),
                session_state=SessionState(str(row.state)),
                started_at=row.started_at,
                created_at=row.created_at,
                created_by_user_id=UserId(UUID(str(row.created_by_user_id))),
                is_participant=row.participation is not None,
                my_role_type=None if row.my_role_type is None else RoleType(str(row.my_role_type)),
            )
            for row in result.all()
        ]

    # -- reads --------------------------------------------------------------------------------

    async def get(self, session_id: SessionId) -> SimulationSession | None:
        """The aggregate, without taking a row lock."""
        return await self._load(session_id, for_update=False)

    async def get_for_update(self, session_id: SessionId) -> SimulationSession | None:
        """The aggregate, with `SELECT … FOR NO KEY UPDATE` on `simulation_sessions` (§20.8)."""
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
            # `key_share=True` renders `FOR NO KEY UPDATE` on PostgreSQL — see this module's
            # docstring and `SqlAlchemyEventStore`'s (R14).
            statement = statement.with_for_update(key_share=True)
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


def _report_release(
    session_id: SessionId, released_at: datetime, released_by_user_id: Any
) -> ReportRelease:
    """The two columns as the application type; the CHECK guarantees they are both set."""
    return ReportRelease(
        session_id=session_id,
        released_at=released_at,
        released_by_user_id=UserId(UUID(str(released_by_user_id))),
    )
