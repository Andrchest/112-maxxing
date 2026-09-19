"""`ImportScenarios` against real PostgreSQL (D4, HLD §20.2).

The demo scenario `scenarios/examples/apartment-fire/v1.yaml` is copied into a temporary directory
so a test can edit it without touching the repository's own file.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest
from app.application.scenarios.import_scenarios import (
    ImportScenarios,
    ScenarioIdentityConflictError,
    ScenarioVersionChangedError,
)
from app.domain.common.errors import ScenarioValidationError
from app.domain.common.ids import ScenarioVersionId
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.tools.import_scenarios import YamlScenarioSource
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[4]
DEMO_SLUG = "apartment-fire"
DEMO_FILE = REPO_ROOT / "scenarios" / "examples" / DEMO_SLUG / "v1.yaml"


def write_scenario(
    root: Path,
    version: int = 1,
    scenario_version_id: str | None = None,
    description: str | None = None,
) -> Path:
    """Copy the demo scenario into `root/<slug>/v<version>.yaml`, optionally edited."""
    lines = DEMO_FILE.read_text(encoding="utf-8").splitlines()
    edited: list[str] = []
    for line in lines:
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


@pytest.fixture
def import_scenarios(unit_of_work: Callable[[], SqlAlchemyUnitOfWork]) -> ImportScenarios:
    return ImportScenarios(unit_of_work, YamlScenarioSource())


async def test_import_creates_the_scenario_the_version_and_its_scoring_rules(
    import_scenarios: ImportScenarios, tmp_path: Path, migrated_engine: AsyncEngine
) -> None:
    write_scenario(tmp_path)
    report = await import_scenarios(tmp_path)

    assert (report.files, report.scenarios_created, report.versions_created) == (1, 1, 1)
    assert await _count(migrated_engine, "scenarios") == 1
    assert await _count(migrated_engine, "scenario_versions") == 1
    assert await _count(migrated_engine, "scoring_rules") == 10

    async with migrated_engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT slug, s.title_ru, v.version, v.schema_version, v.role_chain,"
                    " v.difficulty, v.deterministic_seed, v.content_sha256, v.source_path,"
                    " v.locked_at, v.content->>'title' AS content_title"
                    " FROM scenarios s JOIN scenario_versions v ON v.scenario_id = s.id"
                )
            )
        ).one()
    assert row.slug == DEMO_SLUG
    assert row.version == 1
    assert row.role_chain == ["OPERATOR_112", "DDS"]
    assert row.deterministic_seed == "apartment-fire-v1"
    assert len(row.content_sha256) == 64
    assert row.source_path.endswith("apartment-fire/v1.yaml")
    assert row.locked_at is None, "import must not lock; session creation does (D4)"
    assert row.content_title == row.title_ru


async def test_scoring_rules_keep_the_documents_order(
    import_scenarios: ImportScenarios, tmp_path: Path, migrated_engine: AsyncEngine
) -> None:
    write_scenario(tmp_path)
    await import_scenarios(tmp_path)

    async with migrated_engine.connect() as connection:
        order_indexes = list(
            (
                await connection.execute(
                    text("SELECT order_index FROM scoring_rules ORDER BY order_index")
                )
            ).scalars()
        )
    assert order_indexes == list(range(10))


async def test_a_second_import_creates_no_rows(
    import_scenarios: ImportScenarios, tmp_path: Path, migrated_engine: AsyncEngine
) -> None:
    write_scenario(tmp_path)
    await import_scenarios(tmp_path)
    before = await _snapshot(migrated_engine)

    report = await import_scenarios(tmp_path)

    assert (report.scenarios_created, report.versions_created, report.versions_unchanged) == (
        0,
        0,
        1,
    )
    assert await _snapshot(migrated_engine) == before


async def test_a_changed_file_under_the_same_version_is_rejected(
    import_scenarios: ImportScenarios, tmp_path: Path, migrated_engine: AsyncEngine
) -> None:
    write_scenario(tmp_path)
    await import_scenarios(tmp_path)
    before = await _snapshot(migrated_engine)

    write_scenario(tmp_path, description="Edited in place, which SPEC §4 forbids")
    with pytest.raises(ScenarioVersionChangedError) as raised:
        await import_scenarios(tmp_path)

    assert "bump the version to v2" in str(raised.value)
    assert await _snapshot(migrated_engine) == before


async def test_the_same_content_under_a_new_version_number_is_accepted(
    import_scenarios: ImportScenarios, tmp_path: Path, migrated_engine: AsyncEngine
) -> None:
    write_scenario(tmp_path)
    await import_scenarios(tmp_path)
    write_scenario(
        tmp_path,
        version=2,
        scenario_version_id="6b1d0f4e-7f33-4a91-9a16-1a0c2bb4e7d2",
        description="A second, bumped version",
    )

    report = await import_scenarios(tmp_path)

    assert (report.files, report.versions_created, report.versions_unchanged) == (2, 1, 1)
    assert await _count(migrated_engine, "scenarios") == 1
    assert await _count(migrated_engine, "scenario_versions") == 2
    assert await _count(migrated_engine, "scoring_rules") == 20


async def test_an_invalid_file_rolls_the_whole_import_back(
    import_scenarios: ImportScenarios, tmp_path: Path, migrated_engine: AsyncEngine
) -> None:
    path = write_scenario(tmp_path)
    path.write_text(path.read_text(encoding="utf-8") + "\nunknown_key: 1\n", encoding="utf-8")

    with pytest.raises(ScenarioValidationError):
        await import_scenarios(tmp_path)

    assert await _count(migrated_engine, "scenarios") == 0
    assert await _count(migrated_engine, "scenario_versions") == 0


async def test_a_slug_owned_by_another_scenario_id_is_rejected(
    import_scenarios: ImportScenarios, tmp_path: Path, migrated_engine: AsyncEngine
) -> None:
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO scenarios (slug, title_ru) VALUES (:slug, 'Другой')"),
            {"slug": DEMO_SLUG},
        )
    write_scenario(tmp_path)

    with pytest.raises(ScenarioIdentityConflictError):
        await import_scenarios(tmp_path)


async def test_lock_scenario_version_is_idempotent(
    import_scenarios: ImportScenarios,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    tmp_path: Path,
    migrated_engine: AsyncEngine,
) -> None:
    write_scenario(tmp_path)
    await import_scenarios(tmp_path)
    version_id = ScenarioVersionId(await _only_version_id(migrated_engine))

    async with unit_of_work() as uow:
        assert await uow.scenarios.lock_scenario_version(version_id) is True
        await uow.commit()
    async with migrated_engine.connect() as connection:
        first = (
            await connection.execute(text("SELECT locked_at FROM scenario_versions"))
        ).scalar_one()

    async with unit_of_work() as uow:
        assert await uow.scenarios.lock_scenario_version(version_id) is False
        await uow.commit()
    async with migrated_engine.connect() as connection:
        second = (
            await connection.execute(text("SELECT locked_at FROM scenario_versions"))
        ).scalar_one()

    assert first is not None
    assert second == first


async def _count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        value = (await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
    return int(value)


async def _snapshot(engine: AsyncEngine) -> list[tuple[str, int, str]]:
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT s.slug, v.version, v.content_sha256"
                    " FROM scenarios s JOIN scenario_versions v ON v.scenario_id = s.id"
                    " ORDER BY s.slug, v.version"
                )
            )
        ).all()
    return [(row.slug, row.version, row.content_sha256) for row in rows]


async def _only_version_id(engine: AsyncEngine) -> UUID:
    async with engine.connect() as connection:
        value = (await connection.execute(text("SELECT id FROM scenario_versions"))).scalar_one()
    return UUID(str(value))
