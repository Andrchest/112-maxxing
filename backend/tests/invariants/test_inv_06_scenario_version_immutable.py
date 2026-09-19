"""SPEC §42 invariant test 6: "ScenarioVersion cannot change during a running session."

SPEC §4 makes a `ScenarioVersion` immutable "as soon as a simulation starts using it", and D4
implements that as `scenario_versions.locked_at` plus the `scenario_versions_locked_guard` trigger
of HLD §20.2. The invariant therefore has two halves, and both are asserted here against real
PostgreSQL:

1. **At rest.** Once `lock_scenario_version` has set `locked_at`, no write path can change
   `content` or `content_sha256` — neither through the ORM nor through raw SQL, because the guard
   is a database trigger and not application code. Metadata updates stay legal, which is what
   §20.9 says the conditional trigger exists for.
2. **At import.** Re-importing a changed file under an already-imported version number is
   rejected and tells the author to bump the version (D4); importing the change as v2 succeeds and
   leaves v1 byte-identical — compared by `content_sha256`, which is the digest of the whole
   stored document.

This file is self-contained: it owns its fixtures so that the invariant can be read, and run, on
its own (`uv run pytest backend/tests/invariants`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from app.application.scenarios.import_scenarios import ImportScenarios, ScenarioVersionChangedError
from app.application.testing.fakes import FakeClock, InMemoryEventPublisher
from app.db.models.reference import ScenarioVersion as ScenarioVersionRow
from app.db.session import create_session_factory
from app.domain.common.ids import ScenarioVersionId
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.tools.import_scenarios import YamlScenarioSource
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_SLUG = "apartment-fire"
DEMO_FILE = REPO_ROOT / "scenarios" / "examples" / DEMO_SLUG / "v1.yaml"
V2_ID = "6b1d0f4e-7f33-4a91-9a16-1a0c2bb4e7d2"

_TRUNCATE = sa.text("TRUNCATE TABLE users, scenarios RESTART IDENTITY CASCADE")


def _write_scenario(
    root: Path,
    version: int = 1,
    scenario_version_id: str | None = None,
    description: str | None = None,
) -> Path:
    """Copy the demo scenario into `root/<slug>/v<version>.yaml`, optionally edited."""
    edited: list[str] = []
    for line in DEMO_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("version: ") and version != 1:
            edited.append(f"version: {version}")
        elif line.startswith("id: ") and scenario_version_id is not None:
            edited.append(f"id: {scenario_version_id}")
        elif line.startswith("description: ") and description is not None:
            edited.append(f'description: "{description}"')
        else:
            edited.append(line)
    directory = root / DEMO_SLUG
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"v{version}.yaml"
    path.write_text("\n".join(edited) + "\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
async def clean_database(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    async with migrated_engine.begin() as connection:
        await connection.execute(_TRUNCATE)
    yield
    async with migrated_engine.begin() as connection:
        await connection.execute(_TRUNCATE)


@pytest.fixture
def unit_of_work(migrated_engine: AsyncEngine) -> Callable[[], SqlAlchemyUnitOfWork]:
    factory = create_session_factory(migrated_engine)

    def make() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(factory, FakeClock(), InMemoryEventPublisher())

    return make


@pytest.fixture
def import_scenarios(unit_of_work: Callable[[], SqlAlchemyUnitOfWork]) -> ImportScenarios:
    return ImportScenarios(unit_of_work, YamlScenarioSource())


async def _digest(engine: AsyncEngine, version: int) -> str:
    async with engine.connect() as connection:
        value = (
            await connection.execute(
                sa.text("SELECT content_sha256 FROM scenario_versions WHERE version = :version"),
                {"version": version},
            )
        ).scalar_one()
    return str(value)


async def _version_id(engine: AsyncEngine, version: int) -> UUID:
    async with engine.connect() as connection:
        value = (
            await connection.execute(
                sa.text("SELECT id FROM scenario_versions WHERE version = :version"),
                {"version": version},
            )
        ).scalar_one()
    return UUID(str(value))


async def _import_and_lock(
    import_scenarios: ImportScenarios,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    engine: AsyncEngine,
    root: Path,
) -> UUID:
    """Import the demo scenario, then lock v1 the way session creation will (D4, E5)."""
    _write_scenario(root)
    await import_scenarios(root)
    version_id = await _version_id(engine, 1)
    async with unit_of_work() as uow:
        assert await uow.scenarios.lock_scenario_version(ScenarioVersionId(version_id)) is True
        await uow.commit()
    return version_id


async def test_updating_the_content_of_a_locked_version_through_the_orm_fails(
    import_scenarios: ImportScenarios,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    migrated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    version_id = await _import_and_lock(import_scenarios, unit_of_work, migrated_engine, tmp_path)
    before = await _digest(migrated_engine, 1)

    async with AsyncSession(bind=migrated_engine, expire_on_commit=False) as session:
        row = await session.get(ScenarioVersionRow, version_id)
        assert row is not None
        row.content = {"tampered": True}
        with pytest.raises(DBAPIError) as raised:
            await session.flush()
        await session.rollback()

    assert "is locked since" in str(raised.value)
    assert await _digest(migrated_engine, 1) == before


async def test_updating_the_content_of_a_locked_version_through_raw_sql_fails(
    import_scenarios: ImportScenarios,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    migrated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    version_id = await _import_and_lock(import_scenarios, unit_of_work, migrated_engine, tmp_path)
    before = await _digest(migrated_engine, 1)

    for statement in (
        "UPDATE scenario_versions SET content = '{\"tampered\": true}'::jsonb WHERE id = :id",
        "UPDATE scenario_versions SET content_sha256 = 'deadbeef' WHERE id = :id",
    ):
        with pytest.raises(DBAPIError) as raised:
            async with migrated_engine.begin() as connection:
                await connection.execute(sa.text(statement), {"id": version_id})
        assert "is locked since" in str(raised.value)

    assert await _digest(migrated_engine, 1) == before


async def test_metadata_of_a_locked_version_stays_updatable(
    import_scenarios: ImportScenarios,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    migrated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    """§20.9: the trigger is conditional — only `content` / `content_sha256` freeze."""
    version_id = await _import_and_lock(import_scenarios, unit_of_work, migrated_engine, tmp_path)

    async with migrated_engine.begin() as connection:
        await connection.execute(
            sa.text("UPDATE scenario_versions SET source_path = 'moved.yaml' WHERE id = :id"),
            {"id": version_id},
        )
        stored = (
            await connection.execute(
                sa.text("SELECT source_path FROM scenario_versions WHERE id = :id"),
                {"id": version_id},
            )
        ).scalar_one()
    assert stored == "moved.yaml"


async def test_reimporting_a_changed_file_under_the_locked_version_is_rejected(
    import_scenarios: ImportScenarios,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    migrated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    await _import_and_lock(import_scenarios, unit_of_work, migrated_engine, tmp_path)
    before = await _digest(migrated_engine, 1)

    _write_scenario(tmp_path, description="Edited after a session had started")
    with pytest.raises(ScenarioVersionChangedError) as raised:
        await import_scenarios(tmp_path)

    assert "bump the version to v2" in str(raised.value)
    assert await _digest(migrated_engine, 1) == before


async def test_importing_the_change_as_v2_leaves_v1_byte_identical(
    import_scenarios: ImportScenarios,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    migrated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    await _import_and_lock(import_scenarios, unit_of_work, migrated_engine, tmp_path)
    before = await _digest(migrated_engine, 1)

    _write_scenario(
        tmp_path,
        version=2,
        scenario_version_id=V2_ID,
        description="Edited after a session had started",
    )
    report = await import_scenarios(tmp_path)

    assert (report.files, report.versions_created, report.versions_unchanged) == (2, 1, 1)
    assert await _digest(migrated_engine, 1) == before
    assert await _digest(migrated_engine, 2) != before

    async with migrated_engine.connect() as connection:
        locked = (
            await connection.execute(
                sa.text(
                    "SELECT version, locked_at IS NOT NULL AS is_locked"
                    " FROM scenario_versions ORDER BY version"
                )
            )
        ).all()
    assert [(row.version, row.is_locked) for row in locked] == [(1, True), (2, False)]
