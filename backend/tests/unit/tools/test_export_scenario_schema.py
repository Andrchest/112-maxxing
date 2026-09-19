"""`python -m app.tools.export_scenario_schema` and its `--check` staleness gate (D4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.tools.export_scenario_schema import DEFAULT_SCHEMA_PATH, main, render_schema

from tests.fixtures.scenarios import REPO_ROOT

COMMITTED_SCHEMA = REPO_ROOT / DEFAULT_SCHEMA_PATH


def test_render_schema_is_deterministic_and_newline_terminated() -> None:
    first = render_schema()

    assert first == render_schema()
    assert first.endswith("}\n")


def test_committed_schema_is_up_to_date() -> None:
    assert COMMITTED_SCHEMA.is_file()
    assert COMMITTED_SCHEMA.read_text(encoding="utf-8") == render_schema()


def test_check_passes_on_the_committed_schema(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--check", "--path", str(COMMITTED_SCHEMA)])

    assert exit_code == 0
    assert "up to date" in capsys.readouterr().out


def test_check_fails_after_the_file_is_altered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy = tmp_path / "scenario_version.schema.json"
    copy.write_text(render_schema() + " ", encoding="utf-8")

    exit_code = main(["--check", "--path", str(copy)])

    assert exit_code == 1
    assert "is stale" in capsys.readouterr().out


def test_check_fails_when_the_file_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--check", "--path", str(tmp_path / "absent.json")])

    assert exit_code == 1
    assert "does not exist" in capsys.readouterr().out


def test_export_writes_a_file_that_check_then_accepts(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "scenario_version.schema.json"

    assert main(["--path", str(target)]) == 0
    assert main(["--check", "--path", str(target)]) == 0
