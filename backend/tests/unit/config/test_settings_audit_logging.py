"""I4 E25's settings: `SIM_AUDIT_RETENTION_DAYS` (ТЗ ¶297, ≥ 183), `SIM_LOG_FORMAT`, `SIM_LOG_DIR`
(`71-i4-wave4.md` §71.2, D31)."""

from __future__ import annotations

import pytest
from app.config.settings import AUDIT_RETENTION_MIN_DAYS, Settings
from pydantic import ValidationError

_BASE_KWARGS = {
    "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
    "redis_url": "redis://localhost:56379/0",
    "jwt_secret": "x" * 32,
    "livekit_url": "ws://localhost:7880",
    "livekit_api_key": "devkey",
    "livekit_api_secret": "devsecret1234567890",
    "llm_base_url": "http://localhost:8080/v1",
}


def test_the_floor_is_six_months() -> None:
    assert AUDIT_RETENTION_MIN_DAYS == 183


@pytest.mark.parametrize("days", [0, 30, 182])
def test_a_retention_below_183_days_is_refused_at_settings_load(days: int) -> None:
    with pytest.raises(ValidationError, match="SIM_AUDIT_RETENTION_DAYS must be at least 183"):
        Settings(audit_retention_days=days, **_BASE_KWARGS)  # type: ignore[arg-type]


def test_a_retention_below_183_days_from_the_environment_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIM_AUDIT_RETENTION_DAYS", "182")
    with pytest.raises(ValidationError, match="at least 183"):
        Settings(**_BASE_KWARGS)  # type: ignore[arg-type]


@pytest.mark.parametrize("days", [183, 365, 3650])
def test_a_retention_of_at_least_183_days_is_accepted(days: int) -> None:
    settings = Settings(audit_retention_days=days, **_BASE_KWARGS)  # type: ignore[arg-type]
    assert settings.audit_retention_days == days


def test_the_defaults_are_one_year_json_and_no_log_file(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SIM_AUDIT_RETENTION_DAYS", "SIM_LOG_FORMAT", "SIM_LOG_DIR"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(**_BASE_KWARGS)  # type: ignore[arg-type]
    assert settings.audit_retention_days == 365
    assert settings.log_format == "json"
    assert settings.log_dir == ""


def test_the_log_format_is_json_or_text_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIM_LOG_FORMAT", "text")
    assert Settings(**_BASE_KWARGS).log_format == "text"  # type: ignore[arg-type]
    monkeypatch.setenv("SIM_LOG_FORMAT", "xml")
    with pytest.raises(ValidationError):
        Settings(**_BASE_KWARGS)  # type: ignore[arg-type]
