"""`SqlAlchemyStatisticsReader` — `StatisticsReader` over the stored scores (I4 E33, HLD 71
§71.10).

Set-based on purpose (ТЗ ¶165 REQ-2142: an analytic report in 30 s or less): whatever the number
of sessions, one call is five statements — the sessions, their participants, their score sums per
category, the events the norms read, and nothing per session. Every statement is a read in one
short transaction of its own (like E25's `SqlAlchemyAuditLog`, not the Unit of Work: a read model
publishes nothing and belongs to no aggregate).

Only stored rows are summed (D11): `sum(points_awarded)`, `sum(max_points)` and counts of
`passed = false` / `critical_failure = true` per `(session, category)`. The adapter evaluates no
rule.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.reports.norms import NORM_EVENT_TYPES
from app.application.statistics.ports import (
    ScoredSession,
    StatisticsEvent,
    StatisticsFilter,
    StatisticsParticipant,
    TraineeAccount,
)
from app.db.models.events import SessionEvent as SessionEventRow
from app.db.models.reference import ScenarioVersion as ScenarioVersionRow
from app.db.models.reference import TraineeGroup as TraineeGroupRow
from app.db.models.reference import TraineeGroupMember as TraineeGroupMemberRow
from app.db.models.reference import User as UserRow
from app.db.models.scoring import ScoreResult as ScoreResultRow
from app.db.models.session import SessionParticipant as SessionParticipantRow
from app.db.models.session import SimulationSession as SimulationSessionRow
from app.domain.common.ids import LessonId, SessionId, TraineeGroupId, UserId
from app.domain.dds.card_status import DEFAULT_CARD_TIMERS, CardTimers
from app.domain.enums import RoleType, SessionMode
from app.domain.events.types import EventType

__all__ = ["SqlAlchemyStatisticsReader"]

_TRAINEE = "TRAINEE"
_COMPLETED = "COMPLETED"
_NORM_EVENT_TYPE_VALUES = sorted(event_type.value for event_type in NORM_EVENT_TYPES)
_EVENT_TYPES = {event_type.value: event_type for event_type in EventType}


class SqlAlchemyStatisticsReader:
    """`StatisticsReader`, each call in a read-only session of its own."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def trainees(self, query: StatisticsFilter) -> tuple[TraineeAccount, ...]:
        statement = sa.select(UserRow.id, UserRow.display_name_ru).where(UserRow.role == _TRAINEE)
        if query.trainee_id is not None:
            statement = statement.where(UserRow.id == query.trainee_id)
        if query.group_id is not None:
            statement = statement.where(
                sa.exists().where(
                    TraineeGroupMemberRow.group_id == query.group_id,
                    TraineeGroupMemberRow.user_id == UserRow.id,
                )
            )
        statement = statement.order_by(UserRow.display_name_ru, UserRow.id)
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple(TraineeAccount(UserId(row.id), row.display_name_ru) for row in rows)

    async def accounts(self, user_ids: Sequence[UserId]) -> tuple[TraineeAccount, ...]:
        if not user_ids:
            return ()
        statement = (
            sa.select(UserRow.id, UserRow.display_name_ru)
            .where(UserRow.id.in_(list(user_ids)))
            .order_by(UserRow.display_name_ru, UserRow.id)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple(TraineeAccount(UserId(row.id), row.display_name_ru) for row in rows)

    async def group_exists(self, group_id: TraineeGroupId) -> bool:
        statement = sa.select(sa.exists().where(TraineeGroupRow.id == group_id))
        async with self._session_factory() as session:
            return bool((await session.execute(statement)).scalar_one())

    async def scored_sessions(
        self,
        user_ids: Sequence[UserId],
        *,
        from_utc: datetime | None = None,
        to_utc: datetime | None = None,
    ) -> tuple[ScoredSession, ...]:
        if not user_ids:
            return ()
        async with self._session_factory() as session:
            heads = (await session.execute(_sessions_statement(user_ids, from_utc, to_utc))).all()
            session_ids = [row.id for row in heads]
            if not session_ids:
                return ()
            participants = (await session.execute(_participants_statement(session_ids))).all()
            scores = (await session.execute(_scores_statement(session_ids))).all()
            events = (await session.execute(_events_statement(session_ids))).all()

        by_participants: dict[UUID, list[StatisticsParticipant]] = defaultdict(list)
        for row in participants:
            by_participants[row.session_id].append(
                StatisticsParticipant(
                    user_id=UserId(row.user_id),
                    assigned_role_type=(
                        None if row.assigned_role_type is None else RoleType(row.assigned_role_type)
                    ),
                )
            )
        totals: dict[UUID, _Totals] = defaultdict(_Totals)
        for row in scores:
            totals[row.session_id].add(row)
        by_events: dict[UUID, list[StatisticsEvent]] = defaultdict(list)
        for row in events:
            event_type = _EVENT_TYPES.get(row.event_type)
            if event_type is None:  # pragma: no cover - the query filters on the same values
                continue
            by_events[row.session_id].append(
                StatisticsEvent(
                    event_type=event_type,
                    payload=dict(row.payload or {}),
                    monotonic_offset_ms=int(row.monotonic_offset_ms),
                )
            )

        return tuple(
            ScoredSession(
                session_id=SessionId(head.id),
                lesson_id=None if head.lesson_id is None else LessonId(head.lesson_id),
                session_mode=SessionMode(head.session_mode),
                completed_at=head.completed_at,
                report_released=head.report_released_at is not None,
                scenario_title_ru=head.title,
                scenario_timers=_timers(head.timers),
                participants=tuple(by_participants.get(head.id, ())),
                total_points=totals[head.id].points,
                total_max_points=totals[head.id].max_points,
                failed_by_category=dict(totals[head.id].failed),
                failed_rule_count=sum(totals[head.id].failed.values()),
                critical_error_count=totals[head.id].critical,
                events=tuple(by_events.get(head.id, ())),
            )
            for head in heads
        )


class _Totals:
    """One session's stored sums, folded from its `(category)` rows."""

    def __init__(self) -> None:
        self.points = 0.0
        self.max_points = 0.0
        self.failed: dict[str, int] = {}
        self.critical = 0

    def add(self, row: Any) -> None:
        self.points += float(row.points)
        self.max_points += float(row.max_points)
        if row.failed:
            self.failed[str(row.category)] = int(row.failed)
        self.critical += int(row.critical)


def _timers(raw: Mapping[str, Any] | None) -> CardTimers:
    """`ScenarioVersion.card_timers` from the stored document's `timers` key."""
    return CardTimers.model_validate(raw) if isinstance(raw, Mapping) else DEFAULT_CARD_TIMERS


def _sessions_statement(
    user_ids: Sequence[UserId], from_utc: datetime | None, to_utc: datetime | None
) -> sa.Select[Any]:
    """The `COMPLETED` sessions with stored results one of `user_ids` took part in."""
    sessions = SimulationSessionRow
    statement = (
        sa.select(
            sessions.id,
            sessions.lesson_id,
            sessions.session_mode,
            sessions.completed_at,
            sessions.report_released_at,
            ScenarioVersionRow.title,
            ScenarioVersionRow.content["timers"].label("timers"),
        )
        .join(ScenarioVersionRow, ScenarioVersionRow.id == sessions.scenario_version_id)
        .where(
            sessions.state == _COMPLETED,
            sessions.completed_at.is_not(None),
            sa.exists().where(
                SessionParticipantRow.session_id == sessions.id,
                SessionParticipantRow.user_id.in_(list(user_ids)),
            ),
            sa.exists().where(ScoreResultRow.session_id == sessions.id),
        )
        .order_by(sessions.completed_at, sessions.id)
    )
    if from_utc is not None:
        statement = statement.where(sessions.completed_at >= from_utc)
    if to_utc is not None:
        statement = statement.where(sessions.completed_at < to_utc)
    return statement


def _participants_statement(session_ids: Sequence[UUID]) -> sa.Select[Any]:
    return sa.select(
        SessionParticipantRow.session_id,
        SessionParticipantRow.user_id,
        SessionParticipantRow.assigned_role_type,
    ).where(SessionParticipantRow.session_id.in_(list(session_ids)))


def _scores_statement(session_ids: Sequence[UUID]) -> sa.Select[Any]:
    results = ScoreResultRow
    return (
        sa.select(
            results.session_id,
            results.category,
            sa.func.sum(results.points_awarded).label("points"),
            sa.func.sum(results.max_points).label("max_points"),
            sa.func.count().filter(sa.not_(results.passed)).label("failed"),
            sa.func.count().filter(results.critical_failure).label("critical"),
        )
        .where(results.session_id.in_(list(session_ids)))
        .group_by(results.session_id, results.category)
    )


def _events_statement(session_ids: Sequence[UUID]) -> sa.Select[Any]:
    events = SessionEventRow
    return (
        sa.select(events.session_id, events.event_type, events.payload, events.monotonic_offset_ms)
        .where(
            events.session_id.in_(list(session_ids)),
            events.event_type.in_(_NORM_EVENT_TYPE_VALUES),
        )
        .order_by(events.session_id, events.seq_no)
    )
