"""INV 1 — "The caller LLM never receives a WorldTruth fact unavailable to CallerBelief" (SPEC §42).

The invariant has a structural half and a behavioural half, and — as with INV 3 and INV 4 — the
structural one is the real guarantee.

**(a) Structural.** `evaluate_fact_access` has no parameter whose name or annotation mentions
world truth (SPEC §21: "`world_truth` is **not** a parameter"), and an `ast` scan proves that
nothing under `backend/app/domain/facts/` and nothing in
`backend/app/application/dialogue/catalog.py` imports `app.domain.layers.world_truth`, the
operator card or the handoff snapshot. A world value has no route into an `AllowedFactsPackage`
because no world value is ever in scope where the package is built.

**(b) Behavioural.** A deterministic sweep of the gate over two scenarios — the committed demo
(`scenarios/examples/apartment-fire/v1.yaml`, instantiated the way `start_session` does) and a
synthetic twin in which **every** fact's caller value differs from its world value — asking each
fact explicitly and non-explicitly, at `t = 0` and at `t = +inf`, with nothing revealed and with
everything revealed. For every one of those packages:

* every released value is exactly `caller_belief.facts[fact_id]`;
* no world-only value appears anywhere in `package.model_dump()`, compared as whole normalised
  values rather than as substrings (the flaky-"27" lesson of `reports/e11-0.md`);
* no fact whose knowledge is `UNKNOWN`, and no `NEVER_DISCLOSE` fact, is ever in `allowed`.

`test_the_sweep_would_catch_a_gate_that_read_world_truth` is the bite proof: it runs the same
assertions against a stand-in gate that does read the world value, and requires them to fail.
"""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from app.domain.common.values import FactValue
from app.domain.enums import DisclosurePolicy, KnowledgeState
from app.domain.facts.definitions import FactDefinition
from app.domain.facts.gate import (
    AllowedFactsPackage,
    FactRequest,
    GateConditionContext,
    evaluate_fact_access,
)
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.copies import instantiate_caller_belief
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion

from tests.fixtures.scenarios import demo_document

BACKEND = Path(__file__).resolve().parents[2]
FACTS_PACKAGE = BACKEND / "app" / "domain" / "facts"
CATALOG_MODULE = BACKEND / "app" / "application" / "dialogue" / "catalog.py"

#: Modules that may not be reachable from the gate or the catalog builder (D3, SPEC §21).
FORBIDDEN_MODULES: frozenset[str] = frozenset(
    {
        "app.domain.layers.world_truth",
        "app.domain.layers.operator_card",
        "app.domain.layers.handoff",
    }
)

#: The words a gate parameter must not contain, however it is spelled (SPEC §21).
FORBIDDEN_PARAMETER_WORDS: frozenset[str] = frozenset({"world_truth", "worldtruth", "world"})


# ---------------------------------------------------------------------------------------------
# (a) Structural
# ---------------------------------------------------------------------------------------------


def _scanned_modules() -> list[Path]:
    modules = sorted(path for path in FACTS_PACKAGE.rglob("*.py"))
    modules.append(CATALOG_MODULE)
    return modules


def test_the_scan_covers_the_modules_it_claims_to() -> None:
    """A guard on the guard: the gate, the bookkeeping and the catalog builder are all in it."""
    modules = _scanned_modules()

    assert FACTS_PACKAGE / "gate.py" in modules
    assert FACTS_PACKAGE / "revealed.py" in modules
    assert CATALOG_MODULE in modules
    assert all(path.is_file() for path in modules)


@pytest.mark.parametrize("path", _scanned_modules(), ids=lambda path: path.name)
def test_no_gate_module_imports_a_layer_it_may_not_see(path: Path) -> None:
    """SPEC §21 structurally: the world value is not merely unused here, it is unreachable."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    offenders = sorted(imported & FORBIDDEN_MODULES)
    assert not offenders, f"{path.relative_to(BACKEND)} imports {offenders}"


def test_the_gate_signature_names_no_world_truth() -> None:
    """SPEC §21: "`world_truth` is **not** a parameter: no world value can reach the package"."""
    signature = inspect.signature(evaluate_fact_access)

    assert list(signature.parameters) == [
        "requests",
        "definitions",
        "caller_belief",
        "revealed_fact_ids",
        "now_ms",
        "condition_ctx",
        "max_spontaneous_per_turn",
    ]
    for name, parameter in signature.parameters.items():
        spelled = f"{name} {parameter.annotation}".lower()
        words = set(re.findall(r"[a-z_]+", spelled))
        assert not words & FORBIDDEN_PARAMETER_WORDS, f"parameter {name!r} names world truth"


def test_the_allowed_fact_type_documents_the_caller_value() -> None:
    """A released value has one source, and the model says so."""
    from app.domain.facts.gate import AllowedFact

    assert set(AllowedFact.model_fields) == {
        "fact_id",
        "label_ru",
        "value",
        "value_ru",
        "certainty",
        "hedge",
        "spontaneous",
    }


def test_an_enum_facts_value_ru_comes_from_the_caller_member_not_the_world_one() -> None:
    """E13-B4 item 0: the synthetic scenario's `incident.type` disagrees ENUM-typed (SPEC §42)."""
    from app.domain.facts.value_labels_ru import ENUM_VALUE_LABELS_RU

    _name, _version, definitions, caller_belief = CASES[1]
    package, _decisions = evaluate_fact_access(
        [FactRequest(fact_id=_ENUM_DISAGREEMENT_FACT_ID, explicit=True)],
        definitions,
        caller_belief,
        frozenset(),
        0,
        GateConditionContext(),
    )

    (fact,) = [f for f in package.allowed if f.fact_id == _ENUM_DISAGREEMENT_FACT_ID]
    assert fact.value == _ENUM_DISAGREEMENT_CALLER_MEMBER
    assert fact.value_ru == ENUM_VALUE_LABELS_RU["IncidentType"][_ENUM_DISAGREEMENT_CALLER_MEMBER]
    world_only_label = ENUM_VALUE_LABELS_RU["IncidentType"]["FIRE"]
    assert world_only_label not in fact.value_ru
    assert "FIRE" not in fact.value_ru


# ---------------------------------------------------------------------------------------------
# (b) Behavioural — the deterministic sweep
# ---------------------------------------------------------------------------------------------


def _demo_version() -> ScenarioVersion:
    return ScenarioVersion.model_validate(demo_document())


#: E13-B4 item 0: this one fact stays `ENUM`-typed in the synthetic scenario, with the caller and
#: world members differing, so the sweep also proves `AllowedFact.value_ru` is rendered from the
#: CALLER member's own Russian label (`render_value_ru`) and never the world member's.
_ENUM_DISAGREEMENT_FACT_ID = "incident.type"
_ENUM_DISAGREEMENT_CALLER_MEMBER = "MEDICAL"


def _synthetic_document() -> dict[str, Any]:
    """The demo, mutated so that **every** fact's caller value differs from the world's.

    A scenario in which the two layers agree cannot distinguish "the gate released the caller
    value" from "the gate released the world value"; this one can, for every fact at once.
    """
    document = demo_document()
    caller_facts = document["caller_knowledge"]["facts"]
    for fact_id, spec in document["world_truth"]["facts"].items():
        caller = caller_facts[fact_id]
        if caller["knowledge"] == "UNKNOWN":
            continue
        caller["knowledge"] = "INCORRECT_BELIEF"
        if fact_id == _ENUM_DISAGREEMENT_FACT_ID:
            # Keep this fact ENUM/`IncidentType`-typed (world stays `FIRE`) instead of collapsing
            # it to a plain string like every other fact below.
            caller["caller_value"] = _ENUM_DISAGREEMENT_CALLER_MEMBER
            continue
        caller["caller_value"] = f"caller-only-{fact_id}"
        spec["value_type"] = "STRING"
        spec.pop("enum_name", None)
        spec["world_value"] = f"world-only-{fact_id}"
    return document


def _belief(version: ScenarioVersion) -> CallerBelief:
    """`instantiate_caller_belief`, exactly as `start_session` calls it."""
    from uuid import UUID

    from app.domain.common.ids import IncidentId

    return instantiate_caller_belief(
        version, IncidentId(UUID("0e1a4b1e-9d2a-0a7c-5b2f-1d1100000001"))
    )


def _normalise(value: FactValue) -> str | None:
    """A fact value as the comparable token a leak would have to produce."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _world_only_values(definitions: Mapping[str, FactDefinition]) -> set[str]:
    """Every world value that is not also a caller value of the same fact."""
    leaks: set[str] = set()
    for item in definitions.values():
        world = _normalise(item.world_value)
        caller = _normalise(item.caller_value)
        if world is not None and world != caller:
            leaks.add(world)
    # A value the caller holds for *some other* fact is not a world-only value at all.
    caller_values = {
        token
        for token in (_normalise(item.caller_value) for item in definitions.values())
        if token is not None
    }
    return leaks - caller_values


def _tokens(payload: Any) -> Iterator[str]:
    """Every scalar in a dumped package, as the normalised token a leak would appear as."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield from _tokens(key)
            yield from _tokens(value)
    elif isinstance(payload, list | tuple):
        for item in payload:
            yield from _tokens(item)
    else:
        token = _normalise(payload)
        if token is not None:
            yield token


SweepCase = tuple[str, ScenarioVersion, dict[str, FactDefinition], CallerBelief]


def _cases() -> list[SweepCase]:
    demo = _demo_version()
    synthetic = ScenarioVersion.model_validate(_synthetic_document())
    return [
        ("demo", demo, build_fact_definitions(demo), _belief(demo)),
        ("synthetic", synthetic, build_fact_definitions(synthetic), _belief(synthetic)),
    ]


CASES = _cases()

#: `t = +inf` for a simulation whose world events are minutes apart.
FAR_FUTURE_MS = 10**12


def _sweep(
    definitions: Mapping[str, FactDefinition], caller_belief: CallerBelief
) -> Iterator[tuple[str, AllowedFactsPackage]]:
    """Every (fact, explicitness, time, revealed-set) package the invariant sweeps, in order."""
    every_id = frozenset(definitions)
    for fact_id in definitions:
        for explicit in (False, True):
            for now_ms in (0, FAR_FUTURE_MS):
                for revealed in (frozenset(), every_id):
                    package, _decisions = evaluate_fact_access(
                        [FactRequest(fact_id=fact_id, explicit=explicit)],
                        definitions,
                        caller_belief,
                        revealed,
                        now_ms,
                        GateConditionContext(fired_world_event_ids=every_id),
                    )
                    label = f"{fact_id}/explicit={explicit}/t={now_ms}/revealed={len(revealed)}"
                    yield label, package


def test_the_synthetic_scenario_really_does_disagree_on_every_known_fact() -> None:
    """The premise of the sweep: without it, finding no world value would prove nothing."""
    _name, _version, definitions, _belief_state = CASES[1]

    disagreeing = [
        item
        for item in definitions.values()
        if item.knowledge is not KnowledgeState.UNKNOWN and item.world_value != item.caller_value
    ]

    assert len(disagreeing) >= 15
    assert all(
        item.knowledge is KnowledgeState.UNKNOWN or item.world_value != item.caller_value
        for item in definitions.values()
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case[0])
def test_every_released_value_is_the_callers_own(case: SweepCase) -> None:
    """SPEC §42 INV 1, positively: the gate returns `caller_belief.facts[fact_id]` or nothing."""
    _name, _version, definitions, caller_belief = case

    for label, package in _sweep(definitions, caller_belief):
        for fact in package.allowed:
            assert fact.value == caller_belief.facts[fact.fact_id], label


@pytest.mark.parametrize("case", CASES, ids=lambda case: case[0])
def test_no_world_only_value_appears_anywhere_in_a_package(case: SweepCase) -> None:
    """The same claim negatively, over the whole serialised package — keys included."""
    _name, _version, definitions, caller_belief = case
    forbidden = _world_only_values(definitions)

    assert forbidden, "the scenario must hold at least one world-only value"

    for label, package in _sweep(definitions, caller_belief):
        leaked = sorted(set(_tokens(package.model_dump())) & forbidden)
        assert not leaked, f"{label}: the package carries world-only values {leaked}"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case[0])
def test_unknown_and_never_disclose_facts_are_never_allowed(case: SweepCase) -> None:
    """SPEC §42 INV 2 at the same boundary: silence is the only thing they can produce."""
    _name, _version, definitions, caller_belief = case
    forbidden_ids = {
        fact_id
        for fact_id, item in definitions.items()
        if item.knowledge is KnowledgeState.UNKNOWN
        or item.policy is DisclosurePolicy.NEVER_DISCLOSE
    }

    assert forbidden_ids, "the demo scenario hides the fire source, the cause and the cylinder"

    for label, package in _sweep(definitions, caller_belief):
        released = {fact.fact_id for fact in package.allowed}
        assert not released & forbidden_ids, label


def test_the_sweep_is_deterministic() -> None:
    """No randomness anywhere: two sweeps of the same inputs are byte-identical."""
    _name, _version, definitions, caller_belief = CASES[0]

    first = [package.model_dump_json() for _label, package in _sweep(definitions, caller_belief)]
    second = [package.model_dump_json() for _label, package in _sweep(definitions, caller_belief)]

    assert first == second
    assert len(first) == len(definitions) * 2 * 2 * 2


# ---------------------------------------------------------------------------------------------
# The bite proof
# ---------------------------------------------------------------------------------------------


def test_the_sweep_would_catch_a_gate_that_read_world_truth() -> None:
    """Make the gate release the world value and the assertions above must fail.

    A structural test that cannot fail is worth nothing. The stand-in below is the smallest
    possible regression — one field of one model taken from the wrong layer — and both the
    value-identity check and the whole-package token scan have to notice it.
    """
    _name, _version, definitions, caller_belief = CASES[1]

    leaked_packages = []
    for _label, package in _sweep(definitions, caller_belief):
        broken = package.model_copy(
            update={
                "allowed": tuple(
                    fact.model_copy(update={"value": definitions[fact.fact_id].world_value})
                    for fact in package.allowed
                )
            }
        )
        if broken.allowed:
            leaked_packages.append(broken)

    assert leaked_packages, (
        "the sweep must release at least one fact for the proof to mean anything"
    )

    forbidden = _world_only_values(definitions)
    caught_value = any(
        fact.value != caller_belief.facts[fact.fact_id]
        for package in leaked_packages
        for fact in package.allowed
    )
    caught_tokens = any(
        set(_tokens(package.model_dump())) & forbidden for package in leaked_packages
    )

    assert caught_value, "the value-identity assertion does not bite"
    assert caught_tokens, "the whole-package token scan does not bite"
