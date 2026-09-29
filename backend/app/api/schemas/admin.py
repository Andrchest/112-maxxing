"""`admin` schemas — `PurgeRecordingsRequest`, `PurgeRecordingsResult` (`openapi.yaml`, §9.2, R8);
plus S5's monitoring reads (I4 E29, `71-i4-wave4.md` §71.6, appended at the end of this module).

`clearInferenceFatal` needs no schema of its own beyond `HealthReadyResponseSchema` (already
`app.api.schemas.health`); this module is `purgeRecordings`'s half only, plus E29's below.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.admin.backup_status import BackupStatusResult
from app.application.admin.get_activity_heatmap import ActivityHeatmapResult
from app.application.admin.get_error_report import ErrorReportItem
from app.application.admin.get_server_load import ServerLoadResult
from app.application.admin.get_usage_stats import UsageStatsResult
from app.application.admin.list_admin_alerts import AdminAlert
from app.application.ports.admin_monitoring import DailyUsage
from app.application.ports.audit_log import AuditAction, AuditOutcome, StoredAuditEntry
from app.application.ports.user_repository import UserRole
from app.application.recording import PurgeRecordingsRequest, PurgeRecordingsResult
from app.domain.common.ids import SessionId

__all__ = [
    "ActivityHeatmapCellSchema",
    "ActivityHeatmapSchema",
    "AdminAlertViewSchema",
    "AdminAlertsSchema",
    "AuditChangeViewSchema",
    "AuditEntryViewSchema",
    "BackupStatusSchema",
    "ErrorRecordViewSchema",
    "ErrorReportSchema",
    "PurgeRecordingsRequestSchema",
    "PurgeRecordingsResultSchema",
    "ServerLoadSchema",
    "UsageDaySchema",
    "UsageStatsSchema",
    "activity_heatmap_schema",
    "admin_alerts_schema",
    "audit_entry_view_schema",
    "backup_status_schema",
    "error_report_schema",
    "purge_recordings_request",
    "purge_recordings_result_schema",
    "server_load_schema",
    "usage_stats_schema",
]


class PurgeRecordingsRequestSchema(ApiModel):
    """`openapi.yaml`'s `PurgeRecordingsRequest`. The whole body is optional on the wire — a bare
    `POST` with no body is the default `dry_run=True` sweep (`Settings.recording_retention_days`,
    no `session_id`) — so the router hands this a schema instance built from `{}` when the request
    carries no body at all, never `None`.
    """

    dry_run: bool = True
    older_than_days: int | None = Field(default=None, ge=0)
    session_id: UUID | None = None


class PurgeRecordingsResultSchema(ApiModel):
    """`openapi.yaml`'s `PurgeRecordingsResult`."""

    dry_run: bool
    retention_days: int = Field(ge=0)
    session_count: int = Field(ge=0)
    segment_count: int = Field(ge=0)
    bytes_freed: int = Field(ge=0)
    purged_at: datetime
    reason: Literal["RETENTION_WINDOW", "MANUAL_REQUEST", "ADMIN_DELETE"]


def purge_recordings_request(schema: PurgeRecordingsRequestSchema) -> PurgeRecordingsRequest:
    """`PurgeRecordingsRequestSchema` -> the application `PurgeRecordingsRequest`."""
    return PurgeRecordingsRequest(
        dry_run=schema.dry_run,
        older_than_days=schema.older_than_days,
        session_id=SessionId(schema.session_id) if schema.session_id is not None else None,
    )


def purge_recordings_result_schema(result: PurgeRecordingsResult) -> PurgeRecordingsResultSchema:
    """The application `PurgeRecordingsResult` -> `PurgeRecordingsResultSchema`."""
    return PurgeRecordingsResultSchema(
        dry_run=result.dry_run,
        retention_days=result.retention_days,
        session_count=result.session_count,
        segment_count=result.segment_count,
        bytes_freed=result.bytes_freed,
        purged_at=result.purged_at,
        reason=result.reason,  # type: ignore[arg-type]  # the use case only ever writes these three
    )


# --- I4 E29 admin monitoring (`71-i4-wave4.md` §71.6) -------------------------------------------
#
# `listAuditLog`, `getUsageStats`, `getServerLoad`, `getErrorReport`, `listAdminAlerts`,
# `getBackupStatus` — ADMIN only, ТЗ ¶205-¶209, ¶216, ¶289, ¶308.


class AuditChangeViewSchema(ApiModel):
    """`openapi.yaml`'s `AuditChangeView` (I7 E43): one field «было → стало»; `before`/`after`
    are any JSON, both `null` for a secret («изменён»)."""

    field: str
    before: Any = None
    after: Any = None


class AuditEntryViewSchema(ApiModel):
    """`openapi.yaml`'s `AuditEntryView` — one `audit_log` row, never a request/response body."""

    id: UUID
    ts: datetime
    user_id: UUID | None
    role: UserRole | None
    action: AuditAction
    operation_id: str | None
    method: str
    path_template: str
    target_ids: dict[str, str]
    status: int
    client_ip: str | None
    outcome: AuditOutcome
    username: str | None = None
    display_name_ru: str | None = None
    changes: list[AuditChangeViewSchema] = Field(default_factory=list)
    """(I7 E43) «было → стало»; empty for an entry that changed nothing."""


def audit_entry_view_schema(stored: StoredAuditEntry) -> AuditEntryViewSchema:
    """`StoredAuditEntry` (E25's `AuditReader.page`) -> `AuditEntryView`."""
    entry = stored.entry
    return AuditEntryViewSchema(
        id=stored.id,
        ts=entry.ts,
        user_id=UUID(str(entry.user_id)) if entry.user_id is not None else None,
        role=entry.role,
        action=entry.action,
        operation_id=entry.operation_id,
        method=entry.method,
        path_template=entry.path_template,
        target_ids=dict(entry.target_ids),
        status=entry.status,
        client_ip=entry.client_ip,
        outcome=entry.outcome,
        username=stored.username,
        display_name_ru=stored.display_name_ru,
        changes=[
            AuditChangeViewSchema(field=change.field, before=change.before, after=change.after)
            for change in entry.changes
        ],
    )


class UsageDaySchema(ApiModel):
    """`openapi.yaml`'s `UsageStats.days` item."""

    date: date
    logins: int = Field(ge=0)
    sessions: int = Field(ge=0)
    lessons: int = Field(ge=0)
    active_users: int = Field(ge=0)


class UsageStatsSchema(ApiModel):
    """`openapi.yaml`'s `UsageStats`."""

    days: list[UsageDaySchema]


def _usage_day_schema(day: DailyUsage) -> UsageDaySchema:
    return UsageDaySchema(
        date=day.day,
        logins=day.logins,
        sessions=day.sessions,
        lessons=day.lessons,
        active_users=day.active_users,
    )


def usage_stats_schema(result: UsageStatsResult) -> UsageStatsSchema:
    """The application `UsageStatsResult` -> `UsageStatsSchema`."""
    return UsageStatsSchema(days=[_usage_day_schema(day) for day in result.days])


# --- I7 E46a: «Активность» weekday × hour heatmap (admin item 6) ----------------------------


class ActivityHeatmapCellSchema(ApiModel):
    """`openapi.yaml`'s `ActivityHeatmapCell` — one non-empty `(weekday, hour)` bucket."""

    weekday: int = Field(ge=1, le=7, description="ISO: 1 = Monday … 7 = Sunday.")
    hour: int = Field(ge=0, le=23)
    session_count: int = Field(ge=0)


class ActivityHeatmapSchema(ApiModel):
    """`openapi.yaml`'s `ActivityHeatmap`. Only non-empty buckets are listed; an absent
    `(weekday, hour)` means zero sessions."""

    cells: list[ActivityHeatmapCellSchema]


def activity_heatmap_schema(result: ActivityHeatmapResult) -> ActivityHeatmapSchema:
    return ActivityHeatmapSchema(
        cells=[
            ActivityHeatmapCellSchema(
                weekday=cell.weekday, hour=cell.hour, session_count=cell.session_count
            )
            for cell in result.cells
        ]
    )


class ServerLoadSchema(ApiModel):
    """`openapi.yaml`'s `ServerLoad`. Every metric is `null`, never `0`, when it cannot be read."""

    sampled_at: datetime
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    memory_used_mb: float | None = Field(default=None, ge=0)
    memory_total_mb: float | None = Field(default=None, ge=0)
    disk_used_gb: float | None = Field(default=None, ge=0)
    disk_total_gb: float | None = Field(default=None, ge=0)
    gpu_memory_used_mb: float | None = Field(default=None, ge=0)
    gpu_memory_total_mb: float | None = Field(default=None, ge=0)


def server_load_schema(result: ServerLoadResult) -> ServerLoadSchema:
    """The application `ServerLoadResult` -> `ServerLoadSchema`."""
    return ServerLoadSchema(
        sampled_at=result.sampled_at,
        cpu_percent=result.cpu_percent,
        memory_used_mb=result.memory_used_mb,
        memory_total_mb=result.memory_total_mb,
        disk_used_gb=result.disk_used_gb,
        disk_total_gb=result.disk_total_gb,
        gpu_memory_used_mb=result.gpu_memory_used_mb,
        gpu_memory_total_mb=result.gpu_memory_total_mb,
    )


class ErrorRecordViewSchema(ApiModel):
    """`openapi.yaml`'s `ErrorRecordView`.

    `VOICE_AGENT_LOG`/`SIP_GATEWAY_LOG` additive, I7 E51 (G6).
    """

    ts: datetime
    source: Literal[
        "BACKEND_LOG", "VOICE_AGENT_LOG", "SIP_GATEWAY_LOG", "MODEL_ERROR", "INFERENCE_FATAL"
    ]
    message: str
    session_id: UUID | None


class ErrorReportSchema(ApiModel):
    """`openapi.yaml`'s `getErrorReport` response — `{items}`, no `total` (the contract's own
    inline object has none)."""

    items: list[ErrorRecordViewSchema]


def _error_record_view_schema(item: ErrorReportItem) -> ErrorRecordViewSchema:
    return ErrorRecordViewSchema(
        ts=item.ts, source=item.source, message=item.message, session_id=item.session_id
    )


def error_report_schema(items: tuple[ErrorReportItem, ...]) -> ErrorReportSchema:
    """The application `GetErrorReport` result -> `ErrorReportSchema`."""
    return ErrorReportSchema(items=[_error_record_view_schema(item) for item in items])


class AdminAlertViewSchema(ApiModel):
    """`openapi.yaml`'s `AdminAlertView`."""

    kind: Literal["INFERENCE_FATAL", "BACKUP_STALE", "BACKUP_FAILED", "LOGIN_FAILURES"]
    since: datetime
    detail_ru: str


class AdminAlertsSchema(ApiModel):
    """`openapi.yaml`'s `listAdminAlerts` response — `{items}`, no `total`."""

    items: list[AdminAlertViewSchema]


def _admin_alert_view_schema(alert: AdminAlert) -> AdminAlertViewSchema:
    return AdminAlertViewSchema(kind=alert.kind, since=alert.since, detail_ru=alert.detail_ru)


def admin_alerts_schema(alerts: tuple[AdminAlert, ...]) -> AdminAlertsSchema:
    """The application `ListAdminAlerts` result -> `AdminAlertsSchema`."""
    return AdminAlertsSchema(items=[_admin_alert_view_schema(alert) for alert in alerts])


class BackupStatusSchema(ApiModel):
    """`openapi.yaml`'s `BackupStatus`."""

    available: bool
    finished_at: datetime | None
    status: Literal["OK", "FAILED"] | None
    database_bytes: int | None = Field(default=None, ge=0)
    recordings_bytes: int | None = Field(default=None, ge=0)
    database_sha256: str | None
    recordings_sha256: str | None


def backup_status_schema(result: BackupStatusResult) -> BackupStatusSchema:
    """The application `BackupStatusResult` -> `BackupStatusSchema`."""
    return BackupStatusSchema(
        available=result.available,
        finished_at=result.finished_at,
        status=result.status,
        database_bytes=result.database_bytes,
        recordings_bytes=result.recordings_bytes,
        database_sha256=result.database_sha256,
        recordings_sha256=result.recordings_sha256,
    )


# --- end I4 E29 -----------------------------------------------------------------------------
