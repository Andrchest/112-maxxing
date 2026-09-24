"""Fixtures for the API tests (real PostgreSQL and Redis, no bound port).

Every test here drives the real application through `httpx.ASGITransport`: `create_app(container)`
in process, no `uvicorn`, no socket. That is deliberate and it is a rule, not a convenience —
ports 8000 and 8001 on the development machine belong to another project, and a test suite that
binds a port is a test suite that can collide with whatever else is running.

The container is the production one with three overrides, each for a stated reason:

* `runner_enabled=False` — D7's runner would leave a background task per ACTIVE session behind.
  `backend/tests/api/test_lifespan.py` is the one test that turns it on, and it asserts the task
  count is back where it started;
* `FakePasswordHasher` — argon2 is ~100 ms per hash by design; a suite that logs in fifty times
  would spend five seconds proving nothing about the KDF. `test_argon2_hasher` covers the real
  one;
* `FakeInferenceReadiness` — the real `RedisInferenceReadiness` (D8, E18-B) would need a live
  `voice:health:{service}` heartbeat in Redis for every test that starts a session;
  `backend/tests/integration/health/` drives the real adapter instead.

Everything else is real: the engine is the migrated throwaway database, Redis is the compose
instance, and the Unit of Work, the repositories and the event store are the production ones.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import redis.asyncio as redis_asyncio
from app.api.container import Container
from app.api.main import create_app
from app.application.ports.user_repository import UserRole
from app.application.scenarios.import_scenarios import ImportScenarios
from app.application.testing.fakes import (
    FakeInferenceReadiness,
    FakePasswordHasher,
    InMemoryEventPublisher,
)
from app.config.settings import Settings
from app.db.session import create_session_factory
from app.domain.common.ids import ScenarioVersionId, UserId
from app.infrastructure.clock import SystemClock
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork, unit_of_work_factory
from app.tools.import_scenarios import YamlScenarioSource
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "scenarios" / "examples"
DEMO_SLUG = "apartment-fire"

#: Every table reachable from `simulation_sessions` by `CASCADE` (§20.9's append-only triggers
#: guard `UPDATE`/`DELETE` only — TRUNCATE is exempt, see `0001_baseline.py`). `users` and
#: `scenarios`/`scenario_versions` are reference data that stays committed across tests instead of
#: being wiped and re-seeded every time (E9-0); see the `users` and `demo_version_id` fixtures
#: below for why that is safe.
#: `lessons` (I3 E4a) is truncated with them: it is per-test state too, and it is referenced *by*
#: `simulation_sessions`, so the session cascade alone never reaches it.
_TRUNCATE_SESSION_TABLES = text(
    "TRUNCATE TABLE lessons, simulation_sessions RESTART IDENTITY CASCADE"
)

#: The seeded accounts' passwords. Test-only values in a test file — never a source default.
PASSWORDS: dict[str, str] = {
    "instructor1": "instructor-pw",
    "trainee1": "trainee-one-pw",
    "trainee2": "trainee-two-pw",
    "admin1": "admin-pw",
    "retired1": "retired-pw",
}


@pytest.fixture(autouse=True)
async def clean_database(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """Leave every per-session table (session/event/card/resource/...) empty around each test.

    No session/event/card/resource row of one test is ever visible to another — this cascades
    from `simulation_sessions` through every layer table (§20.4-§20.6). Reference data is left
    alone here; it is not test state.
    """
    async with migrated_engine.begin() as connection:
        await connection.execute(_TRUNCATE_SESSION_TABLES)
    yield
    async with migrated_engine.begin() as connection:
        await connection.execute(_TRUNCATE_SESSION_TABLES)


@pytest.fixture(scope="package", autouse=True)
async def _reference_data_lifecycle(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """Leave `users`/`scenarios` exactly as this package found them once every test here has run.

    `migrated_engine` (`backend/tests/conftest.py`) is ONE throwaway database shared with
    `backend/tests/integration` and `backend/tests/invariants` for the whole pytest session, and
    `users`/`demo_version_id` below deliberately leave their rows committed instead of truncating
    them per test (E9-0) — `backend/tests/integration/db/conftest.py`'s `seed_ids`, for one, does a
    bare `INSERT ... VALUES ('trainee1', ...)` with no `ON CONFLICT`, which a leaked row from here
    would turn into a unique-violation error. Package scope (not session scope) makes this
    fixture's teardown run right after the last test under `backend/tests/api/` — before any other
    package's tests start. `users` and `demo_version_id` are both self-healing (see their
    docstrings), so `backend/tests/invariants`' own reuse of them (`test_inv_04...py`,
    `test_inv_13...py`) re-creates whatever this truncated, further into the same session.
    """
    yield
    async with migrated_engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users, scenarios RESTART IDENTITY CASCADE"))


@pytest.fixture
def api_settings(test_settings: Settings) -> Settings:
    """`Settings` for an API test: no runner, inference not required, CORS off."""
    return test_settings.model_copy(
        update={
            "runner_enabled": False,
            "require_inference_ready": False,
            "cors_allow_origins": [],
            "api_port": 8100,
        }
    )


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    """A recording `EventPublisher`; the Redis adapter has its own test."""
    return InMemoryEventPublisher()


@pytest.fixture
def hasher() -> FakePasswordHasher:
    """See this module's docstring for why the real argon2 hasher is not used here."""
    return FakePasswordHasher()


@pytest.fixture
def inference() -> FakeInferenceReadiness:
    """See the module docstring: the real adapter has its own suite; this exercises the flag."""
    return FakeInferenceReadiness(ready=True)


@pytest.fixture
async def redis_client(api_settings: Settings) -> AsyncIterator[redis_asyncio.Redis]:
    """A real Redis client against the compose test instance."""
    client: redis_asyncio.Redis = redis_asyncio.from_url(
        api_settings.redis_url, decode_responses=True
    )
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def container(
    api_settings: Settings,
    migrated_engine: AsyncEngine,
    redis_client: redis_asyncio.Redis,
    publisher: InMemoryEventPublisher,
    hasher: FakePasswordHasher,
    inference: FakeInferenceReadiness,
) -> Container:
    """The production container over the test database, with the three documented overrides.

    `owns_engine=False` / `owns_redis=False`: the engine is the session-scoped
    `migrated_engine` and the client belongs to `redis_client`, so `container.aclose()` must not
    dispose either — the next test still needs them.
    """
    session_factory = create_session_factory(migrated_engine)
    return Container(
        api_settings,
        engine=migrated_engine,
        session_factory=session_factory,
        redis=redis_client,
        publisher=publisher,
        unit_of_work=unit_of_work_factory(session_factory, SystemClock(), publisher),
        hasher=hasher,
        inference=inference,
        owns_engine=False,
        owns_redis=False,
    )


@pytest.fixture
def unit_of_work(container: Container) -> Callable[[], SqlAlchemyUnitOfWork]:
    """The container's own Unit of Work factory, for tests that seed or assert directly."""
    factory = container.unit_of_work

    def make() -> SqlAlchemyUnitOfWork:
        unit = factory()
        assert isinstance(unit, SqlAlchemyUnitOfWork)
        return unit

    return make


@pytest.fixture
async def client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    """An `httpx.AsyncClient` over the real ASGI app — no port is bound (see the docstring).

    The lifespan is not run: `runner_enabled` is false for these tests anyway, and
    `test_lifespan.py` exercises startup and shutdown explicitly.
    """
    app = create_app(container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as http_client:
        yield http_client


# ---------------------------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------------------------


@pytest.fixture
async def users(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], hasher: FakePasswordHasher
) -> dict[str, UserId]:
    """Five accounts through the real repository: three roles, a second trainee, a retired one.

    Self-healing by construction (E9-0): `UserRepository.upsert` is `ON CONFLICT (username) DO
    UPDATE` and keeps the existing row's `id` (`app/infrastructure/persistence/user_repository.py`),
    so calling this every test is idempotent and cheap once the five rows already exist — it does
    not re-run the one genuinely expensive seed (see `demo_version_id`), and it also means a test
    that mutates an account (`realtime/test_websocket.py`'s token-expiry test deactivates
    `trainee1` mid-session) never leaks that change into the next test: the next `users` call
    upserts it straight back.
    """
    accounts = (
        ("instructor1", "Инструктор", UserRole.INSTRUCTOR, True),
        ("trainee1", "Стажёр", UserRole.TRAINEE, True),
        ("trainee2", "Стажёр 2", UserRole.TRAINEE, True),
        ("admin1", "Администратор", UserRole.ADMIN, True),
        ("retired1", "Бывший стажёр", UserRole.TRAINEE, False),
    )
    created: dict[str, UserId] = {}
    async with unit_of_work() as uow:
        for username, display_name_ru, role, is_active in accounts:
            stored = await uow.users.upsert(
                user_id=UserId(uuid4()),
                username=username,
                display_name_ru=display_name_ru,
                user_role=role,
                password_hash=hasher.hash(PASSWORDS[username]),
                is_active=is_active,
            )
            created[username] = stored.user_id
        await uow.commit()
    return created


async def login(client: httpx.AsyncClient, username: str) -> str:
    """Log in and return the bearer token (the tests' own use of the real endpoint)."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORDS[username]},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def auth(token: str) -> dict[str, str]:
    """The `Authorization` header for a bearer token."""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def tokens(client: httpx.AsyncClient, users: dict[str, UserId]) -> dict[str, str]:
    """A live bearer token per active seeded account."""
    return {
        username: await login(client, username)
        for username in ("instructor1", "trainee1", "trainee2", "admin1")
    }


@pytest.fixture
async def demo_version_id(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> ScenarioVersionId:
    """The committed demo scenario's version id; `role_chain` is 112 → DDS. Imported once, shared.

    Self-healing (E9-0): almost every test shares one import — the heavy part (load, §30.8
    validation, materialising `scoring_rules`) runs once — at the cost of one cheap existence
    check per test that asks for it. `isolated_scenario_catalog` (`test_scenarios.py`) truncates
    `scenarios` around the few tests that must see an empty or never-locked catalog, and
    `_reference_data_lifecycle` truncates it once this whole package is done; either way, the next
    test to ask for this fixture finds the row gone and re-imports through `ImportScenarios`'s own
    idempotence, so sharing never corrupts a later test.
    """
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(DEMO_SLUG)
        version = (
            await uow.scenarios.find_version(stored.scenario_id, 1) if stored is not None else None
        )
        await uow.commit()
    if version is not None:
        return version.scenario_version_id

    await ImportScenarios(unit_of_work, YamlScenarioSource())(EXAMPLES_DIR)
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(DEMO_SLUG)
        assert stored is not None
        version = await uow.scenarios.find_version(stored.scenario_id, 1)
        assert version is not None
        await uow.commit()
        return version.scenario_version_id


@pytest.fixture
async def isolated_scenario_catalog(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """Guarantee an empty `scenarios` table around a test that asserts on the *whole* catalog.

    `scenarios` is shared for the whole session (see `demo_version_id`); the handful of
    `test_scenarios.py` tests that assert `total == 0` or an unlocked `locked_at` need to see
    nothing but their own import, so this truncates specifically around them. `demo_version_id` is
    self-healing, so a later test that wants the shared demo scenario back gets it re-imported
    without noticing — this leaves no permanent damage.
    """
    truncate = text("TRUNCATE TABLE scenarios RESTART IDENTITY CASCADE")
    async with migrated_engine.begin() as connection:
        await connection.execute(truncate)
    yield
    async with migrated_engine.begin() as connection:
        await connection.execute(truncate)


@pytest.fixture
def demo_yaml() -> str:
    """The committed demo scenario file's bytes, as the import endpoint receives them."""
    return (EXAMPLES_DIR / DEMO_SLUG / "v1.yaml").read_text(encoding="utf-8")


async def create_demo_session(
    client: httpx.AsyncClient,
    token: str,
    scenario_version_id: ScenarioVersionId,
    participants: list[dict[str, Any]],
    session_mode: str = "MULTI_TRAINEE",
) -> dict[str, Any]:
    """`createSession` through HTTP; returns the `SessionDetail` body.

    The demo scenario's `role_chain` is `[OPERATOR_112, DDS]`, so `MULTI_TRAINEE` needs one
    participant per stage (`SINGLE_STAGE_ONE_PARTICIPANT`) and `FULL_CYCLE_SINGLE_TRAINEE` needs
    exactly one participant with `assigned_role_type: null` (`ALL_STAGES_ONE_PARTICIPANT`,
    §10.10). A test that wants one trainee playing the whole chain passes the latter.
    """
    response = await client.post(
        "/api/v1/sessions",
        headers=auth(token),
        json={
            "scenario_version_id": str(scenario_version_id),
            "session_mode": session_mode,
            "participants": participants,
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def participant(user_id: UserId, role: str | None) -> dict[str, Any]:
    """One `ParticipantAssignment` body."""
    return {"user_id": str(UUID(str(user_id))), "assigned_role_type": role}
