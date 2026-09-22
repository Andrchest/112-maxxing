"""`SIM_ENV_FILE` decides which dotenv `Settings` reads (E20): unset -> `./.env`, empty -> none."""

from __future__ import annotations

import pytest
from app.config.settings import resolve_env_file


def test_unset_means_the_cwd_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIM_ENV_FILE", raising=False)
    assert resolve_env_file() == ".env"


def test_empty_means_no_dotenv_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIM_ENV_FILE", "")
    assert resolve_env_file() is None


def test_a_path_is_used_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIM_ENV_FILE", "/tmp/demo.env")
    assert resolve_env_file() == "/tmp/demo.env"


def test_the_test_suite_itself_reads_no_dotenv() -> None:
    """The repo-root conftest sets `SIM_ENV_FILE=` before settings are imported."""
    import os

    assert os.environ.get("SIM_ENV_FILE") == ""


def test_read_env_value_prefers_the_environment_then_the_dotenv(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`read_env_value` — the seed passwords' lookup (`seed_users`, `voice_agent.tools.inject`)."""
    from pathlib import Path

    from app.config.settings import read_env_value

    env_file = Path(str(tmp_path)) / "demo.env"
    env_file.write_text("SIM_SEED_X=from-file\nSIM_SEED_EMPTY=\n", encoding="utf-8")
    monkeypatch.setenv("SIM_ENV_FILE", str(env_file))
    monkeypatch.delenv("SIM_SEED_X", raising=False)
    assert read_env_value("SIM_SEED_X") == "from-file"
    monkeypatch.setenv("SIM_SEED_X", "from-shell")
    assert read_env_value("SIM_SEED_X") == "from-shell"
    assert read_env_value("SIM_SEED_EMPTY") is None
    assert read_env_value("SIM_SEED_ABSENT") is None
    monkeypatch.setenv("SIM_ENV_FILE", "")
    monkeypatch.delenv("SIM_SEED_X", raising=False)
    assert read_env_value("SIM_SEED_X") is None
