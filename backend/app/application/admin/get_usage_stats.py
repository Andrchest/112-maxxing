"""`getUsageStats` — per-day usage counts (ADMIN, ТЗ ¶206, Q-E14-3's proposed metric set).

`from`/`to` are both optional on the wire (the delta's `FromParam`/`ToParam`); when either is
missing this fills a `DEFAULT_WINDOW_DAYS`-day window ending at `Clock.now()` (a technical choice —
Q-E14-3 confirms only the metric set, not a default window, so this is recorded here rather than
guessed at the router).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.application.ports.admin_monitoring import AdminMonitoringReader, DailyUsage
from app.application.ports.clock import Clock

__all__ = ["DEFAULT_WINDOW_DAYS", "GetUsageStats", "UsageStatsResult"]

DEFAULT_WINDOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class UsageStatsResult:
    """`openapi.yaml`'s `UsageStats`, property names literal."""

    days: tuple[DailyUsage, ...]


class GetUsageStats:
    """ADMIN only. A pure read over E25's `audit_log` plus `simulation_sessions`/`lessons`."""

    def __init__(self, reader: AdminMonitoringReader, clock: Clock) -> None:
        self._reader = reader
        self._clock = clock

    async def __call__(
        self, *, from_ts: datetime | None = None, to_ts: datetime | None = None
    ) -> UsageStatsResult:
        resolved_to = to_ts if to_ts is not None else self._clock.now()
        resolved_from = (
            from_ts if from_ts is not None else resolved_to - timedelta(days=DEFAULT_WINDOW_DAYS)
        )
        days = await self._reader.daily_usage(from_ts=resolved_from, to_ts=resolved_to)
        return UsageStatsResult(days=tuple(days))
