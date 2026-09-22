"""`getHealthLive` / `getHealthReady` (SPEC §37, D8)."""

from __future__ import annotations

from collections.abc import AsyncIterator
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
from app.infrastructure.health import (
    INFERENCE_SERVICES,
    VOICE_HEALTH_FATAL_KEY,
    PostgresHealthProbe,
    RedisHealthProbe,
    voice_health_key,
)
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

#: A port nothing listens on. Deliberately not 8000/8001 (another project owns those) and not
#: 8100 (this API's own default) — 59099 is in the ephemeral range and unbound.
CLOSED_PORT = 59099


class _StubProbe:
    """A `HealthProbe` with a fixed answer — for the cases where the point is the *fold*."""

    def __init__(self, component: str, status: HealthStatus) -> None:
        self._component = component
        self._status = status

    @property
    def component(self) -> str:
        return self._component

    async def check(self) -> ComponentReading:
        return ComponentReading(
            component=self._component,
            status=self._status,
            detail=None,
            checked_at=datetime.now(UTC),
        )


@pytest.fixture
async def no_voice_health(redis_client: redis_asyncio.Redis) -> AsyncIterator[None]:
    """Guarantee that no `voice:health:*` key exists around a test.

    The compose test Redis is shared across the suite, so a heartbeat another test wrote would
    otherwise decide this one's verdict. Cleared on the way in *and* out.
    """
    keys = [VOICE_HEALTH_FATAL_KEY, *(voice_health_key(name) for name in INFERENCE_SERVICES)]
    await redis_client.delete(*keys)
    yield
    await redis_client.delete(*keys)


async def test_live_needs_no_token_and_touches_nothing(client: httpx.AsyncClient) -> None:
    """`/health/live` answers `HealthLiveResponse` with no `Authorization` header."""
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "LIVE"
    assert body["version"] == "1.0.0"
    assert body["uptime_seconds"] >= 0
    assert set(body) == {"status", "version", "uptime_seconds"}


async def test_ready_without_a_voice_agent_heartbeat_is_not_ready(
    client: httpx.AsyncClient, no_voice_health: None
) -> None:
    """PostgreSQL and Redis are up, no voice-agent is writing heartbeats — `overall` is NOT_READY.

    The E18-B truth that replaced the placeholder one: `llm`/`asr`/`tts`/`vad` are real probes over
    `voice:health:{service}` now, and a **missing key is `NOT_READY`** with the reason
    `60-inference-ops.md` §4.3 and `openapi.yaml` both spell out. Nothing names an owing epic any
    more, and nothing invents `READY` on a box with no inference stack — SPEC §37 wants the start
    button disabled, and `503` is what disables it.
    """
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["overall"] == "NOT_READY"
    assert body["required_components"] == list(REQUIRED_HEALTH_COMPONENTS)
    assert body["require_inference_ready"] is False
    assert body["model_profile"] == "DEV_3060TI", "the active profile's name (E18-A, §2)"
    by_component = {item["component"]: item for item in body["components"]}
    assert by_component["postgres"]["status"] == "READY"
    assert by_component["redis"]["status"] == "READY"
    for component in INFERENCE_SERVICES:
        assert by_component[component]["status"] == "NOT_READY"
        assert by_component[component]["detail"] == "no heartbeat from voice-agent"
        assert "TODO(" not in (by_component[component]["detail"] or "")
    # `livekit` is a real probe since E11, so its reading depends on whether a developer happens
    # to have `make dev-infra-up` running. Either reading is correct; what must be true is that it
    # is no longer a placeholder naming an owing epic, and that it never says READY without one.
    livekit = by_component["livekit"]
    assert livekit["status"] in {"READY", "NOT_READY"}
    assert "TODO(" not in (livekit["detail"] or "")
    if livekit["status"] == "NOT_READY":
        assert livekit["detail"]


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
            _StubProbe("livekit", HealthStatus.READY),
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
