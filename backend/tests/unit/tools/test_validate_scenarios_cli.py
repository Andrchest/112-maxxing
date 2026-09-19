"""`python -m app.tools.validate_scenarios` and the YAML loader behind it (D4, §30.8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.domain.common.errors import ScenarioValidationError
from app.infrastructure.scenarios.yaml_loader import (
    discover,
    load_scenario_version,
    scenario_slug,
)
from app.tools.validate_scenarios import main, validate_file

from tests.fixtures.scenarios import EXAMPLES_DIR, demo_document, write_scenario


def test_discover_finds_the_committed_demo_scenario() -> None:
    found = discover(EXAMPLES_DIR)

    assert EXAMPLES_DIR / "apartment-fire" / "v1.yaml" in found
    assert all(path.name.startswith("v") for path in found)


def test_load_scenario_version_parses_and_validates_the_demo() -> None:
    version = load_scenario_version(EXAMPLES_DIR / "apartment-fire" / "v1.yaml")

    assert version.version == 1
    assert version.world_truth.facts["address.house"].world_value == "27"
    assert scenario_slug(EXAMPLES_DIR / "apartment-fire" / "v1.yaml") == "apartment-fire"


def test_load_scenario_version_rejects_a_version_that_disagrees_with_the_path(
    tmp_path: Path,
) -> None:
    document = demo_document()
    document["version"] = 7
    path = write_scenario(tmp_path, document)
    path = path.rename(path.with_name("v1.yaml"))

    with pytest.raises(ScenarioValidationError) as excinfo:
        load_scenario_version(path)

    assert any("expected 1 from the file name" in v for v in excinfo.value.violations)


def test_validate_file_reports_every_violation_of_a_broken_copy(tmp_path: Path) -> None:
    document = demo_document()
    document["caller_knowledge"]["facts"]["address.house"]["caller_value"] = "72"
    path = write_scenario(tmp_path, document)

    violations = validate_file(path)

    assert any(violation.startswith("R05:") for violation in violations)


def test_cli_exits_zero_on_the_committed_examples(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(EXAMPLES_DIR)])

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert "PASS" in captured


def test_cli_exits_one_and_names_the_rule_for_a_broken_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = demo_document()
    document["caller_knowledge"]["facts"]["address.house"]["caller_value"] = "72"
    write_scenario(tmp_path, document)

    exit_code = main([str(tmp_path)])

    captured = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL" in captured
    assert "R05:" in captured


def test_cli_exits_one_on_a_directory_without_any_scenario(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([str(tmp_path)])

    assert exit_code == 1
    assert "no <slug>/v<N>.yaml scenario file found" in capsys.readouterr().out


def test_validate_file_reports_a_yaml_parse_error_instead_of_raising(tmp_path: Path) -> None:
    scenario = tmp_path / "broken" / "v1.yaml"
    scenario.parent.mkdir()
    scenario.write_text("slug: [unclosed\n", encoding="utf-8")

    errors = validate_file(scenario)

    assert len(errors) == 1
