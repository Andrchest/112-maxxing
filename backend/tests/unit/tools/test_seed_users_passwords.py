"""Where `seed_users` finds the seed passwords (E20): the environment, else `Settings`' dotenv."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.application.ports.user_repository import UserRole
from app.tools.seed_users import MissingSeedPasswordError, SeedAccount, _password

ACCOUNT = SeedAccount(
    username="trainee",
    display_name_ru="Стажёр",
    user_role=UserRole.TRAINEE,
    password_env="SIM_SEED_TRAINEE_PASSWORD",
)


def _dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    env_file = tmp_path / "demo.env"
    env_file.write_text(body, encoding="utf-8")
    monkeypatch.setenv("SIM_ENV_FILE", str(env_file))


def test_a_fresh_env_file_is_enough(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`cp .env.example .env && make demo-init` — nothing exported, the file supplies it."""
    monkeypatch.delenv("SIM_SEED_TRAINEE_PASSWORD", raising=False)
    _dotenv(tmp_path, monkeypatch, "SIM_SEED_TRAINEE_PASSWORD=from-the-file\n")
    assert _password(ACCOUNT) == "from-the-file"


def test_the_environment_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIM_SEED_TRAINEE_PASSWORD", "from-the-shell")
    _dotenv(tmp_path, monkeypatch, "SIM_SEED_TRAINEE_PASSWORD=from-the-file\n")
    assert _password(ACCOUNT) == "from-the-shell"


def test_missing_everywhere_is_still_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SIM_SEED_TRAINEE_PASSWORD", raising=False)
    _dotenv(tmp_path, monkeypatch, "SIM_SEED_ADMIN_PASSWORD=not-the-one\n")
    with pytest.raises(MissingSeedPasswordError):
        _password(ACCOUNT)


def test_no_dotenv_at_all_reads_only_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIM_ENV_FILE", "")
    monkeypatch.delenv("SIM_SEED_TRAINEE_PASSWORD", raising=False)
    with pytest.raises(MissingSeedPasswordError):
        _password(ACCOUNT)
