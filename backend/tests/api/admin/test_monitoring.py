"""S5 admin monitoring backend over HTTP (I4 E29, `docs/hld/71-i4-wave4.md` §71.6).

`listAuditLog`, `getUsageStats`, `getServerLoad`, `getErrorReport`, `listAdminAlerts`,
`getBackupStatus` — one test class' worth of coverage per operation, driven against the real
application, PostgreSQL and Redis, the same discipline `tests.api.test_audit_log` and
`tests.api.admin.test_clear_inference_fatal` already use for this router.

`api_settings` is overridden (same pattern as `tests.api.admin.test_purge_recordings`) so
`log_dir` and `backup_status_path` live under this test's own `tmp_path` — `getErrorReport` writes
and reads a real `backend.log`, and `getBackupStatus`/`listAdminAlerts` read a real `last.json`,
neither of which may touch anything outside this test.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import redis.asyncio as redis_asyncio
from app.api.container import Container
from app.application.inference_health import AppendInferenceHealthChanged, HealthTransition
from app.config.settings import Settings
from app.domain.common.actors import ActorRef
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.infrastructure.health import VOICE_HEALTH_FATAL_KEY
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api import conftest as _api_fixtures
from tests.api.conftest import auth, create_demo_session, participant

_api_settings_base = _api_fixtures.api_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def api_settings(_api_settings_base: Settings, tmp_path: Path) -> Settings:
    """`log_dir` and `backup_status_path` under this test's own `tmp_path` (see the docstring)."""
    return _api_settings_base.model_copy(
        update={
            "log_dir": str(tmp_path / "logs"),
            "backup_status_path": str(tmp_path / "backups" / "last.json"),
        }
    )


@pytest.fixture(autouse=True)
async def clean_fatal_latch(redis_client: redis_asyncio.Redis) -> AsyncIterator[None]:
    """No `voice:health:fatal` survives into or out of a test in this module."""
    await redis_client.delete(VOICE_HEALTH_FATAL_KEY)
    yield
    await redis_client.delete(VOICE_HEALTH_FATAL_KEY)


def _participants(users: dict[str, UserId]) -> list[dict[str, Any]]:
    return [
        participant(users["trainee1"], "OPERATOR_112"),
        participant(users["trainee2"], "DDS"),
    ]


def _write_backup_status(path: Path, *, finished_at: datetime, status: str = "ok") -> None:
    """A `backups/last.json` shaped as `infra/scripts/backup-once.sh` writes it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ts": finished_at.strftime("%Y%m%dT%H%M%SZ"),
                "status": status,
                "dump_file": "sim-test.dump",
                "dump_size_bytes": 1024,
                "dump_sha256": "0" * 64,
                "recordings_file": "recordings-test.tar.gz",
                "recordings_size_bytes": 2048,
                "recordings_sha256": "1" * 64,
                "error": None if status == "ok" else "simulated failure",
            }
        ),
        encoding="utf-8",
    )


def _write_log_line(log_dir: str, *, level: str, message: str, ts: datetime | None = None) -> None:
    """One `backend.log` JSON line, shaped as `app.infrastructure.logging.JsonFormatter` writes."""
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "ts": (ts or datetime.now(UTC)).isoformat(timespec="milliseconds"),
            "level": level,
            "logger": "app.test",
            "message": message,
            "service": "backend",
        }
    )
    with (directory / "backend.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


async def _append_model_error(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], session_id: str
) -> None:
    event = DomainEvent(
        event_type=EventType.MODEL_ERROR,
        actor=ActorRef(actor_type=ActorType.SYSTEM),
        monotonic_offset_ms=0,
        payload={
            "component": "LLM_GENERATOR",
            "provider": "fake",
            "model": "fake-1",
            "error_code": "TIMEOUT",
            "message": "e29-probe-model-error",
            "recoverable": False,
            "turn_index": None,
        },
    )
    async with unit_of_work() as uow:
        await uow.events.append(SessionId(UUID(session_id)), [event])
        await uow.commit()


# -- listAuditLog ---------------------------------------------------------------------------------


async def test_list_audit_log_pages_admin_only(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    await client.get("/api/v1/auth/me", headers=auth(tokens["trainee1"]))

    response = await client.get(
        "/api/v1/admin/audit-log",
        headers=auth(tokens["admin1"]),
        params={"user_id": str(users["trainee1"]), "limit": 2},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 1
    assert all(item["user_id"] == str(users["trainee1"]) for item in body["items"])


async def test_list_audit_log_is_forbidden_for_non_admin(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.get("/api/v1/admin/audit-log", headers=auth(tokens["instructor1"]))
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


# -- getUsageStats ----------------------------------------------------------------------------


async def test_get_usage_stats_counts_today_s_logins_and_sessions(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """`tokens` already logged in four accounts; one more session is created here."""
    await create_demo_session(client, tokens["instructor1"], demo_version_id, _participants(users))

    response = await client.get("/api/v1/admin/usage-stats", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    days = response.json()["days"]
    today = datetime.now(UTC).date().isoformat()
    today_row = next((day for day in days if day["date"] == today), None)
    assert today_row is not None, days
    assert today_row["logins"] >= 4
    assert today_row["sessions"] >= 1
    assert today_row["active_users"] >= 4


# -- getServerLoad ----------------------------------------------------------------------------


async def test_get_server_load_never_fakes_an_absent_gpu(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """No `voice:health:*` heartbeat is set in this module, so the GPU pair is `null`, not `0`."""
    response = await client.get("/api/v1/admin/server-load", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gpu_memory_used_mb"] is None
    assert body["gpu_memory_total_mb"] is None
    # This test runs on a real Linux host (repo facts), so these are readable, never `0`.
    assert body["cpu_percent"] is not None and 0.0 <= body["cpu_percent"] <= 100.0
    assert body["memory_total_mb"] is not None and body["memory_total_mb"] > 0
    assert body["disk_total_gb"] is not None and body["disk_total_gb"] > 0


async def test_get_server_load_is_forbidden_for_non_admin(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.get("/api/v1/admin/server-load", headers=auth(tokens["trainee1"]))
    assert response.status_code == 403, response.text


# -- getErrorReport ---------------------------------------------------------------------------


async def test_get_error_report_merges_backend_log_and_model_error(
    client: httpx.AsyncClient,
    api_settings: Settings,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    _write_log_line(api_settings.log_dir, level="ERROR", message="e29-probe-backend-log")
    _write_log_line(api_settings.log_dir, level="INFO", message="e29-probe-info-not-included")
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    await _append_model_error(unit_of_work, created["id"])

    response = await client.get("/api/v1/admin/errors", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    sources = {item["source"] for item in items}
    assert "BACKEND_LOG" in sources
    assert "MODEL_ERROR" in sources
    messages = [item["message"] for item in items]
    assert "e29-probe-backend-log" in messages
    assert "e29-probe-info-not-included" not in messages
    model_error = next(item for item in items if item["source"] == "MODEL_ERROR")
    assert model_error["session_id"] == created["id"]
    assert "e29-probe-model-error" in model_error["message"]


# -- listAdminAlerts --------------------------------------------------------------------------


async def test_alerts_are_empty_with_a_fresh_backup_and_no_fatal_latch(
    client: httpx.AsyncClient, api_settings: Settings, tokens: dict[str, str]
) -> None:
    _write_backup_status(Path(api_settings.backup_status_path), finished_at=datetime.now(UTC))

    response = await client.get("/api/v1/admin/alerts", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


async def test_a_stale_backup_is_alerted(
    client: httpx.AsyncClient, api_settings: Settings, tokens: dict[str, str]
) -> None:
    _write_backup_status(
        Path(api_settings.backup_status_path), finished_at=datetime.now(UTC) - timedelta(hours=30)
    )

    response = await client.get("/api/v1/admin/alerts", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    kinds = [item["kind"] for item in response.json()["items"]]
    assert kinds == ["BACKUP_STALE"]


async def test_a_missing_backup_is_alerted_as_stale(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """No `last.json` at all — `api_settings`' default `backup_status_path` is never written."""
    response = await client.get("/api/v1/admin/alerts", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    kinds = [item["kind"] for item in response.json()["items"]]
    assert kinds == ["BACKUP_STALE"]


async def test_a_failed_backup_is_alerted(
    client: httpx.AsyncClient, api_settings: Settings, tokens: dict[str, str]
) -> None:
    _write_backup_status(
        Path(api_settings.backup_status_path), finished_at=datetime.now(UTC), status="failed"
    )

    response = await client.get("/api/v1/admin/alerts", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    kinds = [item["kind"] for item in response.json()["items"]]
    assert kinds == ["BACKUP_FAILED"]


async def test_a_fatal_latch_is_alerted(
    client: httpx.AsyncClient,
    container: Container,
    api_settings: Settings,
    redis_client: redis_asyncio.Redis,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """A fresh backup keeps the backup alerts quiet, so only `INFERENCE_FATAL` is left.

    `since` comes from the most recent FATAL `INFERENCE_HEALTH_CHANGED` of any session
    (`AdminMonitoringReader.latest_fatal_event`), so a real one is appended here rather than
    relying on the "now" fallback.
    """
    _write_backup_status(Path(api_settings.backup_status_path), finished_at=datetime.now(UTC))
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    started = await client.post(
        f"/api/v1/sessions/{created['id']}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    transition = HealthTransition.model_validate_json(
        json.dumps(
            {"service": "llm", "from": "READY", "to": "FATAL", "detail": "CUDA out of memory"}
        )
    )
    appended = await AppendInferenceHealthChanged(container.unit_of_work, container.clock)(
        transition
    )
    assert appended, "the ACTIVE session above should have received the transition"
    await redis_client.set(
        VOICE_HEALTH_FATAL_KEY, json.dumps({"service": "llm", "detail": "CUDA out of memory"})
    )

    response = await client.get("/api/v1/admin/alerts", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    fatal = next((item for item in items if item["kind"] == "INFERENCE_FATAL"), None)
    assert fatal is not None, items
    assert "llm" in fatal["detail_ru"]
    assert fatal["since"] is not None


async def test_list_admin_alerts_is_forbidden_for_non_admin(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.get("/api/v1/admin/alerts", headers=auth(tokens["trainee1"]))
    assert response.status_code == 403, response.text


# -- getBackupStatus --------------------------------------------------------------------------


async def test_get_backup_status_unavailable_without_a_file(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.get("/api/v1/admin/backup-status", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is False
    assert body["finished_at"] is None
    assert body["status"] is None


async def test_get_backup_status_reports_a_written_backup(
    client: httpx.AsyncClient, api_settings: Settings, tokens: dict[str, str]
) -> None:
    finished_at = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
    _write_backup_status(Path(api_settings.backup_status_path), finished_at=finished_at)

    response = await client.get("/api/v1/admin/backup-status", headers=auth(tokens["admin1"]))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is True
    assert body["status"] == "OK"
    assert datetime.fromisoformat(body["finished_at"]) == finished_at
    assert body["database_bytes"] == 1024
    assert body["recordings_bytes"] == 2048


async def test_get_backup_status_is_forbidden_for_non_admin(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.get("/api/v1/admin/backup-status", headers=auth(tokens["trainee1"]))
    assert response.status_code == 403, response.text


async def test_without_a_token_every_operation_is_401(client: httpx.AsyncClient) -> None:
    for path in (
        "/api/v1/admin/audit-log",
        "/api/v1/admin/usage-stats",
        "/api/v1/admin/server-load",
        "/api/v1/admin/errors",
        "/api/v1/admin/alerts",
        "/api/v1/admin/backup-status",
    ):
        response = await client.get(path)
        assert response.status_code == 401, (path, response.text)
