"""The migration matches HLD `20-db-schema.md` §20.1 and the ORM models (epic E4).

The expected table set is parsed out of the markdown **at test time**: no list of table names is
retyped here, so adding a row to §20.1 without adding the table fails this suite.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.db import alembic_support as support

pytestmark = pytest.mark.integration

HLD_DB_SCHEMA = support.REPO_ROOT / "docs" / "hld" / "20-db-schema.md"
_NUMBERED_ROW = re.compile(r"^\|\s*\d+\s*\|")
_INVENTORY_ROW = re.compile(r"^\|\s*\d+\s*\|\s*`([a-z_]+)`\s*\|")


def _inventory_lines(path: Path = HLD_DB_SCHEMA) -> list[str]:
    """Every numbered row of the `## 20.1 Table inventory` markdown table."""
    lines: list[str] = []
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 20.1"):
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if inside and _NUMBERED_ROW.match(line):
            lines.append(line)
    return lines


def table_inventory(path: Path = HLD_DB_SCHEMA) -> set[str]:
    """Parse the §20.1 table inventory into a set of table names."""
    names = {
        match.group(1)
        for match in (_INVENTORY_ROW.match(line) for line in _inventory_lines(path))
        if match is not None
    }
    if not names:  # pragma: no cover - a parser that finds nothing must not pass silently
        raise AssertionError(f"could not parse the §20.1 table inventory out of {path}")
    return names


def _base_url() -> str:
    return os.environ.get(
        "SIM_DATABASE_URL", "postgresql+asyncpg://sim:sim@localhost:55432/sim_test"
    )


def _engine_url(engine: AsyncEngine) -> str:
    return engine.url.render_as_string(hide_password=False)


def test_inventory_parser_reads_every_numbered_row() -> None:
    """Guard the parser: every numbered §20.1 row yields exactly one table name."""
    lines = _inventory_lines()
    assert lines, "no numbered rows found in §20.1"
    assert len(table_inventory()) == len(lines)


def test_migrated_tables_equal_the_hld_inventory(migrated_engine: AsyncEngine) -> None:
    """The migrated database holds exactly the tables §20.1 lists."""
    assert support.table_names(_engine_url(migrated_engine)) == table_inventory()


def test_alembic_check_reports_no_drift(migrated_engine: AsyncEngine) -> None:
    """`alembic check`: the ORM models and the migration describe the same schema."""
    support.check(_engine_url(migrated_engine))


def test_upgrade_downgrade_upgrade_round_trip() -> None:
    """upgrade -> downgrade base (empty) -> upgrade again, on its own throwaway database."""
    base_url = _base_url()
    name = support.random_database_name("sim_roundtrip_")
    url = support.replace_database(base_url, name)
    support.create_database(base_url, name)
    try:
        support.upgrade(url)
        assert support.table_names(url) == table_inventory()

        support.downgrade(url)
        assert support.table_names(url) == set()

        support.upgrade(url)
        assert support.table_names(url) == table_inventory()
        support.check(url)
    finally:
        support.drop_database(base_url, name)
