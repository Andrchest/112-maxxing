"""`listAdminAlerts` — current administrator alerts, derived, not stored (ADMIN, ТЗ ¶308).

Three sources, `docs/hld/puml/i4-backup-restore.puml`'s note and §71.6's content list:

* `INFERENCE_FATAL` — `voice:health:fatal` is set right now (`ServerHeartbeatReader.fatal_latch`).
  `since` is the most recent FATAL `INFERENCE_HEALTH_CHANGED` of any session when one exists,
  else "now" (the latch itself carries no timestamp, `docs/hld/60-inference-ops.md` §4.3);
* `BACKUP_STALE` / `BACKUP_FAILED` — `backups/last.json` is missing/unreadable, older than
  `STALE_AFTER_HOURS` (26h, the same number `infra/scripts/backup_status.py`'s `make
  backup-verify` uses, so an operator sees the same verdict both ways), or its own `status` is not
  `OK`;
* `LOGIN_FAILURES` — a username with at least `LOGIN_FAILURE_THRESHOLD` `LOGIN_FAILED` audit rows
  in the last `LOGIN_FAILURE_WINDOW_MINUTES` (both a technical choice recorded here: the design
  names the alert but not a threshold, and this item is not in E29's "Tests owed").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from app.application.admin.backup_status import read_backup_status
from app.application.ports.admin_monitoring import AdminMonitoringReader, ServerHeartbeatReader
from app.application.ports.clock import Clock

__all__ = ["AdminAlert", "ListAdminAlerts"]

#: `docs/hld/puml/i4-backup-restore.puml`: "BACKUP_STALE when last.json is older than 26 h".
STALE_AFTER_HOURS = 26.0
#: Technical choice (not stated by the design; §71.6 names the alert kind, not a threshold).
LOGIN_FAILURE_THRESHOLD = 5
LOGIN_FAILURE_WINDOW_MINUTES = 15

AlertKind = Literal["INFERENCE_FATAL", "BACKUP_STALE", "BACKUP_FAILED", "LOGIN_FAILURES"]

_BACKUP_MISSING_RU = "Резервная копия ещё ни разу не создавалась."
_BACKUP_FAILED_RU = "Последняя попытка резервного копирования завершилась ошибкой."


def _backup_stale_ru(hours: float) -> str:
    return f"Последняя резервная копия создана {hours:.1f} ч назад (> {STALE_AFTER_HOURS:.0f} ч)."


def _login_failures_ru(username: str, count: int) -> str:
    return f"{count} неудачных попыток входа подряд для «{username}»."


@dataclass(frozen=True, slots=True)
class AdminAlert:
    """`openapi.yaml`'s `AdminAlertView`, property names literal."""

    kind: AlertKind
    since: datetime
    detail_ru: str


class ListAdminAlerts:
    """ADMIN only. Nothing here is stored — every call recomputes the current alert set."""

    def __init__(
        self,
        reader: AdminMonitoringReader,
        heartbeat: ServerHeartbeatReader,
        clock: Clock,
        *,
        backup_status_path: Path,
        stale_after_hours: float = STALE_AFTER_HOURS,
        login_failure_threshold: int = LOGIN_FAILURE_THRESHOLD,
        login_failure_window_minutes: int = LOGIN_FAILURE_WINDOW_MINUTES,
    ) -> None:
        self._reader = reader
        self._heartbeat = heartbeat
        self._clock = clock
        self._backup_status_path = backup_status_path
        self._stale_after_hours = stale_after_hours
        self._login_failure_threshold = login_failure_threshold
        self._login_failure_window_minutes = login_failure_window_minutes

    async def __call__(self) -> tuple[AdminAlert, ...]:
        now = self._clock.now()
        alerts: list[AdminAlert] = []

        latch = await self._heartbeat.fatal_latch()
        if latch.latched:
            latest = await self._reader.latest_fatal_event()
            alerts.append(
                AdminAlert(
                    kind="INFERENCE_FATAL",
                    since=latest.ts if latest is not None else now,
                    detail_ru=latch.detail_ru,
                )
            )

        alerts.extend(self._backup_alert(now))

        bursts = await self._reader.login_failure_bursts(
            since=now - timedelta(minutes=self._login_failure_window_minutes),
            threshold=self._login_failure_threshold,
        )
        for burst in bursts:
            alerts.append(
                AdminAlert(
                    kind="LOGIN_FAILURES",
                    since=burst.since,
                    detail_ru=_login_failures_ru(burst.username, burst.count),
                )
            )

        return tuple(alerts)

    def _backup_alert(self, now: datetime) -> list[AdminAlert]:
        status = read_backup_status(self._backup_status_path)
        if not status.available:
            return [AdminAlert(kind="BACKUP_STALE", since=now, detail_ru=_BACKUP_MISSING_RU)]
        if status.status == "FAILED":
            return [
                AdminAlert(
                    kind="BACKUP_FAILED",
                    since=status.finished_at or now,
                    detail_ru=_BACKUP_FAILED_RU,
                )
            ]
        assert status.finished_at is not None  # `available and status == "OK"` always sets it
        age_hours = (now - status.finished_at).total_seconds() / 3600.0
        if age_hours > self._stale_after_hours:
            return [
                AdminAlert(
                    kind="BACKUP_STALE",
                    since=status.finished_at,
                    detail_ru=_backup_stale_ru(age_hours),
                )
            ]
        return []
