"""`admin` router — the operator-only maintenance surface of `openapi.yaml`'s `admin` tag.

Two operations live under `/api/v1/admin`, and they have nothing in common except who may call
them: `clearInferenceFatal` (E18-B, below) and `purgeRecordings` (E18-D, its own marked section at
the end of this module). They share one `APIRouter` because they share one path prefix, not
because they share a concern.

`clearInferenceFatal` deletes the un-expiring `voice:health:fatal` latch of
`60-inference-ops.md` §4.3 — the key that exists so "a restart loop cannot make a fatal condition
look transient". Three properties make it safe to expose:

* it **touches no session state** (`openapi.yaml`: "Touches no session state"). It deletes one
  Redis key and publishes one transition; `simulation_sessions.state` is not written, no use case
  of `app.application.sessions` is called, and SPEC §39's "never silently reset the simulation"
  holds by construction;
* it does not make anything `READY`. The response is the readiness snapshot **after** clearing,
  and every inference component in it still reads its own `voice:health:{service}` heartbeat: a
  service whose warm-up has not run since the fatal condition still reports `NOT_READY`;
* clearing publishes on `voice:health`, which is what the subscriber turns into the
  `INFERENCE_HEALTH_CHANGED` the contract's `x-emits` promises. The router does not append the
  event itself — the same code path serves a voice-agent transition and an admin's click.

**Roles.** Both operations are `ADMIN` only (manager ruling R4 of epic E18). `openapi.yaml`'s
*summary line* for `clearInferenceFatal` says "INSTRUCTOR / ADMIN"; its machine-readable part
defines only `401` and `403`, so the narrower gate satisfies the contract's responses while the
prose and the ruling disagree. The disagreement is reported, not worked around — see the E18-B
task report's "HLD gaps".
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import ContainerDep
from app.api.routers.health import readiness_snapshot
from app.api.schemas.admin import (
    AdminAlertsSchema,
    AuditEntryViewSchema,
    BackupStatusSchema,
    ErrorReportSchema,
    PurgeRecordingsRequestSchema,
    PurgeRecordingsResultSchema,
    ServerLoadSchema,
    UsageStatsSchema,
    admin_alerts_schema,
    audit_entry_view_schema,
    backup_status_schema,
    error_report_schema,
    purge_recordings_request,
    purge_recordings_result_schema,
    server_load_schema,
    usage_stats_schema,
)
from app.api.schemas.auth import (
    PasswordResetRequestSchema,
    UserAccountI4Schema,
    UserCreateRequestSchema,
    UserUpdateRequestSchema,
    user_account_i4_schema,
)
from app.api.schemas.common import PageSchema
from app.api.schemas.health import HealthReadyResponseSchema
from app.api.security import require_roles
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.audit_log import AuditAction, AuditFilter
from app.application.ports.user_repository import UserRole
from app.domain.common.ids import UserId

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

AdminDep = Annotated[AuthenticatedUser, Depends(require_roles(UserRole.ADMIN))]
"""ADMIN only, for both operations of this router (manager ruling R4 of epic E18; see the
module docstring's note on `openapi.yaml`'s wider summary line)."""


@router.post(
    "/inference/clear-fatal",
    operation_id="clearInferenceFatal",
    summary="Clear a latched FATAL inference state (ADMIN).",
    response_model=HealthReadyResponseSchema,
    status_code=200,
)
async def clear_inference_fatal(
    container: ContainerDep, _user: AdminDep
) -> HealthReadyResponseSchema:
    """Delete `voice:health:fatal`, announce it, and answer with the readiness snapshot after.

    The snapshot is re-probed rather than patched: clearing the latch removes the reason every
    inference probe was reporting `FATAL`, and what they report instead is whatever their own
    heartbeat says at this instant — which is the only honest answer (SPEC §37).
    """
    await container.inference_fatal.clear()
    return await readiness_snapshot(container)


# --- recordings (E18-D) ---
#
# `purgeRecordings` (`POST /api/v1/admin/recordings/purge`, ADMIN only) belongs here, on this
# router, sharing `AdminDep`. E18-B created the module and left this section empty on purpose so
# that the two tasks never touch the same lines.


@router.post(
    "/recordings/purge",
    operation_id="purgeRecordings",
    summary="Purge recordings past the retention window (ADMIN).",
    response_model=PurgeRecordingsResultSchema,
    status_code=200,
)
async def purge_recordings(
    container: ContainerDep,
    user: AdminDep,
    body: PurgeRecordingsRequestSchema | None = None,
) -> PurgeRecordingsResultSchema:
    """`python -m app.cli purge_recordings`'s other front door — same use case, same rule
    (`app.application.recording.PurgeRecordings`, this task's ruling R8). A bare `POST` with no
    body is the default `dry_run=True` sweep over `Settings.recording_retention_days`.

    I4 E29 (§71.6, ТЗ ¶216): a non-dry-run purge raises `BackupRequiredError` — rendered as
    `409 BACKUP_REQUIRED` by `app.api.errors.install_exception_handlers` like any other
    `DomainError` — unless E26's `backups/last.json` reports a successful backup newer than every
    row about to be purged; `dry_run: true` is never refused.
    """
    request = purge_recordings_request(body or PurgeRecordingsRequestSchema())
    result = await container.purge_recordings()(request, actor=user)
    return purge_recordings_result_schema(result)


# --- accounts (I4 E28, `71-i4-wave4.md` §71.5) --------------------------------------------------
#
# `createUser`, `updateUser`, `resetUserPassword` — ТЗ ¶195-¶197, ADMIN only, sharing `AdminDep`.
# `updateUser`'s single PATCH body is split across two use cases (`UpdateUser` for role / display
# name, `SetActive` for `is_active`); both run in this one request, so it still leaves exactly one
# `audit_log` row (E25's middleware records the HTTP request, not the calls inside it). Every
# guard the use cases raise (`USERNAME_TAKEN`, `SELF_MODIFICATION_FORBIDDEN`,
# `LAST_ADMIN_REQUIRED`) is a `DomainError` with its own `code`, rendered by
# `app.api.errors.install_exception_handlers` like any other.


@router.post(
    "/users",
    operation_id="createUser",
    summary="Create an account of any role (ADMIN) — ТЗ ¶195.",
    response_model=UserAccountI4Schema,
    status_code=201,
)
async def create_user(
    body: UserCreateRequestSchema, container: ContainerDep, _user: AdminDep
) -> UserAccountI4Schema:
    created = await container.create_user()(
        username=body.username,
        display_name_ru=body.display_name_ru,
        user_role=body.user_role,
        password=body.password,
    )
    return user_account_i4_schema(created)


@router.patch(
    "/users/{user_id}",
    operation_id="updateUser",
    summary="Change role, display name or block/unblock (ADMIN) — ТЗ ¶196, ¶197.",
    response_model=UserAccountI4Schema,
    status_code=200,
)
async def update_user(
    user_id: UUID,
    body: UserUpdateRequestSchema,
    container: ContainerDep,
    user: AdminDep,
) -> UserAccountI4Schema:
    """Every field is optional (`minProperties: 1`, enforced by the request schema).

    `is_active` is applied last, after the role/display-name change, so a body that both demotes
    and blocks the same account is checked and written consistently: `UpdateUser` sees the account
    as it was before this request, `SetActive` as it is after `UpdateUser` ran.
    """
    target = UserId(user_id)
    updated = None
    if body.display_name_ru is not None or body.user_role is not None:
        updated = await container.update_user()(
            target,
            actor_id=user.user_id,
            display_name_ru=body.display_name_ru,
            user_role=body.user_role,
        )
    if body.is_active is not None:
        updated = await container.set_active()(
            target, actor_id=user.user_id, is_active=body.is_active
        )
    assert updated is not None, "the schema's own validator requires at least one field"
    return user_account_i4_schema(updated)


@router.post(
    "/users/{user_id}/password",
    operation_id="resetUserPassword",
    summary="Set a new password for an account (ADMIN).",
    status_code=204,
    response_class=Response,
)
async def reset_user_password(
    user_id: UUID, body: PasswordResetRequestSchema, container: ContainerDep, _user: AdminDep
) -> Response:
    """The password is never echoed, logged or audited in clear (E25 records the operation, not
    the body)."""
    await container.reset_password()(UserId(user_id), password=body.password)
    return Response(status_code=204)


# --- I4 E29 admin monitoring (`71-i4-wave4.md` §71.6) --------------------------------------------
#
# `listAuditLog`, `getUsageStats`, `getServerLoad`, `getErrorReport`, `listAdminAlerts`,
# `getBackupStatus` — ADMIN only, sharing `AdminDep`. ТЗ ¶205-¶209, ¶216, ¶289, ¶308.

AuditLogPageSchema = PageSchema[AuditEntryViewSchema]


@router.get(
    "/audit-log",
    operation_id="listAuditLog",
    summary="Page the audit log written by E25 (ADMIN) — ТЗ ¶205, ¶296.",
    response_model=AuditLogPageSchema,
    status_code=200,
)
async def list_audit_log(
    container: ContainerDep,
    _user: AdminDep,
    user_id: Annotated[UUID | None, Query()] = None,
    action: Annotated[AuditAction | None, Query()] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditLogPageSchema:
    """No bound left unset here: an absent `user_id`/`action`/`from`/`to` leaves that filter off
    (`AuditFilter`'s own defaults, `app.application.ports.audit_log`)."""
    page = await container.audit_reader.page(
        AuditFilter(
            user_id=UserId(user_id) if user_id is not None else None,
            action=action,
            from_ts=from_,
            to_ts=to,
            limit=limit,
            offset=offset,
        )
    )
    return AuditLogPageSchema(
        items=[audit_entry_view_schema(item) for item in page.items], total=page.total
    )


@router.get(
    "/usage-stats",
    operation_id="getUsageStats",
    summary="Per-day usage counts (ADMIN) — ТЗ ¶206; metric set to be confirmed (Q-E14-3).",
    response_model=UsageStatsSchema,
    status_code=200,
)
async def get_usage_stats(
    container: ContainerDep,
    _user: AdminDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> UsageStatsSchema:
    """An absent `from`/`to` defaults to `GetUsageStats.DEFAULT_WINDOW_DAYS` ending now (a
    technical choice — see that module; Q-E14-3 confirms only the metric set)."""
    result = await container.get_usage_stats()(from_ts=from_, to_ts=to)
    return usage_stats_schema(result)


@router.get(
    "/server-load",
    operation_id="getServerLoad",
    summary="CPU / memory / disk (+ GPU when visible) of the server (ADMIN) — ТЗ ¶208, ¶289.",
    response_model=ServerLoadSchema,
    status_code=200,
)
async def get_server_load(container: ContainerDep, _user: AdminDep) -> ServerLoadSchema:
    """A point-in-time sample; nothing here is stored. Every metric is `null`, never `0`, when it
    cannot be read (SPEC §27's rule, reused)."""
    result = await container.get_server_load()()
    return server_load_schema(result)


@router.get(
    "/errors",
    operation_id="getErrorReport",
    summary="Errors and failures over a period (ADMIN) — ТЗ ¶207.",
    response_model=ErrorReportSchema,
    status_code=200,
)
async def get_error_report(
    container: ContainerDep,
    _user: AdminDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> ErrorReportSchema:
    """Merges the backend JSON log (level >= ERROR) with `MODEL_ERROR` and FATAL
    `INFERENCE_HEALTH_CHANGED` session events, newest first."""
    items = await container.get_error_report()(from_ts=from_, to_ts=to, limit=limit)
    return error_report_schema(items)


@router.get(
    "/alerts",
    operation_id="listAdminAlerts",
    summary="Current administrator alerts, derived not stored (ADMIN) — ТЗ ¶308.",
    response_model=AdminAlertsSchema,
    status_code=200,
)
async def list_admin_alerts(container: ContainerDep, _user: AdminDep) -> AdminAlertsSchema:
    """An empty `items` means nothing to report."""
    alerts = await container.list_admin_alerts()()
    return admin_alerts_schema(alerts)


@router.get(
    "/backup-status",
    operation_id="getBackupStatus",
    summary="The last backup as recorded by E26's `backups/last.json` (ADMIN) — ТЗ ¶143, ¶216.",
    response_model=BackupStatusSchema,
    status_code=200,
)
async def get_backup_status(container: ContainerDep, _user: AdminDep) -> BackupStatusSchema:
    """`available: false` when `backups/last.json` is missing or unreadable."""
    result = await container.get_backup_status()()
    return backup_status_schema(result)


# --- end I4 E29 -----------------------------------------------------------------------------------


# --- I5 E37: settings XML export (Q-E16-1) -------------------------------------------------------


@router.get(
    "/settings/export",
    operation_id="exportSettingsXml",
    summary="The effective, non-secret settings as XML (ADMIN) — Q-E16-1.",
    status_code=200,
    response_class=Response,
)
async def export_settings_xml(container: ContainerDep, _user: AdminDep) -> Response:
    """`<settings version="1"><setting name="SIM_…">value</setting>…</settings>`. Every secret
    (passwords, keys, tokens, the JWT secret, DB URLs with credentials) is omitted entirely, never
    masked-in-place (SPEC §41) — `app.config.settings_xml.SECRET_FIELD_NAMES`. Import is CLI only
    (`make settings-import`, `docs/RUNBOOK.md`), never this API."""
    body = container.export_settings_xml()
    return Response(
        content=body,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="settings.xml"'},
    )


# --- end I5 E37 -----------------------------------------------------------------------------------
