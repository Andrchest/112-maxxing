"""A scenario's event category — «категория событий» (I7 E53, G13; ТЗ ¶324/¶334 «Выбор
Преподавателем категории событий… (возможен множественный выбор)», ¶239 «тип происшествия»; HLD
`71-i4-wave4.md` §71.19.53).

No scenario key carries a category, and none is added: it is *derived* from what the scenario
already says about its incident, against the classifier of its own reference pack
(`reference/classifier/v046_24.json`, whose 24 groups are the organizer's categories):

1. the classifier row of `incident.classifier_code` — the prefab card's value
   (`expected_response.prefab_handoff.card_values`), else the `world_truth` fact of that id —
   gives its `group_no` / `group_ru`;
2. otherwise the first card «Что случилось?» chip (`incident.types`) whose code is a classifier
   group number (`'1'` … `'24'`, `'10:…'` — the v2 card schema's codes are the group numbers)
   gives that group;
3. otherwise there is no category («без категории» in the UI) — a schema-1 scenario, or a pack
   without a classifier.

Pure: the adapter reads the three raw values, the application passes the pack's classifier.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from app.domain.routing.classifier import Classifier

__all__ = ["ScenarioCategory", "scenario_category"]


class ScenarioCategory(BaseModel):
    """One classifier group, as the category of a scenario."""

    model_config = ConfigDict(frozen=True)

    group_no: int
    name_ru: str


def _groups(classifier: Classifier) -> dict[int, str]:
    groups: dict[int, str] = {}
    for row in classifier.rows:
        groups.setdefault(row.group_no, row.group_ru)
    return groups


def _group_no_of_type(code: str) -> int | None:
    head = code.split(":", 1)[0].strip()
    return int(head) if head.isdigit() else None


def scenario_category(
    classifier: Classifier | None,
    *,
    classifier_code: str | None,
    incident_types: Sequence[str] = (),
) -> ScenarioCategory | None:
    """The category of a scenario version whose incident facts are these (see the module)."""
    if classifier is None:
        return None
    if classifier_code:
        row = classifier.row(classifier_code)
        if row is not None:
            return ScenarioCategory(group_no=row.group_no, name_ru=row.group_ru)
    groups = _groups(classifier)
    for code in incident_types:
        group_no = _group_no_of_type(code)
        if group_no is not None and group_no in groups:
            return ScenarioCategory(group_no=group_no, name_ru=groups[group_no])
    return None
