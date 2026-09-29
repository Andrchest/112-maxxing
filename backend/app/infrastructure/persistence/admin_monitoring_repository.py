"""`SqlAlchemyAdminMonitoring` — `AdminMonitoringReader` over `audit_log`, `simulation_sessions`,
`lessons` and `session_events` (I4 E29, `docs/hld/71-i4-wave4.md` §71.6).

Same discipline as `SqlAlchemyAuditLog` (`app.infrastructure.persistence.audit_log_repository`):
every method opens its own session and never joins the caller's Unit of Work, because these are
cross-cutting admin reads, not part of any request's own transaction. `session_events` is read
directly (not through `EventStore`, whose methods are all scoped to one `session_id`) — the same
choice `docs/hld/puml/i4-audit-components.puml` draws as `admin ..> evt`.

Every timestamp bucket is computed in UTC explicitly (`date_trunc('day', … AT TIME ZONE 'UTC')`),
never the session's own timezone, so a day boundary means the same instant regardless of how the
database connection is configured.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.admin_monitoring import (
    ActivityHeatmapCell,
    DailyUsage,
    LoginFailureBurst,
    SessionErrorEvent,
)
from app.application.ports.report_exporter import MOSCOW_TZ
from app.db.models.events import AuditLog as AuditLogRow
from app.db.models.events import SessionEvent as SessionEventRow
from app.db.models.session import Lesson as LessonRow
from app.db.models.session import SimulationSession as SimulationSessionRow

__all__ = ["SqlAlchemyAdminMonitoring"]

_AUDIT_LOG = AuditLogRow.__table__
_SESSIONS = SimulationSessionRow.__table__
_LESSONS = LessonRow.__table__
_EVENTS = SessionEventRow.__table__


def _day_of(column: sa.ColumnElement[datetime]) -> sa.ColumnElement[datetime]:
    """`date_trunc('day', column AT TIME ZONE 'UTC')` — a UTC calendar day, connection-timezone
    independent."""
    return sa.func.date_trunc("day", sa.func.timezone("UTC", column))


class SqlAlchemyAdminMonitoring:
    """`AdminMonitoringReader`, each call in a session of its own."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def daily_usage(self, *, from_ts: datetime, to_ts: datetime) -> Sequence[DailyUsage]:
        async with self._session_factory() as session:
            logins_by_day = await self._counts(
                session,
                _AUDIT_LOG,
                _day_of(_AUDIT_LOG.c.ts),
                sa.and_(
                    _AUDIT_LOG.c.action == "LOGIN_SUCCEEDED",
                    _AUDIT_LOG.c.ts >= from_ts,
                    _AUDIT_LOG.c.ts < to_ts,
                ),
            )
            active_by_day = await self._counts(
                session,
                _AUDIT_LOG,
                _day_of(_AUDIT_LOG.c.ts),
                sa.and_(
                    _AUDIT_LOG.c.user_id.is_not(None),
                    _AUDIT_LOG.c.ts >= from_ts,
                    _AUDIT_LOG.c.ts < to_ts,
                ),
                distinct_column=_AUDIT_LOG.c.user_id,
            )
            sessions_by_day = await self._counts(
                session,
                _SESSIONS,
                _day_of(_SESSIONS.c.created_at),
                sa.and_(_SESSIONS.c.created_at >= from_ts, _SESSIONS.c.created_at < to_ts),
            )
            lessons_by_day = await self._counts(
                session,
                _LESSONS,
                _day_of(_LESSONS.c.created_at),
                sa.and_(_LESSONS.c.created_at >= from_ts, _LESSONS.c.created_at < to_ts),
            )

        days = sorted(
            {
                *logins_by_day,
                *active_by_day,
                *sessions_by_day,
                *lessons_by_day,
            }
        )
        return tuple(
            DailyUsage(
                day=day,
                logins=logins_by_day.get(day, 0),
                sessions=sessions_by_day.get(day, 0),
                lessons=lessons_by_day.get(day, 0),
                active_users=active_by_day.get(day, 0),
            )
            for day in days
        )

    async def activity_heatmap(self) -> Sequence[ActivityHeatmapCell]:
        """(I7 E46a) `EXTRACT(ISODOW/HOUR FROM started_at AT TIME ZONE 'Europe/Moscow')`, grouped
        — Moscow wall time (manager follow-up: admins read this as local hours, and every other
        export's own stamp — `generated_at_moscow`, `MOSCOW_TZ` — already reads the same zone),
        never UTC. `_day_of` above stays UTC-explicit on purpose (a day boundary there means the
        same instant everywhere); this bucket means "what an admin in Moscow would call it"."""
        moscow_started = sa.func.timezone(MOSCOW_TZ.key, _SESSIONS.c.started_at)
        weekday_expr = sa.cast(sa.func.extract("isodow", moscow_started), sa.Integer)
        hour_expr = sa.cast(sa.func.extract("hour", moscow_started), sa.Integer)
        query = (
            sa.select(
                weekday_expr.label("weekday"),
                hour_expr.label("hour"),
                sa.func.count().label("n"),
            )
            .select_from(_SESSIONS)
            .where(_SESSIONS.c.started_at.is_not(None))
            .group_by(weekday_expr, hour_expr)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(query)).all()
        return tuple(
            ActivityHeatmapCell(
                weekday=int(row.weekday), hour=int(row.hour), session_count=int(row.n)
            )
            for row in rows
        )

    async def _counts(
        self,
        session: AsyncSession,
        table: sa.FromClause,
        day_expr: sa.ColumnElement[datetime],
        where: sa.ColumnElement[bool],
        *,
        distinct_column: sa.ColumnElement[object] | None = None,
    ) -> dict[date, int]:
        count_expr = (
            sa.func.count(sa.distinct(distinct_column))
            if distinct_column is not None
            else sa.func.count()
        )
        query = (
            sa.select(day_expr.label("day"), count_expr.label("n"))
            .select_from(table)
            .where(where)
            .group_by(day_expr)
        )
        rows = (await session.execute(query)).all()
        return {row.day.date(): int(row.n) for row in rows}

    async def session_error_events(
        self, *, from_ts: datetime, to_ts: datetime, limit: int
    ) -> Sequence[SessionErrorEvent]:
        async with self._session_factory() as session:
            model_errors = await session.execute(
                sa.select(
                    _EVENTS.c.session_id,
                    _EVENTS.c.timestamp_utc,
                    _EVENTS.c.payload["message"].astext.label("message"),
                )
                .where(
                    _EVENTS.c.event_type == "MODEL_ERROR",
                    _EVENTS.c.timestamp_utc >= from_ts,
                    _EVENTS.c.timestamp_utc < to_ts,
                )
                .order_by(_EVENTS.c.timestamp_utc.desc())
                .limit(limit)
            )
            fatal_transitions = await session.execute(
                sa.select(
                    _EVENTS.c.session_id,
                    _EVENTS.c.timestamp_utc,
                    _EVENTS.c.payload["component"].astext.label("component"),
                    _EVENTS.c.payload["detail"].astext.label("detail"),
                )
                .where(
                    _EVENTS.c.event_type == "INFERENCE_HEALTH_CHANGED",
                    _EVENTS.c.payload["new_status"].astext == "FATAL",
                    _EVENTS.c.timestamp_utc >= from_ts,
                    _EVENTS.c.timestamp_utc < to_ts,
                )
                .order_by(_EVENTS.c.timestamp_utc.desc())
                .limit(limit)
            )
        items = [
            SessionErrorEvent(
                ts=row.timestamp_utc,
                source="MODEL_ERROR",
                message=row.message or "",
                session_id=row.session_id,
            )
            for row in model_errors
        ] + [
            SessionErrorEvent(
                ts=row.timestamp_utc,
                source="INFERENCE_FATAL",
                message=f"{row.component}: {row.detail}" if row.component else (row.detail or ""),
                session_id=row.session_id,
            )
            for row in fatal_transitions
        ]
        items.sort(key=lambda item: item.ts, reverse=True)
        return tuple(items[:limit])

    async def latest_fatal_event(self) -> SessionErrorEvent | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    sa.select(
                        _EVENTS.c.session_id,
                        _EVENTS.c.timestamp_utc,
                        _EVENTS.c.payload["component"].astext.label("component"),
                        _EVENTS.c.payload["detail"].astext.label("detail"),
                    )
                    .where(
                        _EVENTS.c.event_type == "INFERENCE_HEALTH_CHANGED",
                        _EVENTS.c.payload["new_status"].astext == "FATAL",
                    )
                    .order_by(_EVENTS.c.timestamp_utc.desc())
                    .limit(1)
                )
            ).first()
        if row is None:
            return None
        message = f"{row.component}: {row.detail}" if row.component else (row.detail or "")
        return SessionErrorEvent(
            ts=row.timestamp_utc,
            source="INFERENCE_FATAL",
            message=message,
            session_id=row.session_id,
        )

    async def login_failure_bursts(
        self, *, since: datetime, threshold: int
    ) -> Sequence[LoginFailureBurst]:
        username_expr = _AUDIT_LOG.c.target_ids["username"].astext
        async with self._session_factory() as session:
            rows = await session.execute(
                sa.select(
                    username_expr.label("username"),
                    sa.func.count().label("n"),
                    sa.func.min(_AUDIT_LOG.c.ts).label("since"),
                )
                .where(_AUDIT_LOG.c.action == "LOGIN_FAILED", _AUDIT_LOG.c.ts >= since)
                .group_by(username_expr)
                .having(sa.func.count() >= threshold)
            )
        return tuple(
            LoginFailureBurst(username=row.username, count=int(row.n), since=row.since)
            for row in rows
            if row.username is not None
        )
