"""`AuditRecorder` / `AuditReader` ports — the cross-cutting audit of user actions (I4 E25,
`docs/hld/71-i4-wave4.md` §71.2, HLD 20 §20.6 `audit_log`, D31).

The audit is not a domain concern: `session_events` stay the in-session record (D5), and this port
covers everything a user does through the API — every authenticated request, every refused one
(`401`/`403`), every WebSocket connect and every login attempt (ТЗ ¶296, ¶128, ¶213).

What an entry holds is fixed by the table (HLD 20 §20.6): who (`user_id`, `role`), what
(`action`, `operation_id`, `method`, `path_template`, `target_ids`), how it ended (`status`,
`outcome`) and from where (`client_ip`). **Never a request or response body** — passwords and
personal data do not reach this port, which is why `AuditEntry` has no field that could carry one.
For `LOGIN_*` the attempted username is `target_ids["username"]`, never the password.

I7 E43 (Q-E15-3) adds `changes`: the «было → стало» list a mutating use case reported through
`AuditChangeCollector` (`app.application.ports.audit_changes`) — field values, never a body, and a
secret only ever as «изменён» with both values `None`.

Two ports, one adapter (`app.infrastructure.persistence.audit_log_repository`): the API writes
through `AuditRecorder` (the audit middleware and `loginUser`), and E29's `listAuditLog` reads
through `AuditReader`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.application.ports.audit_changes import AuditChange
from app.application.ports.user_repository import UserRole
from app.domain.common.ids import UserId

__all__ = [
    "AuditAction",
    "AuditEntry",
    "AuditFilter",
    "AuditOutcome",
    "AuditPage",
    "AuditReader",
    "AuditRecorder",
    "StoredAuditEntry",
]


class AuditAction(str, Enum):
    """`audit_log.action` (HLD 20 §20.6 CHECK list; the delta's `AuditAction`)."""

    HTTP_REQUEST = "HTTP_REQUEST"
    LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED"
    LOGIN_FAILED = "LOGIN_FAILED"
    ACCESS_DENIED = "ACCESS_DENIED"
    WS_CONNECTED = "WS_CONNECTED"
    #: I7 E51 (G5, ТЗ ¶295): a login rejected by `LoginGuard` before `Login` ever saw the password —
    #: `target_ids["username"]` only, never the password, same as `LOGIN_FAILED`.
    LOGIN_THROTTLED = "LOGIN_THROTTLED"


class AuditOutcome(str, Enum):
    """`audit_log.outcome` (HLD 20 §20.6 CHECK list; the delta's `AuditOutcome`)."""

    OK = "OK"
    DENIED = "DENIED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class AuditEntry:
    """One audit record to write. `user_id`/`role` are `None` for an unauthenticated request."""

    ts: datetime
    action: AuditAction
    method: str
    path_template: str
    status: int
    outcome: AuditOutcome
    user_id: UserId | None = None
    role: UserRole | None = None
    operation_id: str | None = None
    target_ids: Mapping[str, str] = field(default_factory=dict)
    client_ip: str | None = None
    changes: tuple[AuditChange, ...] = ()
    """(I7 E43) What the request changed, «было → стало»; empty for a read or a refusal."""


@dataclass(frozen=True)
class StoredAuditEntry:
    """An `AuditEntry` as read back, with its row id.

    `username`/`display_name_ru` (I6 FIX1) name the acting account — resolved at read time by a
    join on `entry.user_id`, never stored in the row; both `None` when there is no acting account
    (an anonymous or failed login, whose attempted username stays in `target_ids["username"]`).
    """

    id: UUID
    entry: AuditEntry
    username: str | None = None
    display_name_ru: str | None = None


@dataclass(frozen=True)
class AuditFilter:
    """`listAuditLog`'s query: by user, action and period (`from` inclusive, `to` exclusive)."""

    user_id: UserId | None = None
    action: AuditAction | None = None
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    limit: int = 100
    offset: int = 0
    with_changes: bool = False
    """(I7 E43) «Только с изменениями»: only rows that carry a non-empty `changes`."""


@dataclass(frozen=True)
class AuditPage:
    """One page of entries, newest first, and the total matching the filter."""

    items: Sequence[StoredAuditEntry]
    total: int


@runtime_checkable
class AuditRecorder(Protocol):
    """Append one entry. A failure is logged and swallowed by the adapter: the audit runs after
    the response, and it must never turn a completed request into an error."""

    async def record(self, entry: AuditEntry) -> None:
        """Write `entry` in a transaction of its own."""
        ...


@runtime_checkable
class AuditReader(Protocol):
    """Page the audit log (E29's read side)."""

    async def page(self, audit_filter: AuditFilter) -> AuditPage:
        """The entries matching `audit_filter`, newest first."""
        ...
