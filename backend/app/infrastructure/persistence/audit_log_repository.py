"""`SqlAlchemyAuditLog` — `AuditRecorder` and `AuditReader` over `audit_log` (I4 E25, HLD 20
§20.6, `71-i4-wave4.md` §71.2, D31).

Two rules shape the writer, the same two that shape `PgMetricsRecorder`:

1. **Its own transaction, and a short one.** `record` runs after the response has been sent, so it
   never joins a request's Unit of Work — there is none left to join — and one INSERT is all it
   does. It does not go through the Unit of Work at all: an audit row publishes nothing (D5's
   publish-after-commit is about session events) and belongs to no aggregate.
2. **Every failure is logged and swallowed.** A write that raised would turn a request that has
   already completed into an exception in the ASGI stack. The failure lands in the backend's JSON
   log at level ERROR, which is exactly what E29's error report reads.

The table is append-only (`audit_log_append_only`, §20.9): this adapter has no UPDATE or DELETE,
and the trigger refuses one from anywhere else.

I7 E43: `changes` (`0019_audit_changes`) is written in the same single INSERT — `NULL` for an
entry that changed nothing — and `AuditFilter.with_changes` reads only rows that carry one.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.audit_changes import AuditChange
from app.application.ports.audit_log import (
    AuditAction,
    AuditEntry,
    AuditFilter,
    AuditOutcome,
    AuditPage,
    StoredAuditEntry,
)
from app.application.ports.user_repository import UserRole
from app.db.models.events import AuditLog as AuditLogRow
from app.db.models.reference import User as UserRow
from app.domain.common.ids import UserId

__all__ = ["SqlAlchemyAuditLog"]

logger = logging.getLogger(__name__)

_AUDIT_LOG = AuditLogRow.__table__
_USERS = UserRow.__table__


class SqlAlchemyAuditLog:
    """`AuditRecorder` + `AuditReader`, each call in a session of its own."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, entry: AuditEntry) -> None:
        """INSERT one row. A failure is logged (never with the entry's values) and swallowed."""
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(sa.insert(AuditLogRow).values(**_row_of(entry)))
        except Exception:
            logger.exception(
                "writing an audit entry (%s %s) failed; the request is unaffected",
                entry.action.value,
                entry.operation_id or entry.path_template,
            )

    async def page(self, audit_filter: AuditFilter) -> AuditPage:
        """The entries matching `audit_filter`, newest first, and their total."""
        conditions: list[sa.ColumnElement[bool]] = []
        if audit_filter.user_id is not None:
            conditions.append(_AUDIT_LOG.c.user_id == audit_filter.user_id)
        if audit_filter.action is not None:
            conditions.append(_AUDIT_LOG.c.action == audit_filter.action.value)
        if audit_filter.from_ts is not None:
            conditions.append(_AUDIT_LOG.c.ts >= audit_filter.from_ts)
        if audit_filter.to_ts is not None:
            conditions.append(_AUDIT_LOG.c.ts < audit_filter.to_ts)
        if audit_filter.with_changes:
            conditions.append(_AUDIT_LOG.c.changes.is_not(None))

        # The acting account's login and name are joined in at read time (I6 FIX1): the journal
        # shows who acted, not only the role. LEFT JOIN — an anonymous row has no account.
        rows_query = (
            sa.select(
                _AUDIT_LOG,
                _USERS.c.username.label("actor_username"),
                _USERS.c.display_name_ru.label("actor_display_name_ru"),
            )
            .select_from(_AUDIT_LOG.outerjoin(_USERS, _USERS.c.id == _AUDIT_LOG.c.user_id))
            .where(*conditions)
            .order_by(_AUDIT_LOG.c.ts.desc(), _AUDIT_LOG.c.id.desc())
            .limit(audit_filter.limit)
            .offset(audit_filter.offset)
        )
        total_query = sa.select(sa.func.count()).select_from(_AUDIT_LOG).where(*conditions)
        async with self._session_factory() as session:
            rows = (await session.execute(rows_query)).mappings().all()
            total = int((await session.execute(total_query)).scalar_one())
        return AuditPage(items=tuple(_stored_of(row) for row in rows), total=total)


def _row_of(entry: AuditEntry) -> dict[str, Any]:
    return {
        "ts": entry.ts,
        "user_id": entry.user_id,
        "role": entry.role.value if entry.role is not None else None,
        "action": entry.action.value,
        "operation_id": entry.operation_id,
        "method": entry.method,
        "path_template": entry.path_template,
        "target_ids": dict(entry.target_ids),
        "status": entry.status,
        "client_ip": entry.client_ip,
        "outcome": entry.outcome.value,
        "changes": (
            [
                {"field": change.field, "before": change.before, "after": change.after}
                for change in entry.changes
            ]
            if entry.changes
            # SQL NULL, not JSON `null`: `with_changes` filters on `IS NOT NULL`.
            else sa.null()
        ),
    }


def _stored_of(row: Any) -> StoredAuditEntry:
    return StoredAuditEntry(
        id=row["id"],
        entry=AuditEntry(
            ts=row["ts"],
            user_id=UserId(row["user_id"]) if row["user_id"] is not None else None,
            role=UserRole(row["role"]) if row["role"] is not None else None,
            action=AuditAction(row["action"]),
            operation_id=row["operation_id"],
            method=row["method"],
            path_template=row["path_template"],
            target_ids={str(key): str(value) for key, value in row["target_ids"].items()},
            status=row["status"],
            client_ip=row["client_ip"],
            outcome=AuditOutcome(row["outcome"]),
            changes=_changes_of(row["changes"]),
        ),
        username=row["actor_username"],
        display_name_ru=row["actor_display_name_ru"],
    )


def _changes_of(value: Any) -> tuple[AuditChange, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        AuditChange(field=str(item["field"]), before=item.get("before"), after=item.get("after"))
        for item in value
        if isinstance(item, dict) and "field" in item
    )
