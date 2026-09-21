"""Fixtures for the `ScoreRepository` integration tests (real PostgreSQL, §20.7, epic E15-B).

Same shape as `tests/integration/persistence/conftest.py`: a real `migrated_engine`, real commits
(the Unit of Work publishes only after one), `TRUNCATE ... CASCADE` between tests. The demo
scenario is imported for real (`ImportScenarios`) so `scoring_rules` rows exist and `score_results`
/ `score_evidence` FKs are satisfiable, exactly as a session's own scoring would see them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from uuid import UUID

import pytest
from app.application.scenarios.import_scenarios import ImportScenarios
from app.application.testing.fakes import FakeClock, InMemoryEventPublisher
from app.db.session import create_session_factory
from app.domain.common.actors import ActorRef
from app.domain.common.ids import ScenarioVersionId, SessionId
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.tools.import_scenarios import YamlScenarioSource
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

DEMO_SLUG = "apartment-fire"
REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLES_DIR = REPO_ROOT / "scenarios" / "examples"

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
    return create_session_factory(migrated_engine)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def unit_of_work(
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    publisher: InMemoryEventPublisher,
) -> Callable[[], SqlAlchemyUnitOfWork]:
    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, clock, publisher)

    return factory


@pytest.fixture
async def demo_version_id(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> ScenarioVersionId:
    """Import the committed demo scenario for real: ten real `scoring_rules` rows, real FKs."""
    await ImportScenarios(unit_of_work, YamlScenarioSource())(EXAMPLES_DIR)
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(DEMO_SLUG)
        assert stored is not None
        version = await uow.scenarios.find_version(stored.scenario_id, 1)
        assert version is not None
        await uow.commit()
        return version.scenario_version_id


@pytest.fixture
async def seeded_session(
    migrated_engine: AsyncEngine, demo_version_id: ScenarioVersionId
) -> SessionId:
    """One committed `simulation_sessions` row against the real demo scenario version."""
    async with migrated_engine.begin() as connection:
        user_id = (
            await connection.execute(
                text(
                    "INSERT INTO users (username, password_hash, display_name_ru)"
                    " VALUES ('trainee1', 'x', 'Стажёр') RETURNING id"
                )
            )
        ).scalar_one()
        session_row_id = (
            await connection.execute(
                text(
                    "INSERT INTO simulation_sessions"
                    " (scenario_version_id, session_mode, session_seed, created_by_user_id)"
                    " VALUES (:scenario_version_id, 'FULL_CYCLE_SINGLE_TRAINEE', 'seed', :user_id)"
                    " RETURNING id"
                ),
                {"scenario_version_id": UUID(str(demo_version_id)), "user_id": user_id},
            )
        ).scalar_one()
    return SessionId(UUID(str(session_row_id)))


@pytest.fixture
async def seeded_event(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], seeded_session: SessionId
) -> SessionEvent:
    """One real `session_events` row — an evidence FK target (`score_evidence.session_event_id`)."""
    async with unit_of_work() as uow:
        stored = await uow.events.append(
            seeded_session,
            [
                DomainEvent(
                    event_type=EventType.SESSION_CREATED,
                    actor=ActorRef(actor_type=ActorType.INSTRUCTOR),
                    monotonic_offset_ms=0,
                    payload={
                        "session_id": str(seeded_session),
                        "scenario_id": str(UUID(int=0)),
                        "scenario_version_id": str(UUID(int=0)),
                        "scenario_slug": DEMO_SLUG,
                        "scenario_version": 1,
                        "session_mode": "FULL_CYCLE_SINGLE_TRAINEE",
                        "session_seed": "seed",
                        "time_scale": 1.0,
                        "role_chain": ["OPERATOR_112", "DDS"],
                        "created_by_user_id": str(UUID(int=0)),
                    },
                )
            ],
        )
        await uow.commit()
    return stored[0]
