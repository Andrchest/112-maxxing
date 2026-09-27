"""`python -m app.cli settings_import` (I5 E37, Q-E16-1): the CLI half of `exportSettingsXml` — a
real `settings_xml.settings_env_lines` underneath (no faking the validation), only the file I/O,
argument parsing and exit codes are this file's own concern.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.cli import settings_import as cli
from app.config.settings import Settings
from app.config.settings_xml import export_settings_xml

_BASE_KWARGS = {
    "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
    "redis_url": "redis://localhost:56379/0",
    "jwt_secret": "x" * 32,
    "livekit_url": "ws://localhost:7880",
    "livekit_api_key": "devkey",
    "livekit_api_secret": "devsecret1234567890",
    "llm_base_url": "http://localhost:8080/v1",
}


def _xml_of(**overrides: object) -> str:
    return export_settings_xml(Settings(**{**_BASE_KWARGS, **overrides}))  # type: ignore[arg-type]


def test_a_valid_export_is_written_as_name_value_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    xml_path = tmp_path / "settings.xml"
    xml_path.write_text(_xml_of(log_format="text"), encoding="utf-8")
    out_path = tmp_path / "out" / ".env.settings"

    exit_code = cli.main(["--file", str(xml_path), "--out", str(out_path)])

    assert exit_code == 0
    written = out_path.read_text(encoding="utf-8")
    assert "SIM_LOG_FORMAT=text" in written
    assert "SIM_JWT_SECRET" not in written
    assert "wrote" in capsys.readouterr().out


def test_the_default_out_path_is_infra_env_settings() -> None:
    assert cli.DEFAULT_OUT_PATH == "infra/.env.settings"


def test_a_missing_file_is_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["--file", str(tmp_path / "no-such-file.xml")])
    assert exit_code == 2
    assert "could not read" in capsys.readouterr().err


def test_a_secret_name_is_refused_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    xml_path = tmp_path / "settings.xml"
    xml_path.write_text(
        '<settings version="1"><setting name="SIM_JWT_SECRET">leaked</setting></settings>',
        encoding="utf-8",
    )
    out_path = tmp_path / ".env.settings"

    exit_code = cli.main(["--file", str(xml_path), "--out", str(out_path)])

    assert exit_code == 2
    assert "refused" in capsys.readouterr().err
    assert not out_path.exists()


def test_a_malformed_xml_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    xml_path = tmp_path / "settings.xml"
    xml_path.write_text("<settings", encoding="utf-8")
    out_path = tmp_path / ".env.settings"

    exit_code = cli.main(["--file", str(xml_path), "--out", str(out_path)])

    assert exit_code == 2
    assert not out_path.exists()


def test_run_settings_import_returns_the_count(tmp_path: Path) -> None:
    xml = _xml_of()
    out_path = tmp_path / ".env.settings"
    count = cli.run_settings_import(xml, out_path=out_path)
    assert count > 0
    assert len(out_path.read_text(encoding="utf-8").splitlines()) == count
