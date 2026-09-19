"""Fixtures for the session-lifecycle integration tests (real PostgreSQL, fake Redis publisher).

These tests need genuine COMMITs — the whole point of E5 is that create/start/abort are each one
transaction and that a rejection leaves *nothing* behind — so they use `migrated_engine` directly
and clean up with `TRUNCATE ... CASCADE`, exactly like `tests/integration/persistence`.

The scenario reference data is produced by the real importer (`ImportScenarios` +
`YamlScenarioSource`) over the committed demo scenario, so no test invents scenario content. The
one exception is `raw_version`, which writes a *mutated* demo document straight through the
repository, deliberately skipping the importer's validation: that is how a scenario the importer
would refuse (a `role_chain` containing `EDDS`) can reach session creation at all.
"""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.application.scenarios.import_scenarios import (
    ImportScenarios,
    canonical_content,
    content_digest,
)
from app.application.sessions import AbortSession, CreateSession, StartSession
from app.application.testing.fakes import (
    FakeClock,
    FakeInferenceReadiness,
    InMemoryEventPublisher,
    SequentialIdGenerator,
)
from app.db.session import create_session_factory
from app.domain.common.actors import ActorRef
from app.domain.common.ids import ScenarioId, ScenarioVersionId, UserId
from app.domain.enums import ActorType, RoleType
from app.domain.scenario.version import ScenarioVersion
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.tools.import_scenarios import YamlScenarioSource
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.fixtures.scenarios import demo_document

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLES_DIR = REPO_ROOT / "scenarios" / "examples"
DEMO_SLUG = "apartment-fire"

_TRUNCATE = text("TRUNCATE TABLE users, scenarios RESTART IDENTITY CASCADE")


@pytest.fixture(autouse=True)
async def clean_database(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """Leave the schema empty before and after every test in this package."""
    async with migrated_engine.begin() as connection:
        await connection.execute(_TRUNCATE)
    yield
    async with migrated_engine.begin() as connection:
        await connection.execute(_TRUNCATE)


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
def ids() -> SequentialIdGenerator:
    """A deterministic `IdGenerator`, so a created aggregate is reproducible id-for-id."""
    return SequentialIdGenerator()


@pytest.fixture
def inference() -> FakeInferenceReadiness:
    """TODO(E18) ships the real adapter; E5 exercises the flag through this fake."""
    return FakeInferenceReadiness(ready=True)


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
def create_session(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], ids: SequentialIdGenerator
) -> CreateSession:
    return CreateSession(unit_of_work, ids)


@pytest.fixture
def start_session(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    clock: FakeClock,
    inference: FakeInferenceReadiness,
) -> StartSession:
    """`require_inference_ready=False`, the `Makefile`'s test default; a test that wants the
    other branch builds its own `StartSession`."""
    return StartSession(unit_of_work, clock, inference, require_inference_ready=False)


@pytest.fixture
def abort_session(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], clock: FakeClock
) -> AbortSession:
    return AbortSession(unit_of_work, clock)


# ---------------------------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------------------------


@pytest.fixture
async def users(migrated_engine: AsyncEngine) -> dict[str, UserId]:
    """One instructor and two trainees, committed (every actor id is a real `users` row)."""
    created: dict[str, UserId] = {}
    async with migrated_engine.begin() as connection:
        for username, display in (
            ("instructor1", "Инструктор"),
            ("trainee1", "Стажёр"),
            ("trainee2", "Стажёр 2"),
        ):
            result = await connection.execute(
                text(
                    "INSERT INTO users (username, password_hash, display_name_ru)"
                    " VALUES (:username, 'x', :display) RETURNING id"
                ),
                {"username": username, "display": display},
            )
            created[username] = UserId(UUID(str(result.scalar_one())))
    return created


@pytest.fixture
def instructor(users: dict[str, UserId]) -> ActorRef:
    return ActorRef(actor_type=ActorType.INSTRUCTOR, actor_id=users["instructor1"])


@pytest.fixture
def trainee(users: dict[str, UserId]) -> ActorRef:
    return ActorRef(actor_type=ActorType.TRAINEE, actor_id=users["trainee1"])


@pytest.fixture
async def demo_version_id(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> ScenarioVersionId:
    """Import the committed demo scenario and return its `scenario_version_id`.

    `role_chain` is `[OPERATOR_112, DDS]` and `locked_at` is still NULL: locking is session
    creation's job (D4).
    """
    await ImportScenarios(unit_of_work, YamlScenarioSource())(EXAMPLES_DIR)
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(DEMO_SLUG)
        assert stored is not None
        version = await uow.scenarios.find_version(stored.scenario_id, 1)
        assert version is not None
        return version.scenario_version_id


@pytest.fixture
def raw_version(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> Callable[..., Any]:
    """Insert a mutated demo document straight through the repository, without validation.

    Returns an awaitable factory `(slug, **mutations) -> ScenarioVersionId`. The importer would
    refuse some of these documents (an `EDDS` `role_chain`, rule R18), which is exactly why they
    bypass it: the rejection under test must be the one session creation makes, not the one the
    importer would have made hours earlier.
    """

    async def insert(
        slug: str,
        *,
        role_chain: Sequence[RoleType] | None = None,
        with_prefab_handoff: bool = True,
    ) -> ScenarioVersionId:
        document: dict[str, Any] = copy.deepcopy(demo_document())
        document["id"] = str(uuid4())
        document["scenario_id"] = str(uuid4())
        if role_chain is not None:
            document["role_chain"] = [role.value for role in role_chain]
        if not with_prefab_handoff:
            document["expected_response"].pop("prefab_handoff", None)

        version = ScenarioVersion(**document)
        content = canonical_content(version)
        async with unit_of_work() as uow:
            await uow.scenarios.add_scenario(
                ScenarioId(UUID(document["scenario_id"])), slug, version.title
            )
            await uow.scenarios.add_version(version, content, content_digest(content))
            await uow.commit()
        return version.id

    return insert


# ---------------------------------------------------------------------------------------------
# Row-counting helpers
# ---------------------------------------------------------------------------------------------


async def count(engine: AsyncEngine, table: str, **where: Any) -> int:
    """`SELECT count(*) FROM <table> [WHERE ...]` on a fresh connection (committed state only)."""
    clause = " AND ".join(f"{column} = :{column}" for column in where)
    statement = f"SELECT count(*) FROM {table}" + (f" WHERE {clause}" if clause else "")
    async with engine.connect() as connection:
        result = await connection.execute(text(statement), where)
        return int(result.scalar_one())


async def scalar(engine: AsyncEngine, statement: str, **params: Any) -> Any:
    """One committed scalar value."""
    async with engine.connect() as connection:
        result = await connection.execute(text(statement), params)
        return result.scalar_one()


async def locked_at(engine: AsyncEngine, scenario_version_id: ScenarioVersionId) -> Any:
    """`scenario_versions.locked_at` as committed (D4, SPEC §42 invariant 6)."""
    return await scalar(
        engine,
        "SELECT locked_at FROM scenario_versions WHERE id = :id",
        id=UUID(str(scenario_version_id)),
    )
