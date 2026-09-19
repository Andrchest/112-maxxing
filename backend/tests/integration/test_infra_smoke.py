"""Smoke test proving the test infra (`infra/docker-compose.test.yml`, started by `make infra-up`)
is reachable: connects to PostgreSQL and Redis from `Settings` built off the test environment and
runs a trivial round-trip against each.
"""

from __future__ import annotations

import pytest
import redis.asyncio as redis_asyncio
from app.config.settings import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


async def test_postgres_select_1(test_settings: Settings) -> None:
    engine = create_async_engine(test_settings.database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await engine.dispose()


async def test_redis_ping(test_settings: Settings) -> None:
    client = redis_asyncio.from_url(test_settings.redis_url)
    try:
        assert await client.ping() is True
    finally:
        await client.aclose()
