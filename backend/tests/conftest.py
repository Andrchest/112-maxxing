"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from app.config.settings import Settings


@pytest.fixture
def test_settings() -> Settings:
    """A `Settings` instance built from the test environment (see `Makefile`)."""
    return Settings(
        database_url=os.environ.get(
            "SIM_DATABASE_URL", "postgresql+asyncpg://sim:sim@localhost:55432/sim_test"
        ),
        redis_url=os.environ.get("SIM_REDIS_URL", "redis://localhost:56379/0"),
        jwt_secret=os.environ.get("SIM_JWT_SECRET", "test-only-secret"),
        require_inference_ready=False,
        livekit_url=os.environ.get("SIM_LIVEKIT_URL", "ws://localhost:7880"),
        livekit_api_key=os.environ.get("SIM_LIVEKIT_API_KEY", "devkey"),
        livekit_api_secret=os.environ.get("SIM_LIVEKIT_API_SECRET", "devsecret1234567890"),
        llm_base_url=os.environ.get("SIM_LLM_BASE_URL", "http://localhost:8080/v1"),
    )


@pytest.fixture(autouse=True)
def _clean_cwd() -> Iterator[None]:
    """Guard against tests that `os.chdir()` leaking into later tests."""
    original = os.getcwd()
    yield
    os.chdir(original)
