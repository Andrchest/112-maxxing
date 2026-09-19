from __future__ import annotations

from app.api.main import create_app
from fastapi.testclient import TestClient


def test_health_live_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
