"""`forbidden_values` — the §7.6 world-value leak set (HLD `50-voice-pipeline.md` §7.6, D10).

"The validator receives `forbidden_values` = every `world_value` and every `caller_value` in the
`ScenarioVersion` that is **not** in the current `AllowedFactsPackage` and not already revealed."

Pure and synchronous. This module is one of the three in `app.application.dialogue` that may see a
`FactDefinition` at all (R3): the prompt builder, the generator and the caller prompts may not, and
an import scan enforces that. The values computed here go to the **validator**, which is code; they
never enter a prompt, because `CallerPromptBuilder` has no parameter they could arrive through.

§7.6's two exclusions are applied here rather than in the validator, so the set that crosses the
boundary is already the minimal one: "values shorter than 2 characters and boolean values are
skipped (they carry no information and would false-positive constantly)".
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.common.values import FactValue
from app.domain.enums import ValueType
from app.domain.facts.definitions import FactDefinition
from app.domain.facts.gate import AllowedFactsPackage
from app.domain.facts.value_labels_ru import render_value_ru

__all__ = ["MIN_FORBIDDEN_VALUE_CHARS", "forbidden_values"]

#: §7.6: "Values shorter than 2 characters … are skipped".
MIN_FORBIDDEN_VALUE_CHARS = 2


def _renderable(value: FactValue) -> str | None:
    """The string form §7.6 compares, or `None` when the value is skipped."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, list | tuple):
        rendered = " ".join(str(item) for item in value)
    else:
        rendered = str(value)
    rendered = rendered.strip()
    if len(rendered) < MIN_FORBIDDEN_VALUE_CHARS:
        return None
    return rendered


def forbidden_values(
    definitions: Mapping[str, FactDefinition],
    package: AllowedFactsPackage,
    revealed_fact_ids: frozenset[str],
) -> tuple[str, ...]:
    """Every scenario value the caller may not say this turn, deduplicated in scenario order.

    An `ENUM`-typed value also contributes its Russian rendering (`app.domain.facts.
    value_labels_ru.render_value_ru`) beside the raw member name: §7.6's leak check runs against
    the caller's normalised *speech*, and a caller who leaks the fire source says «кухня», never
    `KITCHEN` (E13-B4 item 0).
    """
    released = {fact.fact_id for fact in package.allowed} | set(revealed_fact_ids)
    found: list[str] = []
    seen: set[str] = set()

    def _add(rendered: str | None) -> None:
        if rendered is None or rendered in seen:
            return
        seen.add(rendered)
        found.append(rendered)

    for fact_id, definition in definitions.items():
        if fact_id in released:
            continue
        for value in (definition.world_value, definition.caller_value):
            _add(_renderable(value))
            if definition.value_type is ValueType.ENUM and value is not None:
                _add(
                    _renderable(render_value_ru(value, definition.value_type, definition.enum_name))
                )
    return tuple(found)
