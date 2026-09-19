from __future__ import annotations

from pathlib import Path

from app.tools.validate_scenarios import main, validate_file


def test_validate_file_accepts_parseable_yaml(tmp_path: Path) -> None:
    scenario = tmp_path / "v1.yaml"
    scenario.write_text("slug: apartment_fire\ntitle: Пожар в квартире\n", encoding="utf-8")

    assert validate_file(scenario) == []


def test_validate_file_reports_yaml_parse_error(tmp_path: Path) -> None:
    scenario = tmp_path / "v1.yaml"
    scenario.write_text("slug: [unclosed\n", encoding="utf-8")

    errors = validate_file(scenario)

    assert len(errors) == 1
    assert str(scenario) in errors[0]


def test_main_reports_zero_files_when_none_exist(tmp_path: Path, capsys) -> None:
    exit_code = main([str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "0 scenario files"


def test_main_passes_on_valid_scenario_files(tmp_path: Path, capsys) -> None:
    scenario_dir = tmp_path / "apartment_fire"
    scenario_dir.mkdir()
    (scenario_dir / "v1.yaml").write_text("slug: apartment_fire\n", encoding="utf-8")

    exit_code = main([str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS" in captured.out


def test_main_fails_on_invalid_scenario_files(tmp_path: Path, capsys) -> None:
    scenario_dir = tmp_path / "apartment_fire"
    scenario_dir.mkdir()
    (scenario_dir / "v1.yaml").write_text("slug: [unclosed\n", encoding="utf-8")

    exit_code = main([str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "FAIL" in captured.out
