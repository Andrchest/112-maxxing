"""`python -m app.tools.import_scenarios [dir]` — scenario import CLI (D4, HLD §20.2).

Wires the real adapters to `app.application.scenarios.ImportScenarios`: the YAML loader of
`app.infrastructure.scenarios.yaml_loader` behind the `ScenarioSource` port, the PostgreSQL Unit of
Work and the Redis publisher (which this use case never exercises — an import appends no
`session_events` — but the Unit of Work is one object with one contract).

Exits 0 on success and 1 on any rejection: an invalid file, a slug owned by a different
`scenario_id`, or a file changed under an already-imported version number. Because the whole import
runs in one transaction, a rejection leaves the database untouched.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from redis.asyncio import Redis

from app.application.scenarios.import_scenarios import ImportReport, ImportScenarios
from app.config.settings import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.domain.common.errors import DomainError
from app.domain.scenario.version import ScenarioVersion
from app.infrastructure.clock import SystemClock
from app.infrastructure.persistence.unit_of_work import unit_of_work_factory
from app.infrastructure.realtime.redis_publisher import RedisEventPublisher
from app.infrastructure.scenarios import yaml_loader

DEFAULT_SCENARIOS_DIR = Path("scenarios/examples")

__all__ = ["YamlScenarioSource", "main", "run_import"]


class YamlScenarioSource:
    """`ScenarioSource` adapter over `app.infrastructure.scenarios.yaml_loader` (D2)."""

    def discover(self, root: Path) -> Sequence[Path]:
        return yaml_loader.discover(root)

    def slug_for(self, path: Path) -> str:
        return yaml_loader.scenario_slug(path)

    def load(self, path: Path) -> ScenarioVersion:
        return yaml_loader.load_scenario_version(path)


async def run_import(root: Path, settings: Settings) -> ImportReport:
    """Import `root` against the database and Redis named by `settings`."""
    engine = create_engine(settings)
    redis_client: Redis = Redis.from_url(settings.redis_url)
    try:
        use_case = ImportScenarios(
            unit_of_work_factory(
                create_session_factory(engine), SystemClock(), RedisEventPublisher(redis_client)
            ),
            YamlScenarioSource(),
        )
        return await use_case(root)
    finally:
        await redis_client.aclose()
        await engine.dispose()


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else DEFAULT_SCENARIOS_DIR
    try:
        report = asyncio.run(run_import(root, get_settings()))
    except DomainError as exc:
        print(f"FAIL {root}: {exc}")
        return 1

    print(
        f"{report.files} file(s): {report.scenarios_created} scenario(s) created, "
        f"{report.versions_created} version(s) created, "
        f"{report.versions_unchanged} version(s) already up to date"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
