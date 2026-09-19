"""Smoke test proving the `voice_agent` package imports and depends on `sim-backend` correctly."""

from __future__ import annotations

import voice_agent
import voice_agent.transport
from app.config.settings import Settings


def test_voice_agent_package_imports() -> None:
    assert voice_agent is not None
    assert voice_agent.transport is not None


def test_voice_agent_can_reach_backend_settings_class() -> None:
    # Proves the workspace dependency on `sim-backend` (D1) resolves at import time.
    assert Settings.model_fields["database_url"] is not None
