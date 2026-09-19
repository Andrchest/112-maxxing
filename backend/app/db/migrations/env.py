"""Alembic environment — async (`asyncpg`), one linear history (HLD `20-db-schema.md`, D5).

The database URL is never stored in `alembic.ini`: it is read from `Settings.database_url`
(environment variable `SIM_DATABASE_URL`), with an `-x url=...` command-line override so
`make db-check` can point the same migration at a scratch database.

`target_metadata` is `app.db.base.Base.metadata` with every model module imported, which is what
makes `alembic check` a real models-versus-migration drift check.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

import app.db.models  # noqa: F401  (imports every model module, completing the metadata)
from alembic import context
from app.config.settings import Settings
from app.db.base import Base
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """The URL to migrate: `-x url=...` if given, otherwise `Settings.database_url`."""
    override = context.get_x_argument(as_dictionary=True).get("url")
    if override:
        return str(override)
    return Settings().database_url  # type: ignore[call-arg]  # values come from the environment


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection (`alembic upgrade --sql`)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open an async engine and run the migrations through a sync-style connection."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
