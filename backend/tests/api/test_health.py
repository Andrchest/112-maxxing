"""`getHealthLive` / `getHealthReady` (SPEC §37, D8)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import redis.asyncio as redis_asyncio
from app.api.container import REQUIRED_HEALTH_COMPONENTS, Container
from app.api.main import create_app
from app.api.routers.health import overall_status
from app.application.ports.health_probe import ComponentReading
from app.config.settings import Settings
from app.domain.enums import HealthStatus
from app.infrastructure.health import PlaceholderHealthProbe, PostgresHealthProbe, RedisHealthProbe
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

#: A port nothing listens on. Deliberately not 8000/8001 (another project owns those) and not
#: 8100 (this API's own default) — 59099 is in the ephemeral range and unbound.
CLOSED_PORT = 59099


async def test_live_needs_no_token_and_touches_nothing(client: httpx.AsyncClient) -> None:
    """`/health/live` answers `HealthLiveResponse` with no `Authorization` header."""
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "LIVE"
    assert body["version"] == "1.0.0"
    assert body["uptime_seconds"] >= 0
    assert set(body) == {"status", "version", "uptime_seconds"}


async def test_ready_with_everything_reachable_is_still_not_ready(
    client: httpx.AsyncClient,
) -> None:
    """PostgreSQL and Redis are up, the five placeholders are not — so `overall` is `NOT_READY`.

    That is the documented state of a box with no voice-agent: SPEC §37 wants the start button
    disabled, and `503` is what disables it. `postgres` and `redis` still report `READY`, which is
    how an operator sees that the gap is the inference stack and not the database.
    """
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["overall"] == "NOT_READY"
    assert body["required_components"] == list(REQUIRED_HEALTH_COMPONENTS)
    assert body["require_inference_ready"] is False
    by_component = {item["component"]: item for item in body["components"]}
    assert by_component["postgres"]["status"] == "READY"
    assert by_component["redis"]["status"] == "READY"
    for component in ("livekit", "llm", "asr", "tts", "vad"):
        assert by_component[component]["status"] == "NOT_READY"
        assert "TODO(" in (by_component[component]["detail"] or "")


async def test_ready_reports_a_failing_redis_probe_instead_of_failing(
    container: Container, api_settings: Settings, migrated_engine: AsyncEngine
) -> None:
    """A Redis pointed at a closed port degrades the answer; it never 500s (§40.6)."""
    unreachable: redis_asyncio.Redis = redis_asyncio.from_url(
        f"redis://localhost:{CLOSED_PORT}/0", decode_responses=True
    )
    try:
        probes = [
            PostgresHealthProbe(migrated_engine),
            RedisHealthProbe(unreachable),
            PlaceholderHealthProbe("livekit", "E11"),
        ]
        degraded = Container(
            api_settings,
            engine=migrated_engine,
            session_factory=container.session_factory,
            redis=container.redis,
            unit_of_work=container.unit_of_work,
            health_probes=probes,
            owns_engine=False,
            owns_redis=False,
        )
        transport = httpx.ASGITransport(app=create_app(degraded))
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            response = await client.get("/api/v1/health/ready")
    finally:
        await unreachable.aclose()

    assert response.status_code == 503
    body = response.json()
    assert body["overall"] == "NOT_READY"
    by_component = {item["component"]: item for item in body["components"]}
    assert by_component["postgres"]["status"] == "READY"
    assert by_component["redis"]["status"] == "NOT_READY"
    assert by_component["redis"]["detail"]


def _reading(component: str, status: HealthStatus) -> ComponentReading:
    return ComponentReading(component=component, status=status, checked_at=datetime.now(UTC))


def test_overall_is_ready_only_when_every_required_component_is() -> None:
    """The fold of `HealthReadyResponse.overall`, stated as four cases."""
    required = ("postgres", "redis")

    ready = [_reading("postgres", HealthStatus.READY), _reading("redis", HealthStatus.READY)]
    assert overall_status(ready, required=required) is HealthStatus.READY

    warming = [_reading("postgres", HealthStatus.READY), _reading("redis", HealthStatus.WARMING)]
    assert overall_status(warming, required=required) is HealthStatus.WARMING

    not_ready = [
        _reading("postgres", HealthStatus.NOT_READY),
        _reading("redis", HealthStatus.WARMING),
    ]
    assert overall_status(not_ready, required=required) is HealthStatus.NOT_READY

    # FATAL wins even on a component nobody required: a latched fatal condition must not be
    # hideable by a restart loop (§40.6, `voice:health:fatal`).
    fatal = [*ready, _reading("llm", HealthStatus.FATAL)]
    assert overall_status(fatal, required=required) is HealthStatus.FATAL


def test_a_missing_required_component_is_not_ready() -> None:
    """A required component with no probe at all reports `NOT_READY`, never `READY`."""
    assert (
        overall_status([_reading("postgres", HealthStatus.READY)], required=("postgres", "redis"))
        is HealthStatus.NOT_READY
    )
