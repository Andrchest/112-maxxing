"""Scenario test fixtures: the committed demo document and helpers to write copies of it.

Every failing fixture used by `backend/tests/unit/domain/scenario/` is produced at test time by
applying one minimal mutation to `demo_document()`, so a fixture can never drift away from the
scenario the gate actually validates.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
DEMO_SCENARIO_PATH = REPO_ROOT / "scenarios" / "examples" / "apartment-fire" / "v1.yaml"
EXAMPLES_DIR = REPO_ROOT / "scenarios" / "examples"


def demo_document() -> dict[str, Any]:
    """A fresh mutable copy of the committed demo scenario document."""
    with DEMO_SCENARIO_PATH.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    assert isinstance(document, dict)
    return copy.deepcopy(document)


def write_scenario(directory: Path, document: dict[str, Any], slug: str = "apartment-fire") -> Path:
    """Write `document` as `<directory>/<slug>/v<version>.yaml` and return the file path."""
    target_dir = directory / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"v{document['version']}.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path
