"""`SIM_REFERENCE_DIR` (I3 E2a, HLD 70 §70.6.1): the reference pack's directory.

The default resolves from `backend/app/config/settings.py` to `<repo>/reference`, the same layout
the backend image reproduces under `/workspace` (`backend/Dockerfile` COPYs `reference/`), so a
checkout and a container both find `manifest.json` without configuration; an explicit value wins.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config.settings import Settings
from app.infrastructure.reference.file_catalog import DEFAULT_REFERENCE_DIR

REPO_ROOT = Path(__file__).resolve().parents[4]

_BASE_KWARGS = {
    "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
    "redis_url": "redis://localhost:56379/0",
    "livekit_url": "ws://localhost:7880",
    "livekit_api_key": "devkey",
    "livekit_api_secret": "devsecret1234567890",
    "llm_base_url": "http://localhost:8080/v1",
    "jwt_secret": "x" * 32,
}


def test_the_default_resolves_to_the_repository_reference_manifest() -> None:
    reference_dir = Path(Settings.model_fields["reference_dir"].default)
    assert reference_dir == REPO_ROOT / "reference"
    assert (reference_dir / "manifest.json").is_file()
    assert reference_dir == DEFAULT_REFERENCE_DIR


def test_an_explicit_value_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIM_REFERENCE_DIR", "/workspace/reference")
    settings = Settings(**_BASE_KWARGS)  # type: ignore[arg-type]
    assert settings.reference_dir == "/workspace/reference"
