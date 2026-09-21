"""`/api/v1/health/live` needs no infrastructure at all (SPEC §37, D8).

This test predates E7-A, where `/health/live` still answered `{"status": "ok"}`. E7-A made the
endpoint the `HealthLiveResponse` of `docs/hld/openapi.yaml`, so the assertion moved with it — but
the *claim* being tested is the same one and is worth keeping separate from
`backend/tests/api/test_health.py`: liveness must be answerable with **no database, no Redis and
no probe**.

The container below is built from settings pointing at addresses nothing listens on. If this test
passes, no code path behind `/health/live` touched any of them — which is exactly why an
orchestrator restarting on a liveness failure never restarts a backend whose database merely went
away.
"""

from __future__ import annotations

from app.api.container import Container
from app.api.main import create_app
from app.config.settings import Settings
from fastapi.testclient import TestClient

UNREACHABLE = Settings(
    # Deliberately unreachable: nothing must connect while serving liveness.
    database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:1/nothing",
    redis_url="redis://127.0.0.1:1/0",
    jwt_secret="unit-test-secret",
    livekit_url="ws://127.0.0.1:1",
    livekit_api_key="k",
    livekit_api_secret="s" * 20,
    llm_base_url="http://127.0.0.1:1/v1",
    runner_enabled=False,
    cors_allow_origins=[],
)


def test_health_live_needs_no_infrastructure() -> None:
    """`200 HealthLiveResponse`, with every backing service unreachable."""
    client = TestClient(create_app(Container(UNREACHABLE)))

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "LIVE"
    assert body["uptime_seconds"] >= 0
    assert set(body) == {"status", "version", "uptime_seconds"}


def test_health_live_needs_no_bearer_token() -> None:
    """`security: []` in `openapi.yaml`: a health check that needs a token is useless."""
    client = TestClient(create_app(Container(UNREACHABLE)))

    assert client.get("/api/v1/health/live").status_code == 200
