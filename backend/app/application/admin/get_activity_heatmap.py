"""`getActivityHeatmap` — weekday × hour of started sessions (ADMIN, I7 E46a, owner item 6).

A pure read over `simulation_sessions.started_at`, already stored for every session that reached
`READY`'s next state (D8) — no evaluator, no window: the shape of when the system gets used across
its whole history, the same "derived, not stored" discipline `GetUsageStats` and
`ListAdminAlerts` follow.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.ports.admin_monitoring import ActivityHeatmapCell, AdminMonitoringReader

__all__ = ["ActivityHeatmapResult", "GetActivityHeatmap"]


@dataclass(frozen=True, slots=True)
class ActivityHeatmapResult:
    """`openapi.yaml`'s `ActivityHeatmap`, property names literal."""

    cells: tuple[ActivityHeatmapCell, ...]


class GetActivityHeatmap:
    """ADMIN only (the router's own `AdminDep` gate, like `GetUsageStats`)."""

    def __init__(self, reader: AdminMonitoringReader) -> None:
        self._reader = reader

    async def __call__(self) -> ActivityHeatmapResult:
        cells = await self._reader.activity_heatmap()
        return ActivityHeatmapResult(cells=tuple(cells))
