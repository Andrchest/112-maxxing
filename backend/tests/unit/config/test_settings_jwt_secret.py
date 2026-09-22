"""`Settings.jwt_secret`'s minimum-length rule (SPEC §41, E18-A R3/DO item 4)."""

from __future__ import annotations

import pytest
from app.config.settings import Settings

_BASE_KWARGS = {
    "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
    "redis_url": "redis://localhost:56379/0",
    "livekit_url": "ws://localhost:7880",
    "livekit_api_key": "devkey",
    "livekit_api_secret": "devsecret1234567890",
    "llm_base_url": "http://localhost:8080/v1",
}


def test_a_secret_shorter_than_32_bytes_is_refused() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        Settings(jwt_secret="short-secret", **_BASE_KWARGS)  # type: ignore[arg-type]


def test_a_secret_of_exactly_32_bytes_is_accepted() -> None:
    secret = "x" * 32
    settings = Settings(jwt_secret=secret, **_BASE_KWARGS)  # type: ignore[arg-type]
    assert settings.jwt_secret == secret


def test_a_secret_longer_than_32_bytes_is_accepted() -> None:
    settings = Settings(
        jwt_secret="a-perfectly-fine-secret-well-over-the-minimum-length",
        **_BASE_KWARGS,  # type: ignore[arg-type]
    )
    assert len(settings.jwt_secret.encode("utf-8")) > 32
