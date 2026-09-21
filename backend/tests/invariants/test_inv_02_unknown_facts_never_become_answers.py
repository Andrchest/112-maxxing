"""INV 2 — "Unknown caller facts do not become concrete answers" (SPEC §42 item 2).

SPEC §5's `KnowledgeState.UNKNOWN` means the caller has no value at all: `caller_value` is `None`.
The deterministic boundary where that has to hold is the Fact Access Gate, and it holds there for
a structural reason rather than a behavioural one — `UnavailableFact`, the only channel through
which a refused fact reaches the prompt builder, **has no value attribute**. There is nowhere to
put an answer, so no answer can be smuggled out however the fact was asked for.

Three claims, each proved to bite:

* type-level — `UnavailableFact` carries `fact_id`, `label_ru` and `reason`, and nothing else;
* behavioural — every `UNKNOWN` fact of the demo scenario comes back `UNAVAILABLE` /
  `CALLER_DOES_NOT_KNOW`, asked explicitly or not, at any time, revealed or not;
* an id the scenario does not define comes back `UNAVAILABLE` / `UNKNOWN_FACT_ID` rather than
  being silently dropped (D10: "unknown ids are a validation failure, never dropped silently").
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import pytest
from app.domain.common.ids import IncidentId
from app.domain.enums import GateOutcome, GateReason, KnowledgeState
from app.domain.facts.definitions import FactDefinition
from app.domain.facts.gate import (
    AllowedFact,
    FactRequest,
    GateConditionContext,
    UnavailableFact,
    evaluate_fact_access,
)
from app.domain.facts.revealed import facts_delivered
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.copies import instantiate_caller_belief
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion

from tests.fixtures.scenarios import demo_document

INCIDENT_ID = IncidentId(UUID("0e1a4b1e-9d2a-0a7c-5b2f-1d1100000002"))
FAR_FUTURE_MS = 10**12


def _demo() -> tuple[dict[str, FactDefinition], CallerBelief]:
    version = ScenarioVersion.model_validate(demo_document())
    return build_fact_definitions(version), instantiate_caller_belief(version, INCIDENT_ID)


DEFINITIONS, BELIEF = _demo()

UNKNOWN_IDS = sorted(
    fact_id for fact_id, item in DEFINITIONS.items() if item.knowledge is KnowledgeState.UNKNOWN
)


def _evaluate(
    fact_id: str,
    *,
    explicit: bool,
    now_ms: int,
    revealed: frozenset[str],
    definitions: Mapping[str, FactDefinition] = DEFINITIONS,
):  # type: ignore[no-untyped-def]
    return evaluate_fact_access(
        [FactRequest(fact_id=fact_id, explicit=explicit)],
        definitions,
        BELIEF,
        revealed,
        now_ms,
        GateConditionContext(fired_world_event_ids=frozenset(definitions)),
    )


# ---------------------------------------------------------------------------------------------
# Type level — the real guarantee
# ---------------------------------------------------------------------------------------------


def test_an_unavailable_fact_has_no_value_attribute_at_all() -> None:
    """There is no field to put a concrete answer in, so there can be no concrete answer."""
    fields = set(UnavailableFact.model_fields)

    assert fields == {"fact_id", "label_ru", "reason"}
    assert not fields & {"value", "caller_value", "world_value", "certainty"}
    assert "value" in AllowedFact.model_fields, (
        "the contrast is the point: `allowed` does carry one"
    )


def test_an_unavailable_fact_rejects_a_value_even_if_someone_passes_one() -> None:
    """`extra="forbid"`: a future caller cannot bolt an answer onto the refusal."""
    with pytest.raises(ValueError, match="value"):
        UnavailableFact(
            fact_id="incident.cause",
            label_ru="Причина пожара",
            reason=GateReason.CALLER_DOES_NOT_KNOW,
            value="неисправная электропроводка",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------------------------
# Behavioural — every UNKNOWN fact of the demo, however it is asked for
# ---------------------------------------------------------------------------------------------


def test_the_demo_scenario_really_does_have_unknown_caller_facts() -> None:
    """The premise: without it, the sweep below would prove nothing."""
    assert UNKNOWN_IDS
    assert all(DEFINITIONS[fact_id].caller_value is None for fact_id in UNKNOWN_IDS)


@pytest.mark.parametrize("fact_id", UNKNOWN_IDS)
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("now_ms", [0, FAR_FUTURE_MS])
@pytest.mark.parametrize("revealed_all", [False, True])
def test_an_unknown_fact_is_always_unavailable(
    fact_id: str, explicit: bool, now_ms: int, revealed_all: bool
) -> None:
    """SPEC §42 INV 2 at the deterministic boundary, over every way of asking."""
    revealed = frozenset(DEFINITIONS) if revealed_all else frozenset()

    package, decisions = _evaluate(fact_id, explicit=explicit, now_ms=now_ms, revealed=revealed)

    assert decisions[0].outcome is GateOutcome.UNAVAILABLE
    assert decisions[0].reason in (
        GateReason.CALLER_DOES_NOT_KNOW,
        GateReason.NEVER_DISCLOSE,
    )
    assert fact_id not in {fact.fact_id for fact in package.allowed}
    assert fact_id not in facts_delivered(package, completed=True)


def test_an_unknown_fact_that_is_merely_hidden_says_so_without_a_value() -> None:
    """The refusal names the fact and the reason — the value is simply not representable."""
    fact_id = next(
        item for item in UNKNOWN_IDS if DEFINITIONS[item].policy.value != "NEVER_DISCLOSE"
    )

    package, _decisions = _evaluate(fact_id, explicit=True, now_ms=0, revealed=frozenset())

    refusal = next(fact for fact in package.unavailable if fact.fact_id == fact_id)
    assert refusal.reason is GateReason.CALLER_DOES_NOT_KNOW
    assert refusal.label_ru == DEFINITIONS[fact_id].label_ru
    assert "value" not in refusal.model_dump()


# ---------------------------------------------------------------------------------------------
# An id the scenario does not define
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("explicit", [False, True])
def test_an_unknown_fact_id_is_reported_not_dropped(explicit: bool) -> None:
    """D10: unknown ids are a failure the instructor can see, never a silent no-op."""
    package, decisions = _evaluate(
        "totally.invented.fact", explicit=explicit, now_ms=0, revealed=frozenset()
    )

    invented = [decision for decision in decisions if decision.fact_id == "totally.invented.fact"]

    assert len(invented) == 1, "the request produced exactly one decision, neither 0 nor 2"
    assert invented[0].outcome is GateOutcome.UNAVAILABLE
    assert invented[0].reason is GateReason.UNKNOWN_FACT_ID
    assert package.unavailable == (
        UnavailableFact(
            fact_id="totally.invented.fact",
            label_ru="totally.invented.fact",
            reason=GateReason.UNKNOWN_FACT_ID,
        ),
    )
    # The demo's `SPONTANEOUS` facts still attach — an invented id changes nothing else.
    assert "totally.invented.fact" not in {fact.fact_id for fact in package.allowed}
    assert all(fact.spontaneous for fact in package.allowed)


# ---------------------------------------------------------------------------------------------
# The bite proof
# ---------------------------------------------------------------------------------------------


def test_the_checks_above_would_catch_a_gate_that_answered_an_unknown_fact() -> None:
    """Move an `UNKNOWN` fact into `allowed` and the assertions must fail.

    The stand-in is the smallest regression that INV 2 is about: a fact the caller does not know
    released as though it were known. Both the membership check and `facts_delivered` have to
    notice it — and the type-level check has to stay impossible to break this way, which is why
    the value here has to be smuggled through `AllowedFact` rather than `UnavailableFact`.
    """
    fact_id = UNKNOWN_IDS[0]
    package, _decisions = _evaluate(fact_id, explicit=True, now_ms=0, revealed=frozenset())

    broken = package.model_copy(
        update={
            "allowed": (
                AllowedFact(
                    fact_id=fact_id,
                    label_ru=DEFINITIONS[fact_id].label_ru,
                    value=DEFINITIONS[fact_id].world_value,
                    value_ru=str(DEFINITIONS[fact_id].world_value),
                    certainty=1.0,
                    hedge=False,
                    spontaneous=False,
                ),
            )
        }
    )

    assert fact_id in {fact.fact_id for fact in broken.allowed}
    assert fact_id in facts_delivered(broken, completed=True)
