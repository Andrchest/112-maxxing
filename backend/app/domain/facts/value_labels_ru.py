"""`ENUM_VALUE_LABELS_RU` + `render_value_ru` — caller-style Russian rendering of a `FactValue`.

MANAGER RULING (E13-B4 item 0, on E13-B2's HLD gap 4): today an ENUM-typed caller value reaches
the caller prompt and §7.8 row 2 verbatim — the caller would say «FIRE». This module gives every
enum a scenario fact can name a natural, caller-style Russian wording («пожар», «кухня» — not the
trainee-facing UI label a `*_RU` table elsewhere in this package renders), plus the one renderer
every `value_ru` field in this epic goes through.

Coverage — "every enum that scenario facts can name" (the fact side, i.e. `FactDefinition.enum_name`
/ `WorldFactSpec.enum_name`, `docs/hld/30-scenario-format.md` §30.2):

* Code-backed enums — the union of what `app.domain.layers.operator_card._ENUM_REGISTRY` resolves
  (`IncidentType`, `CallerRelationship`) and what `app.domain.scenario.validation` resolves
  `enum_name` with (nothing: that module only checks `isinstance(value, str)` and that `enum_name`
  is set — see its `_value_matches_type`, which cannot check membership because a scenario-local
  domain has no Python counterpart). Each code-backed table is asserted TOTAL over its `Enum`
  members at import time: a new member without a Russian label fails the import, not a turn.
* Scenario-local value domains (`FireSource` in the demo scenario — `10-domain-model.md` §10.4's
  join note names it as the example of a domain "that has no Python counterpart, so membership
  cannot be checked"). No enumerable Python type exists for these, so totality cannot be
  mechanically asserted the way it is for the code-backed tables above. Every member that actually
  appears in a shipped scenario (`scenarios/examples/**`) is registered by hand below;
  `render_value_ru` falls back to `str(value)` for an unregistered `enum_name` or member rather than
  raising mid-turn. Reported as an HLD gap in this task's report, not invented as a product
  requirement here: a full scenario-local value-domain registry (all members, not just the ones a
  shipped scenario happens to use) belongs with whoever owns the scenario format.

`FactDefinition` itself gained the `enum_name: str | None` field this module needs (it was joined
from `WorldFactSpec.enum_name` at scenario-load time but dropped by the §10.4 join before this
task) — a one-field, one-line extension of `backend/app/domain/facts/definitions.py` and
`app.domain.scenario.validation.build_fact_definitions`, outside this task's literal FILES list but
unavoidable: `evaluate_fact_access` cannot render a caller ENUM value into Russian from
`value_type` alone. Flagged in the report.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.common.values import FactValue
from app.domain.enums import CallerRelationship, IncidentType, ValueType

__all__ = ["ENUM_VALUE_LABELS_RU", "render_value_ru"]

#: `IncidentType` (SPEC's card value domain) in the caller's own, natural wording — not
#: `docs/hld`'s UI label for the same enum, which is trainee-facing text for a different surface.
_INCIDENT_TYPE_RU: dict[str, str] = {
    IncidentType.FIRE.value: "пожар",
    IncidentType.MEDICAL.value: "медицинский случай",
    IncidentType.CRIME.value: "преступление",
    IncidentType.TRAFFIC_ACCIDENT.value: "авария",
    IncidentType.GAS_LEAK.value: "утечка газа",
    IncidentType.UTILITY_FAILURE.value: "авария на коммуникациях",
    IncidentType.RESCUE.value: "спасательная операция",
    IncidentType.OTHER.value: "происшествие",
}

_CALLER_RELATIONSHIP_RU: dict[str, str] = {
    CallerRelationship.VICTIM.value: "пострадавший",
    CallerRelationship.WITNESS.value: "свидетель",
    CallerRelationship.NEIGHBOUR.value: "сосед",
    CallerRelationship.RELATIVE.value: "родственник",
    CallerRelationship.PASSERBY.value: "прохожий",
    CallerRelationship.OFFICIAL.value: "должностное лицо",
    CallerRelationship.UNKNOWN.value: "неизвестно",
}

#: Scenario-local (`FireSource`-shaped) domain found in shipped scenario data
#: (`scenarios/examples/apartment-fire/v1.yaml`'s `incident.fire_source`). See the module
#: docstring's coverage note: not asserted total, no Python enum exists to assert it against.
_FIRE_SOURCE_RU: dict[str, str] = {
    "KITCHEN": "кухня",
}

ENUM_VALUE_LABELS_RU: Mapping[str, Mapping[str, str]] = {
    "IncidentType": _INCIDENT_TYPE_RU,
    "CallerRelationship": _CALLER_RELATIONSHIP_RU,
    "FireSource": _FIRE_SOURCE_RU,
}

#: `enum_name`s backed by a real Python `Enum` — asserted total against `ENUM_VALUE_LABELS_RU`
#: immediately below. Scenario-local domains (`FireSource`) are deliberately not in this registry.
_CODE_ENUM_REGISTRY: Mapping[str, type[IncidentType] | type[CallerRelationship]] = {
    "IncidentType": IncidentType,
    "CallerRelationship": CallerRelationship,
}

for _enum_name, _enum_cls in _CODE_ENUM_REGISTRY.items():
    _table = ENUM_VALUE_LABELS_RU[_enum_name]
    _missing = sorted(member.value for member in _enum_cls if member.value not in _table)
    if _missing:  # pragma: no cover - a startup assertion, not a branch under test
        raise RuntimeError(
            f"ENUM_VALUE_LABELS_RU[{_enum_name!r}] has no Russian label for: {', '.join(_missing)}"
        )
del _enum_name, _enum_cls, _table, _missing


def render_value_ru(value: FactValue, value_type: ValueType, enum_name: str | None) -> str:
    """The caller-style Russian spoken form of one `FactValue` (§7.8 row 2's `{caller_value_ru}`).

    `ENUM` looks `value` up in `ENUM_VALUE_LABELS_RU[enum_name]`; an unregistered `enum_name` or
    member (a scenario-local domain this module was not told about — see the coverage note above)
    falls back to `str(value)` rather than raising mid-turn. `BOOLEAN` -> «да»/«нет» (a caller says
    "yes", not "true"). `STRING_LIST` -> «, »-joined. Everything else (`STRING`, `INTEGER`,
    `FLOAT`, and `None` of any type) -> `str(value)` (`None` -> `""`).
    """
    if value is None:
        return ""
    if value_type is ValueType.ENUM:
        table = ENUM_VALUE_LABELS_RU.get(enum_name or "", {})
        label = table.get(str(value))
        return label if label is not None else str(value)
    if value_type is ValueType.BOOLEAN:
        return "да" if value else "нет"
    if value_type is ValueType.STRING_LIST:
        if isinstance(value, list | tuple):
            return ", ".join(str(item) for item in value)
        return str(value)
    return str(value)
