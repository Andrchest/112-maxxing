"""Fixtures for the persistence integration tests (real PostgreSQL, real Redis).

Unlike `tests/integration/db`, these tests need genuine COMMITs — an append that is rolled back
proves nothing about the `seq_no` row lock, and the Unit of Work publishes only after a commit. So
they use `migrated_engine` directly and clean up with `TRUNCATE ... CASCADE`, which (unlike DELETE)
does not fire the `BEFORE DELETE` append-only triggers of §20.9.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from uuid import UUID, uuid4

import pytest
import redis.asyncio as redis_asyncio
from app.application.testing.fakes import FakeClock, InMemoryEventPublisher
from app.config.settings import Settings
from app.db.session import create_session_factory
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

#: Truncating these two reference tables reaches every other table through `CASCADE`.
_TRUNCATE = text("TRUNCATE TABLE users, scenarios RESTART IDENTITY CASCADE")


async def _truncate_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(_TRUNCATE)


@pytest.fixture(autouse=True)
async def clean_database(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """Leave the schema empty before and after every test in this package."""
    await _truncate_all(migrated_engine)
    yield
    await _truncate_all(migrated_engine)


@pytest.fixture
def session_factory(migrated_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The production `AsyncSession` factory, bound to the throwaway migrated database."""
    return create_session_factory(migrated_engine)


@pytest.fixture
def clock() -> FakeClock:
    """A pinned clock, so `timestamp_utc` is provably not read from the machine."""
    return FakeClock()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    """A recording `EventPublisher`; the Redis adapter has its own test."""
    return InMemoryEventPublisher()


@pytest.fixture
def unit_of_work(
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    publisher: InMemoryEventPublisher,
) -> Callable[[], SqlAlchemyUnitOfWork]:
    """A factory of Units of Work sharing the fixture clock and publisher."""

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, clock, publisher)

    return factory


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


@pytest.fixture
async def seeded(migrated_engine: AsyncEngine) -> dict[str, UUID]:
    """One committed user / scenario / scenario_version / simulation_session chain."""
    ids: dict[str, UUID] = {}
    async with migrated_engine.begin() as connection:
        ids["user"] = UUID(
            str(
                (
                    await connection.execute(
                        text(
                            "INSERT INTO users (username, password_hash, display_name_ru)"
                            " VALUES ('trainee1', 'x', 'Стажёр') RETURNING id"
                        )
                    )
                ).scalar_one()
            )
        )
        ids["scenario"] = UUID(
            str(
                (
                    await connection.execute(
                        text(
                            "INSERT INTO scenarios (slug, title_ru)"
                            " VALUES ('fire-01', 'Пожар') RETURNING id"
                        )
                    )
                ).scalar_one()
            )
        )
        ids["scenario_version"] = UUID(
            str(
                (
                    await connection.execute(
                        text(
                            "INSERT INTO scenario_versions (scenario_id, version, schema_version,"
                            " title, deterministic_seed, role_chain, content, content_sha256)"
                            " VALUES (:scenario_id, 1, 1, 'v1', 'seed', ARRAY['OPERATOR_112'],"
                            " CAST(:content AS jsonb), 'sha') RETURNING id"
                        ),
                        {"scenario_id": ids["scenario"], "content": json.dumps({"version": 1})},
                    )
                ).scalar_one()
            )
        )
        ids["session"] = UUID(
            str(
                (
                    await connection.execute(
                        text(
                            "INSERT INTO simulation_sessions (scenario_version_id, session_mode,"
                            " session_seed, created_by_user_id)"
                            " VALUES (:scenario_version_id, 'SINGLE_ROLE', 'seed', :user_id)"
                            " RETURNING id"
                        ),
                        {
                            "scenario_version_id": ids["scenario_version"],
                            "user_id": ids["user"],
                        },
                    )
                ).scalar_one()
            )
        )
    return ids


@pytest.fixture
def session_id(seeded: dict[str, UUID]) -> SessionId:
    """The seeded session's id, as the domain's `SessionId`."""
    return SessionId(seeded["session"])


def make_event(
    event_type: EventType = EventType.CARD_FIELD_CHANGED,
    monotonic_offset_ms: int = 0,
    **payload: object,
) -> DomainEvent:
    """A minimal `DomainEvent` with a `SYSTEM` actor (no `users` FK to satisfy)."""
    return DomainEvent(
        event_type=event_type,
        actor=ActorRef(actor_type=ActorType.SYSTEM),
        monotonic_offset_ms=monotonic_offset_ms,
        correlation_id=uuid4(),
        payload=dict(payload),
    )
