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


#: The fact E17's condition-gated fixture puts behind a `Condition`. An existing demo fact, so the
#: join across the three sections stays total (§30.8 rules 2-4); one the caller actually knows, so
#: §10.12's row 3 (`CALLER_DOES_NOT_KNOW`) cannot mask the row 4 the fixture is about; and one the
#: demo does not already gate, so the fixture adds the clause rather than replacing one.
CONDITION_GATED_FACT_ID = "address.landmark"

#: A gate-evaluable `available_after` (E17 ruling R3, §30.8 rule 31): the caller mentions the gas
#: landmark only once the operator has begun writing the card down. `action` reads the folded
#: session event log, which is exactly what the dialogue turn's `ConditionContext` is built from —
#: no `WorldTruth`, no resource board.
CONDITION_GATED_AVAILABLE_AFTER: dict[str, Any] = {
    "condition": {"action": {"event_type": "CARD_FIELD_CHANGED", "op": "OCCURRED"}}
}


def condition_gated_document() -> dict[str, Any]:
    """The demo document with one fact put behind a condition-shaped `available_after` (E17 R3).

    A **test** fixture: the committed demo scenario deliberately keeps no condition-gated fact, so
    that the `available_after` paths stay covered without any of the other suites' expectations
    moving. Everything else about the document is untouched, so it still validates clean.
    """
    document = demo_document()
    facts = document["disclosure_rules"]["facts"]
    facts[CONDITION_GATED_FACT_ID]["available_after"] = copy.deepcopy(
        CONDITION_GATED_AVAILABLE_AFTER
    )
    return document
