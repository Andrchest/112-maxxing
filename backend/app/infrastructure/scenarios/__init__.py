"""Scenario source files on disk (HLD `30-scenario-format.md`, D4).

The only place that knows scenario files are YAML under `scenarios/examples/<slug>/v<N>.yaml`;
the domain models and their validation know nothing about paths or I/O (D2).
"""

from __future__ import annotations

from app.infrastructure.scenarios.yaml_loader import discover, load_scenario_version

__all__ = ["discover", "load_scenario_version"]
