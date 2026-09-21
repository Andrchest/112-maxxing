"""The Fact Access Gate's decision table, colouring, availability and spontaneous pass.

HLD `10-domain-model.md` §10.12, D10, SPEC §21. Rows 1-9 are exercised one test each (plus a
parametrised sweep that asserts every row is reachable), then the knowledge-state colouring, the
four `available_after` shapes, the spontaneous pass (order, cap, dedupe) and the purity and
determinism properties that make the gate safe to call from the turn loop.

The doc↔code half of the decision table lives in `test_gate_matches_the_hld.py`.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from app.domain.enums import DisclosurePolicy, GateOutcome, GateReason, KnowledgeState
from app.domain.facts.definitions import AvailableAfter, FactDefinition
from app.domain.facts.gate import (
    AllowedFactsPackage,
    FactRequest,
    GateConditionContext,
    GateDecision,
    UnavailableFact,
    evaluate_fact_access,
)
from app.domain.layers.world_truth import WorldTruth
from app.domain.world.conditions import (
    Condition,
    ConditionContext,
    FactCondition,
    SimTimeCondition,
)

from tests.unit.domain.facts._support import INCIDENT_ID, belief, definition, definitions

EMPTY_CTX = GateConditionContext()


def _ask(fact_id: str, *, explicit: bool = False) -> list[FactRequest]:
    return [FactRequest(fact_id=fact_id, explicit=explicit)]


def _run(
    requests: list[FactRequest],
    defs: dict[str, FactDefinition],
    *,
    revealed: frozenset[str] = frozenset(),
    now_ms: int = 0,
    ctx: GateConditionContext = EMPTY_CTX,
    cap: int = 2,
) -> tuple[AllowedFactsPackage, tuple[GateDecision, ...]]:
    return evaluate_fact_access(
        requests, defs, belief(defs, revealed=revealed), revealed, now_ms, ctx, cap
    )


# ---------------------------------------------------------------------------------------------
# Decision table, rows 1-9
# ---------------------------------------------------------------------------------------------


def test_row_1_an_unknown_fact_id_is_unavailable() -> None:
    """Row 1: the id is not in the definitions at all."""
    package, decisions = _run(_ask("no.such.fact"), definitions(definition("a")))

    assert decisions[0] == GateDecision(
        fact_id="no.such.fact",
        outcome=GateOutcome.UNAVAILABLE,
        reason=GateReason.UNKNOWN_FACT_ID,
    )
    assert package.allowed == ()
    assert package.unavailable[0].fact_id == "no.such.fact"


def test_row_2_never_disclose_beats_everything_else() -> None:
    """Row 2: even a `KNOWN`, available, explicitly asked, already revealed fact is refused."""
    defs = definitions(definition("a", policy=DisclosurePolicy.NEVER_DISCLOSE))

    package, decisions = _run(_ask("a", explicit=True), defs, revealed=frozenset({"a"}))

    assert decisions[0].outcome is GateOutcome.UNAVAILABLE
    assert decisions[0].reason is GateReason.NEVER_DISCLOSE
    assert package.allowed == ()


def test_row_3_an_unknown_caller_fact_is_unavailable() -> None:
    """Row 3: `KnowledgeState.UNKNOWN` under any policy but `NEVER_DISCLOSE`."""
    defs = definitions(
        definition("a", knowledge=KnowledgeState.UNKNOWN, caller_value=None),
    )

    package, decisions = _run(_ask("a", explicit=True), defs)

    assert decisions[0].reason is GateReason.CALLER_DOES_NOT_KNOW
    assert package.allowed == ()


def test_row_4_an_unmet_available_after_is_not_yet() -> None:
    """Row 4: the fact exists and is known, but its time has not come."""
    defs = definitions(definition("a", available_after=AvailableAfter(sim_time_ms=60_000)))

    package, decisions = _run(_ask("a", explicit=True), defs, now_ms=59_999)

    assert decisions[0].outcome is GateOutcome.NOT_YET
    assert decisions[0].reason is GateReason.NOT_YET_AVAILABLE
    assert package.allowed == ()
    assert package.unavailable == (
        UnavailableFact(fact_id="a", label_ru="Метка", reason=GateReason.NOT_YET_AVAILABLE),
    )


def test_row_5_an_already_revealed_fact_is_an_allowed_repeat() -> None:
    """Row 5: repeats are allowed, and they carry the caller value again."""
    defs = definitions(definition("a", caller_value="кухня"))

    package, decisions = _run(_ask("a"), defs, revealed=frozenset({"a"}))

    assert decisions[0].outcome is GateOutcome.ALLOWED_REPEAT
    assert decisions[0].reason is GateReason.ALREADY_REVEALED
    assert package.allowed[0].value == "кухня"


def test_row_5_wins_over_the_explicitness_rule() -> None:
    """Row 5 is above row 6: a revealed `ONLY_IF_EXPLICITLY_ASKED` fact repeats unasked."""
    defs = definitions(definition("a", policy=DisclosurePolicy.ONLY_IF_EXPLICITLY_ASKED))

    _package, decisions = _run(_ask("a"), defs, revealed=frozenset({"a"}))

    assert decisions[0].outcome is GateOutcome.ALLOWED_REPEAT


def test_row_6_a_non_explicit_question_withholds_and_is_counted() -> None:
    """Row 6: withheld facts appear in neither list — only in `withheld_count`."""
    defs = definitions(definition("a", policy=DisclosurePolicy.ONLY_IF_EXPLICITLY_ASKED))

    package, decisions = _run(_ask("a"), defs)

    assert decisions[0].outcome is GateOutcome.WITHHELD
    assert decisions[0].reason is GateReason.REQUIRES_EXPLICIT_QUESTION
    assert package.withheld_count == 1
    assert package.allowed == ()
    assert package.unavailable == ()


def test_row_7_an_explicit_question_releases_the_fact() -> None:
    defs = definitions(definition("a", policy=DisclosurePolicy.ONLY_IF_EXPLICITLY_ASKED))

    package, decisions = _run(_ask("a", explicit=True), defs)

    assert (decisions[0].outcome, decisions[0].reason) == (GateOutcome.ALLOWED, GateReason.OK)
    assert package.allowed[0].fact_id == "a"
    assert package.allowed[0].spontaneous is False


@pytest.mark.parametrize("explicit", [False, True])
def test_row_8_on_ask_releases_however_the_question_was_asked(explicit: bool) -> None:
    defs = definitions(definition("a", policy=DisclosurePolicy.ON_ASK))

    package, decisions = _run(_ask("a", explicit=explicit), defs)

    assert decisions[0].outcome is GateOutcome.ALLOWED
    assert package.allowed[0].fact_id == "a"


def test_row_9_a_requested_spontaneous_fact_is_allowed_not_spontaneous() -> None:
    """Row 9: asked for, so it is a plain `ALLOWED` — the spontaneous pass must not re-add it."""
    defs = definitions(definition("a", policy=DisclosurePolicy.SPONTANEOUS))

    package, decisions = _run(_ask("a"), defs)

    assert [decision.outcome for decision in decisions] == [GateOutcome.ALLOWED]
    assert package.metadata.spontaneous_attached == ()
    assert package.allowed[0].spontaneous is False


# ---------------------------------------------------------------------------------------------
# Knowledge-state colouring
# ---------------------------------------------------------------------------------------------


def test_known_is_certain_and_unhedged() -> None:
    defs = definitions(
        definition("a", knowledge=KnowledgeState.KNOWN, world_value="27", caller_value="27")
    )

    package, _ = _run(_ask("a"), defs)

    assert (package.allowed[0].value, package.allowed[0].certainty) == ("27", 1.0)
    assert package.allowed[0].hedge is False


def test_incorrect_belief_releases_the_wrong_value_without_a_hedge() -> None:
    """SPEC §3: the caller sincerely asserts "72" while the world says "27"."""
    defs = definitions(
        definition(
            "a",
            knowledge=KnowledgeState.INCORRECT_BELIEF,
            world_value="27",
            caller_value="72",
            certainty=0.9,
        )
    )

    package, _ = _run(_ask("a"), defs)

    assert package.allowed[0].value == "72"
    assert package.allowed[0].certainty == pytest.approx(0.9)
    assert package.allowed[0].hedge is False


def test_uncertain_releases_the_caller_value_with_a_hedge() -> None:
    defs = definitions(
        definition(
            "a",
            knowledge=KnowledgeState.UNCERTAIN,
            world_value="78",
            caller_value="80",
            certainty=0.4,
        )
    )

    package, _ = _run(_ask("a"), defs)

    assert package.allowed[0].value == "80"
    assert package.allowed[0].certainty == pytest.approx(0.4)
    assert package.allowed[0].hedge is True


# ---------------------------------------------------------------------------------------------
# available_after — the four shapes
# ---------------------------------------------------------------------------------------------


def test_absent_available_after_is_always_met() -> None:
    package, _ = _run(_ask("a"), definitions(definition("a")), now_ms=0)

    assert package.allowed[0].fact_id == "a"


@pytest.mark.parametrize(
    ("now_ms", "expected"),
    [(59_999, GateOutcome.NOT_YET), (60_000, GateOutcome.ALLOWED), (61_000, GateOutcome.ALLOWED)],
)
def test_sim_time_available_after_is_met_at_or_after_t(now_ms: int, expected: GateOutcome) -> None:
    defs = definitions(definition("a", available_after=AvailableAfter(sim_time_ms=60_000)))

    _package, decisions = _run(_ask("a"), defs, now_ms=now_ms)

    assert decisions[0].outcome is expected


@pytest.mark.parametrize(
    ("fired", "expected"),
    [(frozenset(), GateOutcome.NOT_YET), (frozenset({"gas"}), GateOutcome.ALLOWED)],
)
def test_world_event_available_after_needs_the_event_to_have_fired(
    fired: frozenset[str], expected: GateOutcome
) -> None:
    defs = definitions(definition("a", available_after=AvailableAfter(world_event_id="gas")))

    _package, decisions = _run(
        _ask("a"), defs, ctx=GateConditionContext(fired_world_event_ids=fired)
    )

    assert decisions[0].outcome is expected


def _condition_ctx(now_ms: int) -> GateConditionContext:
    """A `GateConditionContext` whose condition half is a real `ConditionContext`."""
    defs = definitions(definition("a"))
    return GateConditionContext(
        conditions=ConditionContext(
            world_truth=WorldTruth(incident_id=INCIDENT_ID),
            caller_belief=belief(defs),
            now_ms=now_ms,
        )
    )


@pytest.mark.parametrize(
    ("now_ms", "expected"),
    [(0, GateOutcome.NOT_YET), (10_000, GateOutcome.ALLOWED)],
)
def test_condition_available_after_uses_the_shared_condition_evaluator(
    now_ms: int, expected: GateOutcome
) -> None:
    """The gate does not reimplement conditions — it calls `evaluate_condition` (§10.11)."""
    condition = Condition(sim_time=SimTimeCondition(op="GTE", ms=5_000))
    defs = definitions(definition("a", available_after=AvailableAfter(condition=condition)))

    _package, decisions = _run(_ask("a"), defs, ctx=_condition_ctx(now_ms))

    assert decisions[0].outcome is expected


def test_a_condition_without_a_condition_context_is_unmet_not_an_error() -> None:
    """The gate is total: a missing context withholds the fact rather than raising."""
    condition = Condition(fact=FactCondition(fact_id="a", layer="CALLER", op="IS_NOT_NULL"))
    defs = definitions(definition("a", available_after=AvailableAfter(condition=condition)))

    _package, decisions = _run(_ask("a"), defs, ctx=EMPTY_CTX)

    assert decisions[0].outcome is GateOutcome.NOT_YET


# ---------------------------------------------------------------------------------------------
# The spontaneous pass
# ---------------------------------------------------------------------------------------------


def _spontaneous_defs() -> dict[str, FactDefinition]:
    return definitions(
        definition("s1", policy=DisclosurePolicy.SPONTANEOUS),
        definition("s2", policy=DisclosurePolicy.SPONTANEOUS),
        definition("s3", policy=DisclosurePolicy.SPONTANEOUS),
        definition("q", policy=DisclosurePolicy.ON_ASK),
    )


def test_the_spontaneous_pass_attaches_in_scenario_order_up_to_the_cap() -> None:
    package, decisions = _run([], _spontaneous_defs())

    assert package.metadata.spontaneous_attached == ("s1", "s2")
    assert package.metadata.max_spontaneous_per_turn == 2
    assert [fact.fact_id for fact in package.allowed] == ["s1", "s2"]
    assert all(fact.spontaneous for fact in package.allowed)
    assert [decision.outcome for decision in decisions] == [GateOutcome.ALLOWED_SPONTANEOUS] * 2


def test_the_cap_is_configurable() -> None:
    package, _ = _run([], _spontaneous_defs(), cap=3)

    assert package.metadata.spontaneous_attached == ("s1", "s2", "s3")
    assert package.metadata.max_spontaneous_per_turn == 3


def test_a_cap_of_zero_attaches_nothing() -> None:
    package, decisions = _run([], _spontaneous_defs(), cap=0)

    assert package.metadata.spontaneous_attached == ()
    assert decisions == ()


def test_the_spontaneous_pass_skips_revealed_and_already_allowed_facts() -> None:
    package, _ = _run(
        _ask("s2"),
        _spontaneous_defs(),
        revealed=frozenset({"s1"}),
    )

    # s1 was revealed, s2 was requested in the same turn: only s3 is left to attach.
    assert package.metadata.spontaneous_attached == ("s3",)
    assert [fact.fact_id for fact in package.allowed] == ["s2", "s3"]


def test_the_spontaneous_pass_skips_unknown_and_unavailable_facts() -> None:
    defs = definitions(
        definition(
            "s1",
            policy=DisclosurePolicy.SPONTANEOUS,
            knowledge=KnowledgeState.UNKNOWN,
            caller_value=None,
        ),
        definition(
            "s2",
            policy=DisclosurePolicy.SPONTANEOUS,
            available_after=AvailableAfter(sim_time_ms=60_000),
        ),
        definition("s3", policy=DisclosurePolicy.SPONTANEOUS),
    )

    package, _ = _run([], defs, now_ms=0)

    assert package.metadata.spontaneous_attached == ("s3",)


def test_the_spontaneous_pass_runs_after_the_request_loop() -> None:
    """§10.12: requested facts come first, so `allowed` order is requests then attachments."""
    package, _ = _run(_ask("q"), _spontaneous_defs())

    assert [fact.fact_id for fact in package.allowed] == ["q", "s1", "s2"]


# ---------------------------------------------------------------------------------------------
# Duplicate requests
# ---------------------------------------------------------------------------------------------


def test_duplicate_requests_for_one_fact_collapse_to_one_decision() -> None:
    defs = definitions(definition("a"))

    package, decisions = _run(
        [
            FactRequest(fact_id="a", explicit=False),
            FactRequest(fact_id="a", explicit=False),
        ],
        defs,
    )

    assert len(decisions) == 1
    assert len(package.allowed) == 1


@pytest.mark.parametrize("order", [(False, True), (True, False)])
def test_an_explicit_duplicate_wins_over_a_non_explicit_one(order: tuple[bool, bool]) -> None:
    """Whichever way round the interpreter listed them, the operator did ask explicitly."""
    defs = definitions(definition("a", policy=DisclosurePolicy.ONLY_IF_EXPLICITLY_ASKED))

    package, decisions = _run(
        [FactRequest(fact_id="a", explicit=order[0]), FactRequest(fact_id="a", explicit=order[1])],
        defs,
    )

    assert len(decisions) == 1
    assert decisions[0].outcome is GateOutcome.ALLOWED
    assert package.withheld_count == 0


def test_two_withheld_facts_count_twice() -> None:
    defs = definitions(
        definition("a", policy=DisclosurePolicy.ONLY_IF_EXPLICITLY_ASKED),
        definition("b", policy=DisclosurePolicy.ONLY_IF_EXPLICITLY_ASKED),
    )

    package, _ = _run([FactRequest(fact_id=name, explicit=False) for name in ("a", "b")], defs)

    assert package.withheld_count == 2


# ---------------------------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------------------------


def test_metadata_records_the_evaluation_offset_and_the_cap() -> None:
    package, _ = _run(_ask("a"), definitions(definition("a")), now_ms=123_456)

    assert package.metadata.evaluated_at_offset_ms == 123_456
    assert package.metadata.max_spontaneous_per_turn == 2
    assert package.metadata.turn_index == 0  # DialogueResponder stamps the real one (E13-B2)


# ---------------------------------------------------------------------------------------------
# Purity, determinism and structure
# ---------------------------------------------------------------------------------------------


def test_the_gate_mutates_none_of_its_inputs() -> None:
    defs = definitions(definition("a"), definition("s", policy=DisclosurePolicy.SPONTANEOUS))
    caller = belief(defs)
    before = caller.model_dump()
    requests = [FactRequest(fact_id="a", explicit=True)]
    revealed: frozenset[str] = frozenset()

    evaluate_fact_access(requests, defs, caller, revealed, 0, EMPTY_CTX)

    assert caller.model_dump() == before
    assert caller.revealed_fact_ids == frozenset()
    assert revealed == frozenset()
    assert requests == [FactRequest(fact_id="a", explicit=True)]
    assert set(defs) == {"a", "s"}


def test_the_gate_never_writes_revealed_fact_ids() -> None:
    """D10: only `FACTS_DELIVERED` writes them, never the gate."""
    defs = definitions(definition("a"))
    caller = belief(defs)

    package, _ = evaluate_fact_access(
        [FactRequest(fact_id="a", explicit=True)], defs, caller, frozenset(), 0, EMPTY_CTX
    )

    assert caller.revealed_fact_ids == frozenset()
    assert "revealed" not in package.model_dump()


def test_the_same_inputs_give_an_identical_package() -> None:
    defs = _spontaneous_defs()
    requests = [FactRequest(fact_id="q", explicit=True)]

    first = _run(requests, defs)
    second = _run(requests, defs)

    assert first[0] == second[0]
    assert first[0].model_dump_json() == second[0].model_dump_json()
    assert first[1] == second[1]


def test_request_order_changes_the_order_of_allowed_but_not_its_membership() -> None:
    defs = definitions(
        definition("a"), definition("b"), definition("c", policy=DisclosurePolicy.SPONTANEOUS)
    )
    forwards = [FactRequest(fact_id=name, explicit=True) for name in ("a", "b")]
    backwards = list(reversed(forwards))

    first, _ = _run(forwards, defs)
    second, _ = _run(backwards, defs)

    assert [fact.fact_id for fact in first.allowed] == ["a", "b", "c"]
    assert [fact.fact_id for fact in second.allowed] == ["b", "a", "c"]
    assert {fact.fact_id for fact in first.allowed} == {fact.fact_id for fact in second.allowed}
    assert first.withheld_count == second.withheld_count
    assert first.metadata.spontaneous_attached == second.metadata.spontaneous_attached


GATE_SOURCE = Path(inspect.getfile(evaluate_fact_access))
REVEALED_SOURCE = GATE_SOURCE.parent / "revealed.py"

#: Names that would make a "pure" function impure. `open` is checked as a call, `time` and
#: `random` as modules, `now`/`uuid4` as attributes or calls.
IMPURE_NAMES: frozenset[str] = frozenset(
    {"time", "random", "datetime", "logging", "uuid", "uuid4", "now", "open", "print"}
)


@pytest.mark.parametrize("path", [GATE_SOURCE, REVEALED_SOURCE], ids=lambda path: path.name)
def test_the_pure_modules_reach_no_clock_no_randomness_and_no_io(path: Path) -> None:
    """SPEC §21/D10: "pure function: no clock, no I/O, no LLM" — checked, not promised."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.update(node.module.split("."))
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    offenders = sorted(names & IMPURE_NAMES)
    assert not offenders, f"{path.name} reaches {offenders}"
