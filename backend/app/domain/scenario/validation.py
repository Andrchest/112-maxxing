"""Scenario load-time validation and the three-section fact join (HLD `30-scenario-format.md`
§30.8, `10-domain-model.md` §10.4, §10.15, D4, SPEC §4, §5, §11, §12, §28).

Two public entry points:

* `validate_scenario_version(version, *, role_modules=ROLE_MODULES)` — the thirty rules of §30.8
  against an already-parsed `ScenarioVersion`. It raises **one** `ScenarioValidationError` whose
  `violations` lists *every* violation found, each message starting with `R<nn>:` and naming the
  offending id or path.
* `validate_scenario_document(document, *, role_modules=ROLE_MODULES)` — the same thirty rules
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

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from app.domain.common.errors import ScenarioValidationError
from app.domain.common.values import FactValue
from app.domain.enums import (
    EffectKind,
    KnowledgeState,
    RoleType,
    ValueType,
    WorldEventKind,
)
from app.domain.facts.definitions import AvailableAfter, FactDefinition
from app.domain.layers.operator_card import CARD_FIELDS, CardFieldSpec
from app.domain.roles import ROLE_MODULES
from app.domain.roles.module import RoleModule
from app.domain.scenario.sections import CallerFactSpec, WorldFactSpec
from app.domain.scenario.version import SUPPORTED_SCHEMA_VERSIONS, ScenarioVersion
from app.domain.scoring.evaluators.registry import parse_rule_config
from app.domain.world.conditions import Condition
from app.domain.world.events import WorldEventDefinition

__all__ = [
    "build_fact_definitions",
    "scenario_version_violations",
    "scenario_version_warnings",
    "validate_scenario_document",
    "validate_scenario_version",
]

_CARD_FIELD_SPECS: Mapping[str, CardFieldSpec] = {spec.field_path: spec for spec in CARD_FIELDS}

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


def _check_card_field_paths(version: ScenarioVersion, out: list[str]) -> None:
    for rule in version.scoring_rules:
        paths: list[str] = []
        single = rule.config.get(_CONFIG_FIELD_PATH_KEY)
        if isinstance(single, str):
            paths.append(single)
        listed = rule.config.get(_CONFIG_FIELD_PATH_LIST_KEY)
        if isinstance(listed, Sequence) and not isinstance(listed, str):
            paths.extend(item for item in listed if isinstance(item, str))
        for path in paths:
            if path not in _CARD_FIELD_SPECS:
                out.append(
                    f"R14: scoring_rules['{rule.rule_id}'] references unknown card "
                    f"field_path '{path}'"
                )

    prefab = version.expected_response.prefab_handoff
    if prefab is None:
        return
    for path, value in prefab.card_values.items():
        spec = _CARD_FIELD_SPECS.get(path)
        if spec is None:
            out.append(
                f"R14: expected_response.prefab_handoff.card_values['{path}'] is not a "
                f"CARD_FIELDS field_path"
            )
            continue
        if not _value_matches_type(value, spec.value_type, spec.enum_name):
            out.append(
                f"R14: expected_response.prefab_handoff.card_values['{path}'] value {value!r} "
                f"does not match value_type {spec.value_type.value}"
            )


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


def _check_seed(version: ScenarioVersion, out: list[str]) -> None:
    if not version.deterministic_seed.strip():
        out.append("R30: deterministic_seed must be a non-empty string")


# ---------------------------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------------------------


def scenario_version_violations(
    version: ScenarioVersion,
    *,
    role_modules: Mapping[RoleType, RoleModule] = ROLE_MODULES,
) -> list[str]:
    """Every §30.8 violation in `version`, sorted by rule number then message."""
    out: list[str] = []
    _check_schema_version(version, out)
    _check_fact_sections(version, out)
    _check_knowledge_states(version, out)
    _check_fact_references(version, out)
    _check_card_field_paths(version, out)
    _check_resources(version, out)
    _check_role_chain(version, role_modules, out)
    _check_scoring_rules(version, out)
    _check_world_events(version, out)
    _check_conditions_parse(version, out)
    _check_emotion_rules(version, out)
    _check_expected_response(version, out)
    _check_seed(version, out)
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
) -> None:
    """Raise one `ScenarioValidationError` listing every §30.8 violation, or return `None`."""
    violations = scenario_version_violations(version, role_modules=role_modules)
    if violations:
        raise ScenarioValidationError(violations)


def validate_scenario_document(
    document: Mapping[str, Any],
    *,
    role_modules: Mapping[RoleType, RoleModule] = ROLE_MODULES,
) -> list[str]:
    """Every §30.8 violation in a raw scenario mapping (parse errors included).

    Returns the violations rather than raising, so a CLI can report several files in one run.
    """
    try:
        version = ScenarioVersion.model_validate(document)
    except ValidationError as exc:
        return sorted(_parse_error_violations(exc))
    return scenario_version_violations(version, role_modules=role_modules)


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
        )
    return definitions


# ---------------------------------------------------------------------------------------------
# Parse-error -> rule-number mapping
# ---------------------------------------------------------------------------------------------

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
