"""Async engine and session factory (HLD `20-db-schema.md`, D5).

SQLAlchemy 2 async with `asyncpg`. The engine is built from `Settings.database_url` — nothing here
reads the environment directly, so a test can hand in its own `Settings`.

`expire_on_commit=False` because a use case's Unit of Work commits once at the end and the caller
still needs to read the flushed attributes afterwards (D5).
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import Settings, get_settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Create a new `AsyncEngine` for `settings.database_url`.

    The caller owns the engine and must `await engine.dispose()` when finished.
    """
    return create_async_engine(settings.database_url, pool_pre_ping=True, future=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the `AsyncSession` factory used by the Unit of Work."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide engine built from the cached `Settings`."""
    return create_engine(get_settings())


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide `AsyncSession` factory."""
    return create_session_factory(get_engine())
