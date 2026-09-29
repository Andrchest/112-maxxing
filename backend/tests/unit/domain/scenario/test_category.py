"""A scenario's event category (I7 E53, G13; ТЗ ¶324/¶334; `app.domain.scenario.category`).

* every one of the organizer's ticket scenarios maps to a classifier group — through its prefab
  card's `incident.classifier_code` or, when the ticket names no row, its `incident.types` chip;
* the classifier row wins over the chip; an unknown code falls back to the chip; nothing known,
  or no classifier (a schema-1 / legacy scenario), is «без категории» (`None`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from app.domain.routing.classifier import Classifier
from app.domain.scenario.category import ScenarioCategory, scenario_category
from app.infrastructure.reference.file_catalog import FileReferenceCatalog

TICKETS_DIR = Path(__file__).resolve().parents[5] / "scenarios" / "tickets"
PACK = "v046_24-r1"
CLASSIFIER = FileReferenceCatalog().catalog().classifier(PACK)
FIRE = ScenarioCategory(group_no=1, name_ru="Пожары и задымления")


def _classifier() -> Classifier:
    assert CLASSIFIER is not None
    return CLASSIFIER


def _ticket_files() -> list[Path]:
    return sorted(TICKETS_DIR.glob("*/v*.yaml"))


def _card_values(document: dict[str, Any]) -> dict[str, Any]:
    prefab = (document.get("expected_response") or {}).get("prefab_handoff") or {}
    values: dict[str, Any] = prefab.get("card_values") or {}
    return values


def test_there_are_108_ticket_scenarios() -> None:
    assert len(_ticket_files()) == 108


@pytest.mark.parametrize("path", _ticket_files(), ids=lambda path: path.parent.name)
def test_every_ticket_scenario_has_a_category(path: Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    values = _card_values(document)
    code = values.get("incident.classifier_code")

    category = scenario_category(
        _classifier(),
        classifier_code=code,
        incident_types=tuple(values.get("incident.types") or ()),
    )

    assert category is not None, path.parent.name
    if code is not None:
        row = _classifier().row(code)
        assert row is not None
        assert category.group_no == row.group_no


def test_the_classifier_row_wins_over_the_chip() -> None:
    category = scenario_category(_classifier(), classifier_code="1010101", incident_types=("2",))
    assert category == FIRE


def test_an_unknown_code_falls_back_to_the_first_group_chip() -> None:
    category = scenario_category(
        _classifier(), classifier_code="0", incident_types=("THANKS", "10:radiatsiya")
    )
    assert category == ScenarioCategory(
        group_no=10, name_ru="Аварии на опасных и производственных объектах"
    )


def test_nothing_known_or_no_classifier_is_no_category() -> None:
    assert scenario_category(_classifier(), classifier_code=None, incident_types=()) is None
    assert scenario_category(_classifier(), classifier_code=None, incident_types=("99",)) is None
    assert scenario_category(None, classifier_code="1010101", incident_types=("1",)) is None
