"""Scenario domain types and load-time validation (HLD `10-domain-model.md` §10.15,
`30-scenario-format.md`, SPEC §4, D4).

`version.py` holds `Scenario`/`ScenarioVersion`, `sections.py` the nested section models, and
`validation.py` the thirty §30.8 load-time rules plus the §10.4 three-section fact join.
"""

from __future__ import annotations

from app.domain.scenario.validation import (
    build_fact_definitions,
    validate_scenario_document,
    validate_scenario_version,
)
from app.domain.scenario.version import SUPPORTED_SCHEMA_VERSIONS, Scenario, ScenarioVersion

__all__ = [
    "SUPPORTED_SCHEMA_VERSIONS",
    "Scenario",
    "ScenarioVersion",
    "build_fact_definitions",
    "validate_scenario_document",
    "validate_scenario_version",
]
