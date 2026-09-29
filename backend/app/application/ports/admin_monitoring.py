"""`AdminMonitoringReader` / `ServerHeartbeatReader` ports — S5's read side (I4 E29,
`docs/hld/71-i4-wave4.md` §71.6).

Two ports, because they read two different things `audit_log` (E25) and `session_events` do not
offer a query for on their own:

* `AdminMonitoringReader` — per-day usage counts, `MODEL_ERROR`/FATAL `INFERENCE_HEALTH_CHANGED`
  events across *every* session (not one), and bursts of `LOGIN_FAILED` by the same username.
  Implemented by `app.infrastructure.persistence.admin_monitoring_repository` over SQLAlchemy —
  each method its own session (like `SqlAlchemyAuditLog`), never the caller's Unit of Work;
* `ServerHeartbeatReader` — the voice-agent's `voice:health:*` Redis keys `getServerLoad`'s GPU
  reading and `listAdminAlerts`'s `INFERENCE_FATAL` both need. `app.application` may not import
  `redis` itself (D2), so this is a port even though the adapter is a thin Redis read. Implemented
  by `app.infrastructure.health.server_load.RedisServerHeartbeat`.

Nothing here is faked when it is absent: SPEC §27's "a metric is never invented" rule, reused —
`GpuLoad.used_mb`/`total_mb` are `None`, never `0`, and `FatalLatch.latched` is `False` rather than
guessed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

__all__ = [
    "ActivityHeatmapCell",
    "AdminMonitoringReader",
    "DailyUsage",
    "ErrorSource",
    "FatalLatch",
    "GpuLoad",
    "LoginFailureBurst",
    "ServerHeartbeatReader",
    "SessionErrorEvent",
]

ErrorSource = Literal["MODEL_ERROR", "INFERENCE_FATAL"]


@dataclass(frozen=True, slots=True)
class DailyUsage:
    """One row of `getUsageStats` (ТЗ ¶206; the proposed metric set, Q-E14-3)."""

    day: date
    logins: int
    sessions: int
    lessons: int
    active_users: int


@dataclass(frozen=True, slots=True)
class ActivityHeatmapCell:
    """One `(weekday, hour)` bucket of `getActivityHeatmap` (I7 E46a, admin item 6): sessions
    *started* (`simulation_sessions.started_at`), bucketed in Moscow wall time (`MOSCOW_TZ`,
    `app.application.ports.report_exporter` — the same zone every export's own "Сформировано"
    stamp already reads; manager follow-up: admins read this heatmap as local hours). `weekday` is
    ISO (1 = Monday … 7 = Sunday) *in Moscow time*. Only non-empty buckets are returned; an absent
    `(weekday, hour)` means zero sessions."""

    weekday: int
    hour: int
    session_count: int


@dataclass(frozen=True, slots=True)
class SessionErrorEvent:
    """One `MODEL_ERROR` or FATAL `INFERENCE_HEALTH_CHANGED`, read across every session."""

    ts: datetime
    source: ErrorSource
    message: str
    session_id: UUID


@dataclass(frozen=True, slots=True)
class LoginFailureBurst:
    """`username` failed to log in `count` times since `since` (§71.6's `LOGIN_FAILURES` alert)."""

    username: str
    count: int
    since: datetime


@dataclass(frozen=True, slots=True)
class GpuLoad:
    """`getServerLoad`'s GPU pair — both `None` when no heartbeat carries them (today, F-23)."""

    used_mb: float | None
    total_mb: float | None


@dataclass(frozen=True, slots=True)
class FatalLatch:
    """`voice:health:fatal` as `listAdminAlerts` needs it: whether it is set, and a Russian detail
    for the alert (empty when `latched` is `False`)."""

    latched: bool
    detail_ru: str


@runtime_checkable
class AdminMonitoringReader(Protocol):
    """Cross-session reads over `audit_log` and `session_events` (E29's own queries)."""

    async def daily_usage(self, *, from_ts: datetime, to_ts: datetime) -> Sequence[DailyUsage]:
        """One row per calendar day in `[from_ts, to_ts)`, oldest first."""
        ...

    async def activity_heatmap(self) -> Sequence[ActivityHeatmapCell]:
        """(I7 E46a) Every `(weekday, hour)` bucket with at least one started session, across
        every `simulation_sessions.started_at` on record — no window (the admin heatmap's own
        reading: a shape of when the system is used, not a dated report)."""
        ...

    async def session_error_events(
        self, *, from_ts: datetime, to_ts: datetime, limit: int
    ) -> Sequence[SessionErrorEvent]:
        """`MODEL_ERROR` + FATAL `INFERENCE_HEALTH_CHANGED`, merged, newest first, `limit` rows."""
        ...

    async def latest_fatal_event(self) -> SessionErrorEvent | None:
        """The most recent FATAL `INFERENCE_HEALTH_CHANGED` of any session, or `None`.

        `listAdminAlerts`' `INFERENCE_FATAL.since`: the latch itself (`voice:health:fatal`) carries
        no timestamp (`docs/hld/60-inference-ops.md` §4.3 fixes only `{service, detail}`), so the
        alert's `since` falls back to "now" when no session ever recorded the transition.
        """
        ...

    async def login_failure_bursts(
        self, *, since: datetime, threshold: int
    ) -> Sequence[LoginFailureBurst]:
        """Every username with `>= threshold` `LOGIN_FAILED` audit rows at or after `since`."""
        ...


@runtime_checkable
class ServerHeartbeatReader(Protocol):
    """The voice-agent heartbeat half of `getServerLoad` / `listAdminAlerts` (Redis
    `voice:health:*`, `docs/hld/60-inference-ops.md` §4.3). Never raises (same rule as
    `HealthProbe`): an unreachable Redis reads as absent, not as an error."""

    async def gpu_load(self) -> GpuLoad:
        """The first `voice:health:{service}` frame that carries `gpu_memory_{used,total}_mb`,
        or both `None` when none does."""
        ...

    async def fatal_latch(self) -> FatalLatch:
        """Whether `voice:health:fatal` is set right now, with a Russian detail."""
        ...
