"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator, Iterator

import pytest
from app.config.settings import Settings
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

#: `gw<N>` -> `(N % 15) + 1`, as `pytest-xdist` names its worker processes.
_XDIST_WORKER = re.compile(r"^gw(\d+)$")


def _redis_url_for_worker(url: str) -> str:
    """Give this xdist worker its own Redis logical database (E11-0).

    PostgreSQL isolation comes for free — `migrated_engine` below creates a randomly named
    database per (session-scoped, so per worker process) fixture instance — but Redis has no
    equivalent of "create me a throwaway database": the compose instance is shared with whatever
    else the developer is running (see `Makefile`), so every worker must pick a different one of
    Redis's 16 logical databases by index instead.

    `PYTEST_XDIST_WORKER` is unset when pytest is not running under `-n` (a bare
    `uv run pytest path::test`, or `make test-backend PYTEST_WORKERS=0`), so `url` passes through
    unchanged — the pre-E11-0 behaviour. Under xdist, `gw<N>` maps to db `(N % 15) + 1`: db 0 is
    reserved for that serial/no-xdist case and is never reused by a worker, and capping at 15
    keeps every worker inside Redis's default 16 databases even if `-n auto` starts more than 15
    workers, in which case two workers share a db index. That is safe only because every Redis key
    and pub/sub channel the tests (and the production code they exercise) use is namespaced by a
    per-test/per-session UUID — see the E11-0 report for the audit — so two workers sharing a db
    index never observe each other's keys or channels by accident.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    if worker == "master":
        return url
    match = _XDIST_WORKER.match(worker)
    if match is None:  # pragma: no cover - defensive: an xdist worker id pytest-xdist never emits
        return url
    db_index = (int(match.group(1)) % 15) + 1
    base, _, _current_db = url.rpartition("/")
    return f"{base}/{db_index}"


@pytest.fixture
def test_settings() -> Settings:
    """A `Settings` instance built from the test environment (see `Makefile`)."""
    return Settings(
        database_url=os.environ.get(
            "SIM_DATABASE_URL", "postgresql+asyncpg://sim:sim@localhost:55432/sim_test"
        ),
        redis_url=_redis_url_for_worker(
            os.environ.get("SIM_REDIS_URL", "redis://localhost:56379/0")
        ),
        jwt_secret=os.environ.get("SIM_JWT_SECRET", "test-only-secret-padded-32-bytes!"),
        require_inference_ready=False,
        livekit_url=os.environ.get("SIM_LIVEKIT_URL", "ws://localhost:7880"),
        livekit_api_key=os.environ.get("SIM_LIVEKIT_API_KEY", "devkey"),
        livekit_api_secret=os.environ.get("SIM_LIVEKIT_API_SECRET", "devsecret1234567890"),
        llm_base_url=os.environ.get("SIM_LLM_BASE_URL", "http://localhost:8080/v1"),
    )


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[AsyncEngine]:
    """A freshly migrated throwaway database on the test server (HLD `20-db-schema.md`).

    Creates `sim_test_<random>`, runs `alembic upgrade head` into it, yields an `AsyncEngine`
    bound to it and drops the database afterwards. `NullPool` is used because pytest-asyncio
    gives each test its own event loop and a pooled connection must never cross loops.

    Tests that need real COMMITs use this engine directly and clean up the rows they made;
    everything else should take `db_session`, whose outer transaction is rolled back.
    """
    from tests.integration.db import alembic_support as support

    base_url = os.environ.get(
        "SIM_DATABASE_URL", "postgresql+asyncpg://sim:sim@localhost:55432/sim_test"
    )
    database_name = support.random_database_name()
    url = support.replace_database(base_url, database_name)

    support.create_database(base_url, database_name)
    try:
        support.upgrade(url)
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            yield engine
        finally:
            asyncio.run(engine.dispose())
    finally:
        support.drop_database(base_url, database_name)


@pytest.fixture
async def db_session(migrated_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """An `AsyncSession` inside an outer transaction that is rolled back when the test ends.

    Nothing a test writes through this session survives it, so the schema stays pristine for the
    next test without any per-test migration.
    """
    async with migrated_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


@pytest.fixture(autouse=True)
def _clean_cwd() -> Iterator[None]:
    """Guard against tests that `os.chdir()` leaking into later tests."""
    original = os.getcwd()
    yield
    os.chdir(original)
