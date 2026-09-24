"""Scenario load-time validation and the three-section fact join (HLD `30-scenario-format.md`
§30.8, `10-domain-model.md` §10.4, §10.15, D4, SPEC §4, §5, §11, §12, §28).

Two public entry points:

* `validate_scenario_version(version, *, role_modules=ROLE_MODULES, reference=LEGACY_REFERENCE)` —
  the rules of §30.8 (R01-R31, plus I3's R32-R40, HLD 70 §70.2.3, and R43, HLD 30 §30.13)
  against an already-parsed `ScenarioVersion`. It raises **one** `ScenarioValidationError` whose
  `violations` lists *every* violation found, each message starting with `R<nn>:` and naming the
  offending id or path.
* `validate_scenario_document(document, *, role_modules=ROLE_MODULES, reference=…)` — the same rules
  against a raw mapping (a `yaml.safe_load` result). Several §30.8 rules are structural and are
  therefore already enforced by the Pydantic models of `sections.py`, `world/events.py` and
  `world/conditions.py`, so a document violating them never becomes a `ScenarioVersion` at all:
  rule 1 (unknown keys), rules 24-25 (world-event ranges) and rule 26 (`Condition` parses). This
  function parses first and maps each `pydantic.ValidationError` back onto its rule number, so
  that a caller validating a *file* sees the same `R<nn>:` vocabulary for every rule.

`build_fact_definitions(version)` performs the §10.4 three-section join.

`validate_scenario_version` re-checks rules 24-26 defensively even though the models already
enforce them: the function is documented as implementing all thirty rules, and a future relaxation
of a model must not silently drop a rule.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from app.domain.common.errors import CardFieldError, ScenarioValidationError
from app.domain.common.values import FactValue
from app.domain.dds.policy import policy_of
from app.domain.dds.responders import script_problems
from app.domain.enums import (
    EffectKind,
    KnowledgeState,
    RoleType,
    ValueType,
    WorldEventKind,
)
from app.domain.facts.definitions import AvailableAfter, FactDefinition
from app.domain.facts.gate import unsupported_available_after_leaves
from app.domain.layers.card_schema import CardOptionUnknownError, CardSchema, check_value
from app.domain.roles import ROLE_MODULES
from app.domain.roles.module import RoleModule
from app.domain.routing.catalog import LEGACY_REFERENCE, ReferenceCatalog
from app.domain.scenario.sections import (
    CALLS_PER_TICKET,
    TICKET_COUNT,
    CallerFactSpec,
    ProvenanceSource,
    WorldFactSpec,
)
from app.domain.scenario.version import SUPPORTED_SCHEMA_VERSIONS, ScenarioVersion
from app.domain.scoring.evaluators.registry import parse_rule_config
from app.domain.scoring.evaluators.resource_selection import ResourceSelectionConfig
from app.domain.scoring.evaluators.service_selection import ServiceSelectionConfig
from app.domain.session.variants import (
    SWITCH_ENUMS,
    SWITCHES,
    CardSource,
    DdsMode,
    ScenarioVariants,
)
from app.domain.world.conditions import Condition
from app.domain.world.events import WorldEventDefinition

__all__ = [
    "VALIDATION_RULE_NUMBERS",
    "build_fact_definitions",
    "scenario_version_violations",
    "scenario_version_warnings",
    "validate_scenario_document",
    "validate_scenario_version",
]


# `ScoringRule.config` keys that name a scenario `fact_id` (§30.8 rule 11).
_CONFIG_FACT_ID_KEYS: tuple[str, ...] = ("fact_id", "expected_from_fact_id", "contradicts_fact_id")
# `ScoringRule.config` keys that name a card `field_path` (§30.8 rule 14).
_CONFIG_FIELD_PATH_KEY = "field_path"
_CONFIG_FIELD_PATH_LIST_KEY = "required_field_paths"
# `ScoringRule.config` key that names `available_resources` entries (§30.8 rule 16).
_CONFIG_RESOURCE_ID_LIST_KEY = "forbidden_resource_ids"


# ---------------------------------------------------------------------------------------------
# Structure walkers
# ---------------------------------------------------------------------------------------------


def _iter_conditions(condition: Condition | None) -> Iterator[Condition]:
    """Yield `condition` and every nested `Condition` node."""
    if condition is None:
        return
    yield condition
    for child in condition.all or ():
        yield from _iter_conditions(child)
    for child in condition.any or ():
        yield from _iter_conditions(child)
    yield from _iter_conditions(condition.not_)


def _condition_fact_ids(condition: Condition | None) -> list[str]:
    return [node.fact.fact_id for node in _iter_conditions(condition) if node.fact is not None]


def _condition_resource_ids(condition: Condition | None) -> list[str]:
    return [
        node.resource.selector.resource_id
        for node in _iter_conditions(condition)
        if node.resource is not None and node.resource.selector.resource_id is not None
    ]


def _event_condition(event: WorldEventDefinition) -> Condition | None:
    return getattr(event, "condition", None)


def _event_fact_ids(event: WorldEventDefinition) -> list[str]:
    fact_ids = list(_condition_fact_ids(_event_condition(event)))
    for effect in event.effects:
        if effect.kind in (EffectKind.MUTATE_WORLD_TRUTH, EffectKind.MUTATE_CALLER_BELIEF):
            fact_ids.extend(effect.changes)
    return fact_ids


def _event_resource_ids(event: WorldEventDefinition) -> list[str]:
    resource_ids = list(_condition_resource_ids(_event_condition(event)))
    for effect in event.effects:
        # `ALTER_RESOURCE_AVAILABILITY` and `CREATE_RADIO_MESSAGE` are the effect kinds carrying a
        # `resource_id` today; reading the attribute covers any later kind that grows one.
        resource_id = getattr(effect, "resource_id", None)
        if isinstance(resource_id, str):
            resource_ids.append(resource_id)
    return resource_ids


def _event_triggered_ids(event: WorldEventDefinition) -> list[tuple[str, int]]:
    """`(world_event_id, delay_ms)` for every `TRIGGER_EVENT` effect of `event`."""
    return [
        (effect.world_event_id, effect.delay_ms)
        for effect in event.effects
        if effect.kind is EffectKind.TRIGGER_EVENT
    ]


def _available_after_clauses(version: ScenarioVersion) -> Iterator[tuple[str, AvailableAfter]]:
    for fact_id, spec in version.disclosure_rules.facts.items():
        if spec.available_after is not None:
            yield fact_id, spec.available_after


# ---------------------------------------------------------------------------------------------
# Value typing
# ---------------------------------------------------------------------------------------------


def _value_matches_type(value: FactValue, value_type: ValueType, enum_name: str | None) -> bool:
    """True when `value` is admissible for `value_type` (`None` always is).

    `ENUM` only requires a string plus a declared `enum_name`: `enum_name` names a scenario-local
    value domain (`FireSource` in the demo) that has no Python counterpart, so membership cannot be
    checked here.
    """
    if value is None:
        return True
    if value_type is ValueType.STRING:
        return isinstance(value, str)
    if value_type is ValueType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type is ValueType.FLOAT:
        return isinstance(value, int | float) and not isinstance(value, bool)
    if value_type is ValueType.BOOLEAN:
        return isinstance(value, bool)
    if value_type is ValueType.ENUM:
        return isinstance(value, str) and enum_name is not None
    if value_type is ValueType.STRING_LIST:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False


# ---------------------------------------------------------------------------------------------
# The thirty rules
# ---------------------------------------------------------------------------------------------


def _check_schema_version(version: ScenarioVersion, out: list[str]) -> None:
    if version.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(str(v) for v in sorted(SUPPORTED_SCHEMA_VERSIONS))
        out.append(
            f"R01: schema_version {version.schema_version} is not supported "
            f"(supported: {supported})"
        )
    # R01 (extended, HLD 70 §70.2.3): a key schema 2 introduced is refused in a schema-1
    # document — `variants` (E1), `reference_pack` (E2a), `timers` (E4a), `provenance` (E8) and
    # `expected_response.responders` (E5b).
    if version.schema_version < 2:
        for key in ("variants", "reference_pack", "timers", "provenance"):
            if getattr(version, key) is not None:
                out.append(
                    f"R01: {key} is a schema_version 2 key; schema_version "
                    f"{version.schema_version} does not allow it"
                )
        if version.expected_response.responders is not None:
            out.append(
                "R01: expected_response.responders is a schema_version 2 key; schema_version "
                f"{version.schema_version} does not allow it"
            )


def _check_fact_sections(version: ScenarioVersion, out: list[str]) -> None:
    world = version.world_truth.facts
    caller = version.caller_knowledge.facts
    disclosure = version.disclosure_rules.facts

    for fact_id in sorted(set(caller) - set(world)):
        out.append(f"R02: caller_knowledge.facts['{fact_id}'] has no world_truth.facts entry")
    for fact_id in sorted(set(disclosure) - set(world)):
        out.append(f"R03: disclosure_rules.facts['{fact_id}'] has no world_truth.facts entry")
    for fact_id in sorted(world):
        if fact_id not in caller:
            out.append(f"R04: world_truth.facts['{fact_id}'] has no caller_knowledge.facts entry")
        if fact_id not in disclosure:
            out.append(f"R04: world_truth.facts['{fact_id}'] has no disclosure_rules.facts entry")


def _check_knowledge_states(version: ScenarioVersion, out: list[str]) -> None:
    world = version.world_truth.facts
    for fact_id, caller_spec in sorted(version.caller_knowledge.facts.items()):
        if not 0.0 <= caller_spec.certainty <= 1.0:
            out.append(
                f"R09: caller_knowledge.facts['{fact_id}'].certainty "
                f"{caller_spec.certainty} is outside 0.0-1.0"
            )
        world_spec = world.get(fact_id)
        if world_spec is None:
            # Reported by rule 2; the value-dependent rules have nothing to compare against.
            continue
        _check_one_knowledge_state(fact_id, caller_spec, world_spec, out)
        _check_one_value_type(fact_id, caller_spec, world_spec, out)


def _check_one_knowledge_state(
    fact_id: str, caller: CallerFactSpec, world: WorldFactSpec, out: list[str]
) -> None:
    if caller.knowledge is KnowledgeState.KNOWN and caller.caller_value != world.world_value:
        out.append(
            f"R05: caller_knowledge.facts['{fact_id}']: KNOWN requires "
            f"caller_value == world_value ({caller.caller_value!r} != {world.world_value!r})"
        )
    elif caller.knowledge is KnowledgeState.UNKNOWN and caller.caller_value is not None:
        out.append(
            f"R06: caller_knowledge.facts['{fact_id}']: UNKNOWN requires caller_value null, "
            f"got {caller.caller_value!r}"
        )
    elif caller.knowledge is KnowledgeState.INCORRECT_BELIEF and (
        caller.caller_value is None or caller.caller_value == world.world_value
    ):
        out.append(
            f"R07: caller_knowledge.facts['{fact_id}']: INCORRECT_BELIEF requires a non-null "
            f"caller_value differing from world_value (got {caller.caller_value!r})"
        )
    elif caller.knowledge is KnowledgeState.UNCERTAIN and (
        caller.caller_value is None or caller.certainty >= 1.0
    ):
        out.append(
            f"R08: caller_knowledge.facts['{fact_id}']: UNCERTAIN requires a non-null "
            f"caller_value and certainty < 1.0 (got {caller.caller_value!r}, "
            f"certainty {caller.certainty})"
        )


def _check_one_value_type(
    fact_id: str, caller: CallerFactSpec, world: WorldFactSpec, out: list[str]
) -> None:
    if world.value_type is ValueType.ENUM and world.enum_name is None:
        out.append(f"R10: world_truth.facts['{fact_id}']: value_type ENUM requires enum_name")
    if not _value_matches_type(world.world_value, world.value_type, world.enum_name):
        out.append(
            f"R10: world_truth.facts['{fact_id}']: world_value {world.world_value!r} "
            f"does not match value_type {world.value_type.value}"
        )
    if not _value_matches_type(caller.caller_value, world.value_type, world.enum_name):
        out.append(
            f"R10: caller_knowledge.facts['{fact_id}']: caller_value {caller.caller_value!r} "
            f"does not match value_type {world.value_type.value}"
        )


def _check_fact_references(version: ScenarioVersion, out: list[str]) -> None:
    known = set(version.world_truth.facts)

    for rule in version.scoring_rules:
        for key in _CONFIG_FACT_ID_KEYS:
            fact_id = rule.config.get(key)
            if isinstance(fact_id, str) and fact_id not in known:
                out.append(
                    f"R11: scoring_rules['{rule.rule_id}'].config.{key} references "
                    f"unknown fact_id '{fact_id}'"
                )

    for event in version.world_events:
        for fact_id in _event_fact_ids(event):
            if fact_id not in known:
                out.append(
                    f"R12: world_events['{event.world_event_id}'] references "
                    f"unknown fact_id '{fact_id}'"
                )

    for fact_id in _condition_fact_ids(version.expected_response.resolution_condition):
        if fact_id not in known:
            out.append(
                f"R13: expected_response.resolution_condition references "
                f"unknown fact_id '{fact_id}'"
            )
    for owner_fact_id, clause in _available_after_clauses(version):
        for fact_id in _condition_fact_ids(clause.condition):
            if fact_id not in known:
                out.append(
                    f"R13: disclosure_rules.facts['{owner_fact_id}'].available_after.condition "
                    f"references unknown fact_id '{fact_id}'"
                )


def _check_card_field_paths(
    version: ScenarioVersion, reference: ReferenceCatalog, out: list[str]
) -> None:
    """Rule 14, against the card schema of the version's own pack (R38's card half, I3 E3a, HLD 70
    §70.2.3): every `field_path` / `required_field_paths` entry a scoring rule names (so
    `HANDOFF_COMPLETENESS` too) and every `prefab_handoff.card_values` key exists in that schema,
    and every prefab value fits its field — type, and option code for a v2 select/toggle set. A
    schema-1 document's pack is `legacy-r1`, whose schema `v1` is `CARD_FIELDS`, so nothing changes
    for it. An unknown pack is R38's to report; rule 14 then has no schema to check against."""
    schema = reference.card_schema(version.reference_pack_id)
    if schema is None:
        return
    for rule in version.scoring_rules:
        paths: list[str] = []
        single = rule.config.get(_CONFIG_FIELD_PATH_KEY)
        if isinstance(single, str):
            paths.append(single)
        listed = rule.config.get(_CONFIG_FIELD_PATH_LIST_KEY)
        if isinstance(listed, Sequence) and not isinstance(listed, str):
            paths.extend(item for item in listed if isinstance(item, str))
        for path in paths:
            if path not in schema:
                out.append(
                    f"R14: scoring_rules['{rule.rule_id}'] references unknown card "
                    f"field_path '{path}'{_schema_note(schema)}"
                )

    prefab = version.expected_response.prefab_handoff
    if prefab is None:
        return
    for path, value in prefab.card_values.items():
        spec = schema.spec(path)
        if spec is None:
            out.append(
                f"R14: expected_response.prefab_handoff.card_values['{path}'] is not a "
                + (
                    "CARD_FIELDS field_path"
                    if schema.schema_id == "v1"
                    else f"field_path of card schema {schema.schema_id}"
                )
            )
            continue
        try:
            check_value(spec, value)
        except CardOptionUnknownError:
            out.append(
                f"R14: expected_response.prefab_handoff.card_values['{path}'] value {value!r} "
                f"is not an option of the field (card schema {schema.schema_id})"
            )
        except CardFieldError:
            out.append(
                f"R14: expected_response.prefab_handoff.card_values['{path}'] value {value!r} "
                f"does not match value_type {spec.value_type.value}"
            )


def _schema_note(schema: CardSchema) -> str:
    """Name the schema in an R14 message unless it is `v1` (keeps the v1 messages verbatim)."""
    return "" if schema.schema_id == "v1" else f" of card schema {schema.schema_id}"


def _check_resources(version: ScenarioVersion, out: list[str]) -> None:
    resources = version.available_resources
    for label, values in (
        ("resource_id", [resource.resource_id for resource in resources]),
        ("callsign", [resource.callsign for resource in resources]),
    ):
        for duplicate in sorted(_duplicates(values)):
            out.append(f"R15: available_resources: duplicate {label} '{duplicate}'")

    known = {resource.resource_id for resource in resources}
    for event in version.world_events:
        for resource_id in _event_resource_ids(event):
            if resource_id not in known:
                out.append(
                    f"R16: world_events['{event.world_event_id}'] references unknown "
                    f"resource_id '{resource_id}'"
                )
    for rule in version.scoring_rules:
        listed = rule.config.get(_CONFIG_RESOURCE_ID_LIST_KEY)
        if not isinstance(listed, Sequence) or isinstance(listed, str):
            continue
        for resource_id in listed:
            if isinstance(resource_id, str) and resource_id not in known:
                out.append(
                    f"R16: scoring_rules['{rule.rule_id}'] references unknown "
                    f"resource_id '{resource_id}'"
                )

    covered = {capability for resource in resources for capability in resource.capabilities}
    for capability in version.expected_response.required_resource_capabilities:
        if capability not in covered:
            out.append(
                f"R17: expected_response.required_resource_capabilities: no available_resources "
                f"entry provides '{capability.value}'"
            )


def _check_role_chain(
    version: ScenarioVersion, role_modules: Mapping[RoleType, RoleModule], out: list[str]
) -> None:
    chain = version.role_chain
    if not chain:
        out.append("R18: role_chain is empty")
    for duplicate in sorted(role.value for role in _duplicates(chain)):
        out.append(f"R18: role_chain contains duplicate role '{duplicate}'")
    for role in chain:
        module = role_modules.get(role)
        if module is None:
            out.append(f"R18: role_chain role '{role.value}' is not a registered RoleModule")
        elif not module.implemented:
            out.append(f"R18: role_chain role '{role.value}' is registered but not implemented")


def _check_scoring_rules(version: ScenarioVersion, out: list[str]) -> None:
    for duplicate in sorted(_duplicates([rule.rule_id for rule in version.scoring_rules])):
        out.append(f"R19: scoring_rules: duplicate rule_id '{duplicate}'")
    for rule in version.scoring_rules:
        if rule.max_points <= 0:
            out.append(f"R19: scoring_rules['{rule.rule_id}'].max_points must be > 0")
        if rule.min_evidence < 1:
            out.append(f"R19: scoring_rules['{rule.rule_id}'].min_evidence must be >= 1")
        try:
            parse_rule_config(rule)
        except ValidationError as exc:
            out.append(
                f"R20: scoring_rules['{rule.rule_id}'].config is not a valid "
                f"{rule.evaluator_type.value} config: {_compact(exc)}"
            )


def _check_world_events(version: ScenarioVersion, out: list[str]) -> None:
    events = version.world_events
    by_id = {event.world_event_id: event for event in events}
    for duplicate in sorted(_duplicates([event.world_event_id for event in events])):
        out.append(f"R21: world_events: duplicate world_event_id '{duplicate}'")

    for event in events:
        for target_id, _delay in _event_triggered_ids(event):
            if target_id not in by_id:
                out.append(
                    f"R23: world_events['{event.world_event_id}'] TRIGGER_EVENT references "
                    f"unknown world_event_id '{target_id}'"
                )
    for owner_fact_id, clause in _available_after_clauses(version):
        if clause.world_event_id is not None and clause.world_event_id not in by_id:
            out.append(
                f"R23: disclosure_rules.facts['{owner_fact_id}'].available_after references "
                f"unknown world_event_id '{clause.world_event_id}'"
            )

    for cycle in _unconditional_cycles(by_id):
        out.append(f"R22: world_events: unconditional zero-delay cycle {' -> '.join(cycle)}")

    _check_world_event_ranges(events, out)


def _check_world_event_ranges(events: Sequence[WorldEventDefinition], out: list[str]) -> None:
    """Rules 24-25.

    Already enforced by `world/events.py`; re-checked defensively (see the module docstring).
    """
    for event in events:
        if event.kind is WorldEventKind.SEEDED_RANDOM:
            if not 0.0 <= event.probability <= 1.0:
                out.append(
                    f"R24: world_events['{event.world_event_id}'].probability "
                    f"{event.probability} is outside 0.0-1.0"
                )
            if event.check_every_ms <= 0:
                out.append(
                    f"R24: world_events['{event.world_event_id}'].check_every_ms must be > 0"
                )
            if event.window_end_ms is not None and event.window_end_ms <= event.window_start_ms:
                out.append(
                    f"R24: world_events['{event.world_event_id}'].window_end_ms must be greater "
                    f"than window_start_ms"
                )
        elif event.kind is WorldEventKind.TIMED and event.at_ms < 0:
            out.append(f"R25: world_events['{event.world_event_id}'].at_ms must be >= 0")
        elif event.kind is WorldEventKind.CONDITIONAL and event.check_after_ms < 0:
            out.append(f"R25: world_events['{event.world_event_id}'].check_after_ms must be >= 0")
        elif event.kind is WorldEventKind.ACTION_TRIGGERED and event.delay_ms < 0:
            out.append(f"R25: world_events['{event.world_event_id}'].delay_ms must be >= 0")


def _is_guarded(event: WorldEventDefinition) -> bool:
    """True when firing `event` is guarded or delayed, so an edge into it cannot close a cycle.

    "Guarding condition" is read literally (§30.8 rule 22): the target carries a `Condition`
    (`ConditionalEvent`, or a `SeededRandomEvent` with one). An `ActionTriggeredEvent` with a
    positive `delay_ms` is delayed and therefore also cannot close a zero-delay cycle. A
    `TimedEvent`'s `at_ms` is a schedule rather than a guard: once a `TRIGGER_EVENT` effect fires
    the event explicitly, `at_ms` no longer holds it back, so it does not make the edge safe.
    """
    if _event_condition(event) is not None:
        return True
    if event.kind is WorldEventKind.SEEDED_RANDOM:
        return True
    if event.kind is WorldEventKind.ACTION_TRIGGERED:
        return event.delay_ms > 0
    return False


def _unconditional_cycles(
    by_id: Mapping[str, WorldEventDefinition],
) -> list[tuple[str, ...]]:
    """Rule 22: cycles in the graph of `TRIGGER_EVENT` edges that are free of delay and guard.

    HLD gap: §30.8 rule 22 also names "`ActionTriggeredEvent` links". A world event's effects do
    not emit `EventType`s, so no static edge from an event to an `ActionTriggeredEvent` exists in
    the document; what the rule can observe is a `TRIGGER_EVENT` effect *targeting* such an event,
    which is exactly the edge modelled below (and it is free only when the target's `delay_ms` is
    zero as well). See the task report.
    """
    edges: dict[str, list[str]] = {}
    for event_id, event in by_id.items():
        free_targets: list[str] = []
        for target_id, delay_ms in _event_triggered_ids(event):
            target = by_id.get(target_id)
            if target is None or delay_ms != 0 or _is_guarded(target):
                continue
            free_targets.append(target_id)
        edges[event_id] = free_targets

    cycles: list[tuple[str, ...]] = []
    seen_cycles: set[frozenset[str]] = set()
    path: list[str] = []
    on_path: set[str] = set()
    finished: set[str] = set()

    def visit(node: str) -> None:
        path.append(node)
        on_path.add(node)
        for target in edges.get(node, ()):
            if target in on_path:
                start = path.index(target)
                members = frozenset(path[start:])
                if members not in seen_cycles:
                    seen_cycles.add(members)
                    cycles.append((*path[start:], target))
            elif target not in finished:
                visit(target)
        path.pop()
        on_path.discard(node)
        finished.add(node)

    for event_id in sorted(edges):
        if event_id not in finished:
            visit(event_id)
    return cycles


def _check_conditions_parse(version: ScenarioVersion, out: list[str]) -> None:
    """Rule 26. Every `Condition` in a parsed `ScenarioVersion` is by construction a
    `world.conditions.Condition`; a document whose condition is a string never parses (see the
    module docstring). The check is kept as an explicit assertion of the rule."""
    nodes: list[Condition] = []
    nodes.extend(_iter_conditions(version.expected_response.resolution_condition))
    for event in version.world_events:
        nodes.extend(_iter_conditions(_event_condition(event)))
    for _fact_id, clause in _available_after_clauses(version):
        nodes.extend(_iter_conditions(clause.condition))
    for node in nodes:
        if not isinstance(node, Condition):  # pragma: no cover - structurally unreachable
            out.append(f"R26: condition node {node!r} is not a declarative Condition")


def _check_emotion_rules(version: ScenarioVersion, out: list[str]) -> None:
    rules = version.caller_profile.emotion_rules
    for duplicate in sorted(_duplicates([rule.rule_id for rule in rules])):
        out.append(f"R27: caller_profile.emotion_rules: duplicate rule_id '{duplicate}'")
    known_events = {event.world_event_id for event in version.world_events}
    known_facts = set(version.world_truth.facts)
    for rule in rules:
        trigger = rule.trigger
        world_event_id = getattr(trigger, "world_event_id", None)
        if world_event_id is not None and world_event_id not in known_events:
            out.append(
                f"R27: caller_profile.emotion_rules['{rule.rule_id}'] references unknown "
                f"world_event_id '{world_event_id}'"
            )
        fact_id = getattr(trigger, "fact_id", None)
        if fact_id is not None and fact_id not in known_facts:
            out.append(
                f"R27: caller_profile.emotion_rules['{rule.rule_id}'] references unknown "
                f"fact_id '{fact_id}'"
            )


def _check_expected_response(version: ScenarioVersion, out: list[str]) -> None:
    if version.expected_response.resolution_condition is None:
        out.append("R28: expected_response.resolution_condition is required")
    chain = version.role_chain
    if chain and chain[0] is RoleType.DDS and version.expected_response.prefab_handoff is None:
        out.append(
            "R29: role_chain starts at DDS, so expected_response.prefab_handoff is required (D6)"
        )


def _check_available_after_condition_kinds(version: ScenarioVersion, out: list[str]) -> None:
    """Rule 31 (E17 R3): a fact's `available_after.condition` uses only gate-evaluable leaves.

    The fact gate runs inside one dialogue turn, and D3 gives that turn the caller-belief layer,
    the session event log and simulated time — never a `WorldTruth`. `evaluate_condition` is
    total, so a condition the gate cannot answer does not raise: it is simply never met, and the
    fact silently never opens. That is precisely the kind of quiet failure §30.8 exists to catch,
    so the clause is refused here instead. See
    `app.domain.facts.gate.unsupported_available_after_leaves` for which leaves are which and why.
    """
    for owner_fact_id, clause in _available_after_clauses(version):
        for leaf in unsupported_available_after_leaves(clause.condition):
            out.append(
                f"R31: disclosure_rules.facts['{owner_fact_id}'].available_after.condition uses "
                f"'{leaf}', which the fact gate cannot evaluate — the gate sees the caller belief, "
                f"the event log and simulated time, never world truth or the resource board (D3); "
                f"use sim_time, action, stage or fact with layer CALLER "
                f"(условие такого вида никогда не откроет факт)"
            )


def _check_variants(version: ScenarioVersion, out: list[str]) -> None:
    """Rules R32-R36 (HLD 70 §70.2.3) over a schema-2 document's `variants`.

    Declared or, when the key is omitted, derived. A schema-1 document is exempt: its variants
    are always derived from the document itself (P5 — every schema-1 scenario loads unchanged).
    """
    if version.schema_version < 2:
        return
    variants = version.scenario_variants
    _check_variant_support(variants, out)
    supported = variants.supported
    facts = (
        version.world_truth.facts,
        version.caller_knowledge.facts,
        version.disclosure_rules.facts,
    )
    if CardSource.CALLER_VOICE in supported.card_source and (
        RoleType.OPERATOR_112 not in version.role_chain or not all(facts)
    ):
        out.append(
            "R33: variants.supported.card_source has CALLER_VOICE, so role_chain must contain "
            "OPERATOR_112 and world_truth, caller_knowledge and disclosure_rules must be non-empty"
        )
    if (
        CardSource.GENERATED_CARD in supported.card_source
        and version.expected_response.prefab_handoff is None
    ):
        out.append(
            "R34: variants.supported.card_source has GENERATED_CARD, so "
            "expected_response.prefab_handoff is required"
        )
    if DdsMode.RESOURCE_PICKER in supported.dds_mode and (
        not version.available_resources or version.expected_response.resolution_condition is None
    ):
        out.append(
            "R35: variants.supported.dds_mode has RESOURCE_PICKER, so available_resources must be "
            "non-empty and expected_response.resolution_condition present"
        )
    if DdsMode.MEMO_STATUSES in supported.dds_mode and version.expected_response.responders is None:
        # R36 (I3 E5b): a memo session plays every leg no ДДС participant is bound to by script,
        # so the script — or the explicit `responders: DEFAULT` — must be written down.
        out.append(
            "R36: variants.supported.dds_mode has MEMO_STATUSES, so "
            "expected_response.responders (or responders: DEFAULT) is required"
        )


def _check_responders(
    version: ScenarioVersion, reference: ReferenceCatalog, out: list[str]
) -> None:
    """Rule R36's second half (I3 E5b, HLD 70 §70.4.5): every script in
    `expected_response.responders` can be played — each step one SIMULATION step of
    `SERVICE_RESPONSE_TRANSITIONS` under the service's status policy (from the pack's catalog),
    `after_ms` non-decreasing, a comment on «Не принята» / «Отказ» (`script_problems`)."""
    responders = version.expected_response.responders
    if responders is None or isinstance(responders, str):
        return
    catalog = reference.services(version.reference_pack_id)
    for service_id, steps in sorted(responders.items()):
        if not steps:
            out.append(f"R36: expected_response.responders['{service_id}'] is empty")
            continue
        for problem in script_problems(steps, policy_of(catalog, service_id)):
            out.append(f"R36: expected_response.responders['{service_id}']{problem}")


def _check_variant_support(variants: ScenarioVariants, out: list[str]) -> None:
    """Rule R32: `default` ∈ `supported`; every `supported` tuple non-empty, duplicate-free."""
    for switch in SWITCHES:
        values: tuple[object, ...] = getattr(variants.supported, switch)
        if not values:
            out.append(f"R32: variants.supported.{switch} is empty")
        for duplicate in sorted(str(getattr(v, "value", v)) for v in _duplicates(values)):
            out.append(f"R32: variants.supported.{switch} lists '{duplicate}' twice")
        default = getattr(variants.default, switch)
        if default not in values:
            out.append(
                f"R32: variants.default.{switch} '{default.value}' is not in "
                f"variants.supported.{switch}"
            )


def _check_applies_to_variants(version: ScenarioVersion, out: list[str]) -> None:
    """Rule R40: every `applies_to_variants` key is a switch and every value a member of it."""
    for rule in version.scoring_rules:
        for switch, values in rule.applies_to_variants.items():
            enum = SWITCH_ENUMS.get(switch)
            if enum is None:
                out.append(
                    f"R40: scoring_rules['{rule.rule_id}'].applies_to_variants names "
                    f"'{switch}', which is not a SessionVariants field"
                )
                continue
            members = {member.value for member in enum}
            for value in values:
                if value not in members:
                    out.append(
                        f"R40: scoring_rules['{rule.rule_id}'].applies_to_variants.{switch} "
                        f"lists '{value}', which is not a {enum.__name__} member"
                    )


def _check_reference_pack(
    version: ScenarioVersion, reference: ReferenceCatalog, out: list[str]
) -> None:
    """Rule R38 (HLD 70 §70.2.3, I3 E2a): `reference_pack` names a pack of the manifest.

    The card-path half of R38 — every rule-14 path exists in *that pack's* card schema — is rule 14
    itself since I3 E3a, which checks against `reference.card_schema(version.reference_pack_id)`.
    """
    if version.reference_pack is not None and reference.pack(version.reference_pack) is None:
        known = ", ".join(reference.pack_ids)
        out.append(
            f"R38: reference_pack '{version.reference_pack}' is not a pack of "
            f"reference/manifest.json (packs: {known})"
        )


def _check_service_ids(
    version: ScenarioVersion, reference: ReferenceCatalog, out: list[str]
) -> None:
    """Rule R37 (HLD 70 §70.2.3, D18, I3 E2a): every service id the document names exists in its
    pack's service catalog — `expected_response.*`, `available_resources[*].service_type`,
    `prefab_handoff.recipient_services` and the `SERVICE_SELECTION` / `RESOURCE_SELECTION` scoring
    configs. It replaces the closed `ServiceType` enum's parse-time check, so every place that enum
    guarded is covered. An unknown pack is R38's to report; R37 then has no catalog to check."""
    catalog = reference.services(version.reference_pack_id)
    if catalog is None:
        return
    for path, service_id in _service_id_references(version):
        if service_id not in catalog:
            out.append(
                f"R37: {path} names service '{service_id}', which is not in service catalog "
                f"'{catalog.catalog_id}' of reference pack '{version.reference_pack_id}'"
            )


def _service_id_references(version: ScenarioVersion) -> Iterator[tuple[str, str]]:
    expected = version.expected_response
    for index, service in enumerate(expected.required_services):
        yield f"expected_response.required_services[{index}]", service
    for index, service in enumerate(expected.optional_services):
        yield f"expected_response.optional_services[{index}]", service
    for service in expected.min_units_by_service:
        yield f"expected_response.min_units_by_service['{service}']", service
    if expected.prefab_handoff is not None:
        for index, service in enumerate(expected.prefab_handoff.recipient_services):
            yield f"expected_response.prefab_handoff.recipient_services[{index}]", service
    if expected.responders is not None and not isinstance(expected.responders, str):
        for service in expected.responders:
            yield f"expected_response.responders['{service}']", service
    for resource in version.available_resources:
        yield f"available_resources['{resource.resource_id}'].service_type", resource.service_type
    for rule in version.scoring_rules:
        try:
            config = parse_rule_config(rule)
        except ValidationError:
            continue  # rule 20's to report
        where = f"scoring_rules['{rule.rule_id}'].config"
        if isinstance(config, ServiceSelectionConfig):
            for index, service in enumerate(config.required_services):
                yield f"{where}.required_services[{index}]", service
            for index, service in enumerate(config.forbidden_services):
                yield f"{where}.forbidden_services[{index}]", service
        elif isinstance(config, ResourceSelectionConfig):
            for service in config.min_units_by_service:
                yield f"{where}.min_units_by_service['{service}']", service


def _check_timers(version: ScenarioVersion, out: list[str]) -> None:
    """Rule R39 (HLD 70 §70.2.3, I3 E4a): `timers.*` are positive integers and
    `accept_within_ms < not_completed_after_ms`. The field bounds already refuse a non-positive
    value at parse time (reported as R39 too); this re-check is the defensive half, like 24-26."""
    timers = version.card_timers
    for key in ("accept_within_ms", "fill_within_ms", "not_completed_after_ms"):
        value = getattr(timers, key)
        if value <= 0:
            out.append(f"R39: timers.{key} must be a positive integer, got {value}")
    if timers.accept_within_ms >= timers.not_completed_after_ms:
        out.append(
            f"R39: timers.accept_within_ms ({timers.accept_within_ms}) must be less than "
            f"timers.not_completed_after_ms ({timers.not_completed_after_ms})"
        )


def _check_provenance(version: ScenarioVersion, out: list[str]) -> None:
    """Rule R43 (I3 E8, HLD 30 §30.13): `provenance.ticket` / `provenance.call` name a call that
    exists — tickets 1-32, calls 1-3 (REQ-5203, REQ-5206). A malformed key (wrong type, unknown
    field, unknown `source`) never parses and is reported as R43 too (`_rule_for_parse_error`)."""
    provenance = version.provenance
    if provenance is None or provenance.source is not ProvenanceSource.TICKET:
        return
    if not 1 <= provenance.ticket <= TICKET_COUNT:
        out.append(
            f"R43: provenance.ticket {provenance.ticket} is outside 1-{TICKET_COUNT} "
            f"(source {provenance.source.value})"
        )
    if not 1 <= provenance.call <= CALLS_PER_TICKET:
        out.append(
            f"R43: provenance.call {provenance.call} is outside 1-{CALLS_PER_TICKET} "
            f"(source {provenance.source.value})"
        )


def _check_seed(version: ScenarioVersion, out: list[str]) -> None:
    if not version.deterministic_seed.strip():
        out.append("R30: deterministic_seed must be a non-empty string")


# ---------------------------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------------------------


_Check = Callable[
    [ScenarioVersion, Mapping[RoleType, RoleModule], ReferenceCatalog, list[str]], None
]

_CHECKS: tuple[tuple[tuple[int, ...], _Check], ...] = (
    ((1,), lambda version, _modules, _reference, out: _check_schema_version(version, out)),
    ((2, 3, 4), lambda version, _modules, _reference, out: _check_fact_sections(version, out)),
    (
        (5, 6, 7, 8, 9, 10),
        lambda version, _modules, _reference, out: _check_knowledge_states(version, out),
    ),
    ((11, 12, 13), lambda version, _modules, _reference, out: _check_fact_references(version, out)),
    (
        (14,),
        lambda version, _modules, reference, out: _check_card_field_paths(version, reference, out),
    ),
    ((15, 16, 17), lambda version, _modules, _reference, out: _check_resources(version, out)),
    ((18,), lambda version, modules, _reference, out: _check_role_chain(version, modules, out)),
    ((19, 20), lambda version, _modules, _reference, out: _check_scoring_rules(version, out)),
    (
        (21, 22, 23, 24, 25),
        lambda version, _modules, _reference, out: _check_world_events(version, out),
    ),
    ((26,), lambda version, _modules, _reference, out: _check_conditions_parse(version, out)),
    ((27,), lambda version, _modules, _reference, out: _check_emotion_rules(version, out)),
    ((28, 29), lambda version, _modules, _reference, out: _check_expected_response(version, out)),
    (
        (31,),
        lambda version, _modules, _reference, out: _check_available_after_condition_kinds(
            version, out
        ),
    ),
    ((30,), lambda version, _modules, _reference, out: _check_seed(version, out)),
    (
        (32, 33, 34, 35, 36),
        lambda version, _modules, _reference, out: _check_variants(version, out),
    ),
    ((36,), lambda version, _modules, reference, out: _check_responders(version, reference, out)),
    ((37,), lambda version, _modules, reference, out: _check_service_ids(version, reference, out)),
    (
        (38,),
        lambda version, _modules, reference, out: _check_reference_pack(version, reference, out),
    ),
    ((39,), lambda version, _modules, _reference, out: _check_timers(version, out)),
    ((40,), lambda version, _modules, _reference, out: _check_applies_to_variants(version, out)),
    ((43,), lambda version, _modules, _reference, out: _check_provenance(version, out)),
)
"""The rule registry: every check `scenario_version_violations` runs, with the §30.8 rule numbers
it implements. Adding a rule means adding its check here, and `VALIDATION_RULE_NUMBERS` — hence
`ScenarioValidationReport.checked_rule_count` — follows."""

VALIDATION_RULE_NUMBERS: tuple[int, ...] = tuple(
    sorted({number for numbers, _check in _CHECKS for number in numbers})
)
"""Every §30.8 rule number a validation run executes (R01-R40 after I3 E4a, and R43 after I3 E8;
R41/R42 are reserved by the telephony HLD, `80-telephony.md`)."""


def scenario_version_violations(
    version: ScenarioVersion,
    *,
    role_modules: Mapping[RoleType, RoleModule] = ROLE_MODULES,
    reference: ReferenceCatalog = LEGACY_REFERENCE,
) -> list[str]:
    """Every §30.8 violation in `version`, sorted by rule number then message.

    `reference` is the reference pack rules R37/R38 check against (HLD 70 §70.2.3), passed the way
    `role_modules` is so the function stays pure; the default is `LEGACY_REFERENCE` (the six
    legacy services, pack `legacy-r1`), and production passes the catalog the composition root
    loaded from `reference/`.
    """
    out: list[str] = []
    for _numbers, check in _CHECKS:
        check(version, role_modules, reference, out)
    return sorted(out)


def scenario_version_warnings(version: ScenarioVersion) -> list[str]:
    """Non-fatal observations about `version` (§30.6.4).

    A `MUTATE_CALLER_BELIEF` effect on an event with `caller_observable: false` is dropped at
    runtime (D7); §30.6.4 says the loader warns about that combination but does not reject it.
    """
    warnings: list[str] = []
    for event in version.world_events:
        if event.caller_observable:
            continue
        for effect in event.effects:
            if effect.kind is EffectKind.MUTATE_CALLER_BELIEF:
                warnings.append(
                    f"world_events['{event.world_event_id}']: MUTATE_CALLER_BELIEF on an event "
                    f"with caller_observable=false is dropped at runtime (D7)"
                )
                break
    return warnings


def validate_scenario_version(
    version: ScenarioVersion,
    *,
    role_modules: Mapping[RoleType, RoleModule] = ROLE_MODULES,
    reference: ReferenceCatalog = LEGACY_REFERENCE,
) -> None:
    """Raise one `ScenarioValidationError` listing every §30.8 violation, or return `None`."""
    violations = scenario_version_violations(
        version, role_modules=role_modules, reference=reference
    )
    if violations:
        raise ScenarioValidationError(violations)


def validate_scenario_document(
    document: Mapping[str, Any],
    *,
    role_modules: Mapping[RoleType, RoleModule] = ROLE_MODULES,
    reference: ReferenceCatalog = LEGACY_REFERENCE,
) -> list[str]:
    """Every §30.8 violation in a raw scenario mapping (parse errors included).

    Returns the violations rather than raising, so a CLI can report several files in one run.
    """
    try:
        version = ScenarioVersion.model_validate(document)
    except ValidationError as exc:
        return sorted(_parse_error_violations(exc))
    return scenario_version_violations(version, role_modules=role_modules, reference=reference)


def build_fact_definitions(version: ScenarioVersion) -> dict[str, FactDefinition]:
    """Join the three fact sections into one `FactDefinition` per `fact_id` (§10.4, D4).

    Raises `ScenarioValidationError` listing every join violation (§30.8 rules 2-10) when the
    three sections do not agree; the iteration order is `world_truth.facts` declaration order.
    """
    out: list[str] = []
    _check_fact_sections(version, out)
    _check_knowledge_states(version, out)
    if out:
        raise ScenarioValidationError(sorted(out))

    definitions: dict[str, FactDefinition] = {}
    for fact_id, world_spec in version.world_truth.facts.items():
        caller_spec = version.caller_knowledge.facts[fact_id]
        disclosure_spec = version.disclosure_rules.facts[fact_id]
        definitions[fact_id] = FactDefinition(
            fact_id=fact_id,
            world_value=world_spec.world_value,
            value_type=world_spec.value_type,
            label_ru=world_spec.label_ru,
            caller_value=caller_spec.caller_value,
            knowledge=caller_spec.knowledge,
            certainty=caller_spec.certainty,
            policy=disclosure_spec.policy,
            aliases_ru=disclosure_spec.aliases_ru,
            categories=disclosure_spec.categories,
            available_after=disclosure_spec.available_after,
            enum_name=world_spec.enum_name,
        )
    return definitions


# ---------------------------------------------------------------------------------------------
# Parse-error -> rule-number mapping
# ---------------------------------------------------------------------------------------------

_TIMER_KEYS = frozenset({"accept_within_ms", "fill_within_ms", "not_completed_after_ms"})
_RULE_25_FIELDS = frozenset({"at_ms", "check_after_ms", "delay_ms"})
_RULE_24_FIELDS = frozenset({"probability", "check_every_ms", "window_start_ms", "window_end_ms"})


def _rule_for_parse_error(loc: tuple[int | str, ...], message: str) -> str:
    """Map one pydantic error onto the §30.8 rule it violates.

    Rules 24-25 (world-event ranges) and 26 (`Condition` shape) are enforced by the models; every
    other structural failure is a rule-1 violation ("no unknown top-level or nested keys", i.e.
    the document does not match the declared schema).
    """
    names = frozenset(part for part in loc if isinstance(part, str))
    if "world_events" in names:
        if names & _RULE_25_FIELDS:
            return "R25"
        if names & _RULE_24_FIELDS or "window_end_ms" in message:
            return "R24"
    if "condition" in names or "resolution_condition" in names:
        return "R26"
    if "scoring_rules" in names and "applies_to_roles" in names:
        # §30.8 item 20: a listed role must be a `RoleType` member. The model already rejects
        # anything else, so the only thing left to decide is which rule number to report it as
        # — and "this rule names a role that does not exist" is a scoring-rule violation, not a
        # generic unknown-key one.
        return "R20"
    if "scoring_rules" in names and "applies_to_variants" in names:
        return "R40"
    if loc and loc[0] == "provenance":
        # R43 (I3 E8): a malformed `provenance` — a missing or unknown field, a wrong type, an
        # unknown `source` — is the rule's "well-formed" half.
        return "R43"
    if loc and loc[0] == "timers" and len(loc) > 1:
        # R39 (I3 E4a): a timer that is not a positive integer. An unknown key under `timers`
        # stays rule 1's.
        return "R39" if loc[1] in _TIMER_KEYS else "R01"
    return "R01"


def _parse_error_violations(error: ValidationError) -> list[str]:
    out: list[str] = []
    for detail in error.errors():
        loc = tuple(detail["loc"])
        rendered = ".".join(str(part) for part in loc) or "<document>"
        rule = _rule_for_parse_error(loc, str(detail["msg"]))
        out.append(f"{rule}: {rendered}: {detail['msg']}")
    return out


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------


def _duplicates[T](values: Iterable[T]) -> set[T]:
    seen: set[T] = set()
    duplicates: set[T] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return duplicates


def _compact(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in detail['loc'])}: {detail['msg']}"
        for detail in exc.errors()
    )
