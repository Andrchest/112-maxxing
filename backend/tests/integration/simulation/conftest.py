"""Fixtures for the simulation integration tests (real PostgreSQL, real Redis).

These tests need genuine COMMITs — the whole point of E6-B is that a tick is one transaction and
that a restart reads back what the previous process wrote — so they use `migrated_engine` directly
and clean up with `TRUNCATE ... CASCADE`, exactly like `tests/integration/sessions`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import redis.asyncio as redis_asyncio
from app.config.settings import Settings
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.simulation._support import SimHarness, build_session, truncate_all

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def clean_database(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """Leave the schema empty before and after every test in this package."""
    await truncate_all(migrated_engine)
    yield
    await truncate_all(migrated_engine)


@pytest.fixture
async def harness(migrated_engine: AsyncEngine) -> SimHarness:
    """One committed, `ACTIVE` demo session with a pinned clock at simulated time zero."""
    return await build_session(migrated_engine)


@pytest.fixture
async def redis_client(test_settings: Settings) -> AsyncIterator[redis_asyncio.Redis]:
    """A real Redis client against the compose test instance."""
    client: redis_asyncio.Redis = redis_asyncio.from_url(
        test_settings.redis_url, decode_responses=True
    )
    try:
        yield client
    finally:
        await client.aclose()
