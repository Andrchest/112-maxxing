"""`clearInferenceFatal` over HTTP, and the readiness it answers with (E18-B, HLD 60 §4.3).

Every test here writes real `voice:health:*` keys into the compose test Redis and drives the real
`VoiceHealthProbe` / `RedisInferenceReadiness` / `RedisInferenceFatalLatch` adapters — the whole
point of E18-B is that the backend reads readiness from reality, so a suite that stubbed the probes
would prove nothing.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import redis.asyncio as redis_asyncio
from app.api.container import Container
from app.api.main import create_app
from app.application.ports.health_probe import ComponentReading
from app.domain.common.ids import ScenarioVersionId, UserId
from app.domain.enums import HealthStatus
from app.infrastructure.health import (
    INFERENCE_SERVICES,
    VOICE_HEALTH_FATAL_KEY,
    PostgresHealthProbe,
    RedisHealthProbe,
    VoiceHealthProbe,
    voice_health_key,
)

from tests.api.conftest import auth, create_demo_session, participant

pytestmark = pytest.mark.integration

_KEYS = (VOICE_HEALTH_FATAL_KEY, *(voice_health_key(name) for name in INFERENCE_SERVICES))


def _frame(state: str, **overrides: object) -> str:
    payload: dict[str, object] = {
        "state": state,
        "profile": "DEV_3060TI",
        "provider": "fake",
        "model_version": "fake-1",
        "updated_at": datetime.now(UTC).isoformat(),
        "detail": None,
        "warmup_ms": 12,
    }
    payload.update(overrides)
    return json.dumps(payload)


class _ReadyLiveKitProbe:
    """`livekit` as `READY`, because no SFU runs in the gate (D13) and `livekit` is *required*.

    Without it `overall` could never be `READY` here and the four heartbeats this module is about
    would be untestable. `backend/tests/api/test_health.py` owns the real `livekit` reading.
    """

    @property
    def component(self) -> str:
        return "livekit"

    async def check(self) -> ComponentReading:
        return ComponentReading(
            component="livekit",
            status=HealthStatus.READY,
            detail=None,
            checked_at=datetime.now(UTC),
        )


@pytest.fixture
async def ready_client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    """A client whose only non-real probe is `livekit` (see `_ReadyLiveKitProbe`)."""
    probes = [
        PostgresHealthProbe(container.engine),
        RedisHealthProbe(container.redis),
        _ReadyLiveKitProbe(),
        *(VoiceHealthProbe(container.redis, service) for service in INFERENCE_SERVICES),
    ]
    live = Container(
        container.settings,
        engine=container.engine,
        session_factory=container.session_factory,
        redis=container.redis,
        publisher=container.publisher,
        unit_of_work=container.unit_of_work,
        hasher=container.hasher,
        tokens=container.tokens,
        inference=container.inference,
        health_probes=probes,
        owns_engine=False,
        owns_redis=False,
    )
    transport = httpx.ASGITransport(app=create_app(live))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as http_client:
        yield http_client


@pytest.fixture(autouse=True)
async def clean_voice_health(redis_client: redis_asyncio.Redis) -> AsyncIterator[None]:
    """No `voice:health:*` key survives into or out of a test in this module."""
    await redis_client.delete(*_KEYS)
    yield
    await redis_client.delete(*_KEYS)


async def _all_ready(client: redis_asyncio.Redis) -> None:
    for service in INFERENCE_SERVICES:
        await client.set(voice_health_key(service), _frame("READY"), ex=15)


def _participants(users: dict[str, UserId]) -> list[dict[str, Any]]:
    return [
        participant(users["trainee1"], "OPERATOR_112"),
        participant(users["trainee2"], "DDS"),
    ]


def _strict(container: Container) -> Container:
    """The same container with `REQUIRE_INFERENCE_READY=true` and the **real** readiness adapter."""
    return Container(
        container.settings.model_copy(update={"require_inference_ready": True}),
        engine=container.engine,
        session_factory=container.session_factory,
        redis=container.redis,
        unit_of_work=container.unit_of_work,
        hasher=container.hasher,
        tokens=container.tokens,
        owns_engine=False,
        owns_redis=False,
    )


# -- readiness through the real adapter --------------------------------------------------------


async def test_four_ready_heartbeats_make_overall_ready_and_let_a_session_start(
    container: Container,
    client: httpx.AsyncClient,
    ready_client: httpx.AsyncClient,
    redis_client: redis_asyncio.Redis,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """The positive case, end to end: four `READY` frames ⇒ `200 READY` and `startSession` passes.

    This is the one test that proves the producer/consumer contract of §4.3 both ways: nothing but
    the four Redis keys changes, and `REQUIRE_INFERENCE_READY=true` with the real
    `RedisInferenceReadiness` stops refusing.
    """
    await _all_ready(redis_client)
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )

    ready = await ready_client.get("/api/v1/health/ready")
    assert ready.status_code == 200, ready.text
    body = ready.json()
    assert body["overall"] == "READY"
    by_component = {item["component"]: item for item in body["components"]}
    for service in INFERENCE_SERVICES:
        assert by_component[service]["status"] == "READY"
        assert by_component[service]["provider"] == "fake"

    transport = httpx.ASGITransport(app=create_app(_strict(container)))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as strict_client:
        started = await strict_client.post(
            f"/api/v1/sessions/{created['id']}/start", headers=auth(tokens["instructor1"])
        )
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "ACTIVE"


async def test_one_warming_service_is_not_ready(
    ready_client: httpx.AsyncClient, redis_client: redis_asyncio.Redis
) -> None:
    """`WARMING` is not `READY`: `overall` is `WARMING` and the endpoint answers `503`."""
    await _all_ready(redis_client)
    await redis_client.set(voice_health_key("tts"), _frame("WARMING"), ex=15)

    response = await ready_client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["overall"] == "WARMING"


async def test_a_fatal_latch_makes_overall_fatal_and_refuses_a_start(
    container: Container,
    client: httpx.AsyncClient,
    redis_client: redis_asyncio.Redis,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """`voice:health:fatal` beats four `READY` frames: `overall` FATAL, `startSession` `503`.

    "A latched FATAL […] so that a restart loop cannot make a fatal condition look transient"
    (§4.3). The session is untouched and still `READY` afterwards — a refused start writes
    nothing (SPEC §39).
    """
    await _all_ready(redis_client)
    await redis_client.set(
        VOICE_HEALTH_FATAL_KEY, json.dumps({"service": "llm", "detail": "CUDA out of memory"})
    )
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["overall"] == "FATAL"

    transport = httpx.ASGITransport(app=create_app(_strict(container)))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as strict_client:
        refused = await strict_client.post(
            f"/api/v1/sessions/{created['id']}/start", headers=auth(tokens["instructor1"])
        )
    assert refused.status_code == 503, refused.text
    assert refused.json()["code"] == "INFERENCE_NOT_READY"

    still_ready = await client.get(
        f"/api/v1/sessions/{created['id']}", headers=auth(tokens["instructor1"])
    )
    assert still_ready.json()["state"] == "READY"


# -- clearInferenceFatal -----------------------------------------------------------------------


async def test_an_admin_clears_the_latch_and_gets_the_snapshot_after(
    ready_client: httpx.AsyncClient, redis_client: redis_asyncio.Redis, tokens: dict[str, str]
) -> None:
    """ADMIN gets `200 HealthReadyResponse`, the key is gone, and the state is re-probed.

    The four heartbeats are still `READY`, so the snapshot after clearing is `READY` — the
    operation clears a latch, it does not assert a readiness of its own.
    """
    await _all_ready(redis_client)
    await redis_client.set(VOICE_HEALTH_FATAL_KEY, json.dumps({"service": "llm"}))

    response = await ready_client.post(
        "/api/v1/admin/inference/clear-fatal", headers=auth(tokens["admin1"])
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["overall"] == "READY"
    assert set(body) == {
        "overall",
        "components",
        "required_components",
        "require_inference_ready",
        "model_profile",
    }
    assert await redis_client.exists(VOICE_HEALTH_FATAL_KEY) == 0


async def test_clearing_does_not_invent_readiness(
    client: httpx.AsyncClient, redis_client: redis_asyncio.Redis, tokens: dict[str, str]
) -> None:
    """No heartbeat at all: clearing leaves `NOT_READY`, never `READY` (SPEC §37)."""
    await redis_client.set(VOICE_HEALTH_FATAL_KEY, json.dumps({"service": "llm"}))

    response = await client.post(
        "/api/v1/admin/inference/clear-fatal", headers=auth(tokens["admin1"])
    )

    assert response.status_code == 200, response.text
    assert response.json()["overall"] == "NOT_READY"
    assert await redis_client.exists(VOICE_HEALTH_FATAL_KEY) == 0


@pytest.mark.parametrize("username", ["instructor1", "trainee1"])
async def test_a_non_admin_is_refused_and_the_latch_survives(
    client: httpx.AsyncClient,
    redis_client: redis_asyncio.Redis,
    tokens: dict[str, str],
    username: str,
) -> None:
    """`403 FORBIDDEN_FOR_ROLE` for every non-ADMIN role, and nothing is cleared (ruling R4)."""
    await redis_client.set(VOICE_HEALTH_FATAL_KEY, json.dumps({"service": "llm"}))

    response = await client.post(
        "/api/v1/admin/inference/clear-fatal", headers=auth(tokens[username])
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"
    assert await redis_client.exists(VOICE_HEALTH_FATAL_KEY) == 1


async def test_without_a_token_it_is_401(
    client: httpx.AsyncClient, redis_client: redis_asyncio.Redis
) -> None:
    """`openapi.yaml` gives the operation a `401`; the latch survives an anonymous attempt."""
    await redis_client.set(VOICE_HEALTH_FATAL_KEY, json.dumps({"service": "llm"}))

    response = await client.post("/api/v1/admin/inference/clear-fatal")

    assert response.status_code == 401, response.text
    assert await redis_client.exists(VOICE_HEALTH_FATAL_KEY) == 1
