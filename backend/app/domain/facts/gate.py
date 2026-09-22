"""The Fact Access Gate (HLD `10-domain-model.md` §10.12, D10, SPEC §21, §42 INV 1/INV 2).

The gate is the **only** normal path through which scenario facts reach the caller-response LLM
(SPEC §21). It is deterministic domain code: a pure function of its arguments with no clock, no
randomness, no I/O and no logging. `world_truth` is deliberately **not** a parameter, and this
module imports no layer module but `caller_belief` — a world value has no route into an
`AllowedFactsPackage` because no world value is ever in scope here (`backend/tests/invariants/
test_inv_01_gate_never_releases_world_truth.py` enforces both halves of that sentence).

Revelation is decided by code, not by text (D10): the gate never writes `revealed_fact_ids`. Only
an uninterrupted `CALLER_TTS_ENDED` produces `FACTS_DELIVERED {fact_ids}` — see
`app.domain.facts.revealed`.

HLD gaps (reported by this task, not invented here):

* **`GateMetadata.turn_index`.** §10.12 lists `turn_index` in the metadata but
  `evaluate_fact_access`'s parameter list — which §10.12 also fixes literally — has no turn index
  and no way to derive one. The gate therefore emits `turn_index = 0` and the turn pipeline that
  owns the turn counter stamps the real value — `DialogueResponder` does it (E13-B2).
* **`NOT_YET` in the package.** The package's only per-fact channels are `allowed` and
  `unavailable`, yet `50-voice-pipeline.md` §7.8 row 5 selects a fallback on "some requested fact
  is `not_yet`" from the package alone. A `NOT_YET` fact is therefore listed in `unavailable`
  carrying `reason = NOT_YET_AVAILABLE`; "unavailable" means "not released this turn", and the
  reason is what distinguishes the rows. `WITHHELD` stays out of both lists and is counted in
  `withheld_count`, exactly as §10.12 row 6 says.
* **Live `CallerBelief` vs. the scenario `FactDefinition`.** §10.12's colouring paragraph reads
  `definition.certainty`, but `CallerBelief.knowledge` / `.certainty` are the live, engine-written
  copies of exactly those scenario values (§10.3, D3) and a `MutateCallerBelief` effect may have
  moved them since instantiation. The caller's own state wins here and the definition is the
  fallback for a fact the belief does not carry; at t=0 the two are identical by construction
  (`instantiate_caller_belief`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.values import FactValue
from app.domain.enums import DisclosurePolicy, GateOutcome, GateReason, KnowledgeState
from app.domain.facts.definitions import AvailableAfter, FactDefinition
from app.domain.facts.value_labels_ru import render_value_ru
from app.domain.layers.caller_belief import CallerBelief
from app.domain.world.conditions import Condition, ConditionContext, evaluate_condition

__all__ = [
    "AllowedFact",
    "AllowedFactsPackage",
    "FactRequest",
    "GateConditionContext",
    "GateDecision",
    "GateMetadata",
    "UnavailableFact",
    "evaluate_fact_access",
    "unsupported_available_after_leaves",
]


# The `Condition` leaves a fact's `available_after` may use (E17 ruling R3).
#
# The gate is evaluated inside one dialogue turn, where D3 allows the caller-belief layer and the
# session's own event log and nothing else — in particular **no `WorldTruth`** (SPEC §2/§3: the
# operator's side of the simulation may not see the world's own values, not even indirectly
# through a fact that opens because of one). The four leaves below are exactly those that the
# log plus simulated time can answer:
#
# * `sim_time` — simulated now, which the loader has;
# * `action` — the folded `EventIndex`, which *is* the log;
# * `stage` — the `RoleStage` states, materialized from the log;
# * `fact` with `layer: CALLER` — the live `CallerBelief`, which the dialogue loader legitimately
#   holds (it is the caller's own state, §10.3).
#
# The two that are refused:
#
# * `fact` with `layer: WORLD` — a `WorldTruth` read, which D3 forbids here;
# * `resource` — the DDS resource board, which is neither in the log in a form a selector by
#   capability or service type could resolve, nor reachable from the 112 stage's dialogue.
#
# A refused leaf would not raise: `evaluate_condition` is total, so the condition would simply be
# unmet for ever and the fact would silently never open. Refusing it at load time (§30.8 rule 31)
# is what turns that silence into an error the scenario author sees.
def unsupported_available_after_leaves(condition: Condition | None) -> list[str]:
    """The leaf kinds in `condition` that a fact's `available_after` may not use, in order.

    Combinators (`all` / `any` / `not`) are walked through; each offending leaf is reported once
    per occurrence as `"fact(WORLD)"` or `"resource"`, which is the wording §30.8 rule 31's
    message quotes.
    """
    found: list[str] = []
    if condition is None:
        return found
    if condition.fact is not None and condition.fact.layer == "WORLD":
        found.append("fact(WORLD)")
    if condition.resource is not None:
        found.append("resource")
    for child in condition.all or ():
        found.extend(unsupported_available_after_leaves(child))
    for child in condition.any or ():
        found.extend(unsupported_available_after_leaves(child))
    found.extend(unsupported_available_after_leaves(condition.not_))
    return found


# ---------------------------------------------------------------------------------------------
# Types (§10.12, verbatim field lists)
# ---------------------------------------------------------------------------------------------


class FactRequest(BaseModel):
    """One fact the interpreter says the operator asked for, and how directly (§10.12, D10)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    explicit: bool


class GateDecision(BaseModel):
    """What the gate decided about one fact — the `FACT_GATE_EVALUATED` row (INSTRUCTOR only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    outcome: GateOutcome
    reason: GateReason


class AllowedFact(BaseModel):
    """A fact the caller may assert this turn. `value` is the CALLER value, never the world's."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    label_ru: str
    value: FactValue
    value_ru: str
    """The caller-style Russian spoken form of `value` (`app.domain.facts.value_labels_ru.
    render_value_ru`, from the CALLER value and the definition's `value_type`/`enum_name` — never
    from `world_value`). E13-B4 item 0: an ENUM-typed caller value must reach the prompt and §7.8
    row 2 in Russian, not as the raw member name."""
    certainty: float = Field(ge=0.0, le=1.0)
    hedge: bool
    spontaneous: bool


class UnavailableFact(BaseModel):
    """A fact the caller may not assert this turn.

    INV 2 (SPEC §42): this model has **no** `value` attribute at all, so a fact the caller does
    not know structurally cannot carry a concrete answer out of the gate.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    label_ru: str
    reason: GateReason


class GateMetadata(BaseModel):
    """`{turn_index, evaluated_at_offset_ms, spontaneous_attached, max_spontaneous_per_turn}`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_index: int = 0
    evaluated_at_offset_ms: int = 0
    spontaneous_attached: tuple[str, ...] = ()
    max_spontaneous_per_turn: int = 2


class AllowedFactsPackage(BaseModel):
    """The only fact structure the caller-response prompt builder ever receives (SPEC §21, D10)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: tuple[AllowedFact, ...] = ()
    unavailable: tuple[UnavailableFact, ...] = ()
    withheld_count: int = 0
    metadata: GateMetadata = GateMetadata()


class GateConditionContext(BaseModel):
    """Everything `available_after` may read, and nothing else (§10.12).

    Two members, because `available_after` has exactly two inputs beyond `now_ms`:

    * `fired_world_event_ids` — the ids of the world events that have fired at least once, which
      is what `{"world_event_id": E}` asks about. The world engine's `FiredEvent` log is folded
      into this set by the caller; the gate never reads the engine.
    * `conditions` — the `ConditionContext` that `app.domain.world.conditions.evaluate_condition`
      already takes, for `{"condition": C}`. It is optional: a scenario whose facts use no
      condition-shaped `available_after` (the demo is one) needs no world state to evaluate the
      gate at all, and an absent context makes every condition-shaped `available_after` unmet
      rather than raising — the gate is total, like `evaluate_condition` itself.

    Holding the condition context does not give the gate a route to a world value: it is passed
    straight to `evaluate_condition`, which returns a `bool`, and nothing in this module reads
    `.conditions` for any other purpose.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    fired_world_event_ids: frozenset[str] = frozenset()
    conditions: ConditionContext | None = None


# ---------------------------------------------------------------------------------------------
# evaluate_fact_access
# ---------------------------------------------------------------------------------------------


def _is_available(
    available_after: AvailableAfter | None,
    now_ms: int,
    condition_ctx: GateConditionContext,
) -> bool:
    """§10.12: absent; or `sim_time_ms` reached; or the event fired; or the condition holds."""
    if available_after is None:
        return True
    if available_after.sim_time_ms is not None:
        return now_ms >= available_after.sim_time_ms
    if available_after.world_event_id is not None:
        return available_after.world_event_id in condition_ctx.fired_world_event_ids
    if available_after.condition is not None and condition_ctx.conditions is not None:
        return evaluate_condition(available_after.condition, condition_ctx.conditions)
    return False


def _collapse(requests: Sequence[FactRequest]) -> tuple[FactRequest, ...]:
    """One request per `fact_id`, in first-mention order; an explicit mention wins (§10.12).

    Two requests for the same fact in one utterance are one question about that fact, and the
    decision table has one row per fact: collapsing here is what keeps `allowed` free of
    duplicates and `withheld_count` an honest count of facts rather than of mentions.
    """
    order: list[str] = []
    explicit: dict[str, bool] = {}
    for request in requests:
        if request.fact_id not in explicit:
            order.append(request.fact_id)
            explicit[request.fact_id] = request.explicit
        else:
            explicit[request.fact_id] = explicit[request.fact_id] or request.explicit
    return tuple(FactRequest(fact_id=fact_id, explicit=explicit[fact_id]) for fact_id in order)


def _decide(
    request: FactRequest,
    definition: FactDefinition | None,
    knowledge: KnowledgeState,
    available: bool,
    already_revealed: bool,
) -> tuple[GateOutcome, GateReason]:
    """The §10.12 decision table, rows 1-9, top-down, first match wins."""
    if definition is None:  # row 1
        return GateOutcome.UNAVAILABLE, GateReason.UNKNOWN_FACT_ID
    if definition.policy is DisclosurePolicy.NEVER_DISCLOSE:  # row 2
        return GateOutcome.UNAVAILABLE, GateReason.NEVER_DISCLOSE
    if knowledge is KnowledgeState.UNKNOWN:  # row 3
        return GateOutcome.UNAVAILABLE, GateReason.CALLER_DOES_NOT_KNOW
    if not available:  # row 4
        return GateOutcome.NOT_YET, GateReason.NOT_YET_AVAILABLE
    if already_revealed:  # row 5
        return GateOutcome.ALLOWED_REPEAT, GateReason.ALREADY_REVEALED
    if definition.policy is DisclosurePolicy.ONLY_IF_EXPLICITLY_ASKED and not request.explicit:
        return GateOutcome.WITHHELD, GateReason.REQUIRES_EXPLICIT_QUESTION  # row 6
    return GateOutcome.ALLOWED, GateReason.OK  # rows 7, 8, 9


def _colour(
    definition: FactDefinition,
    caller_belief: CallerBelief,
    knowledge: KnowledgeState,
    *,
    spontaneous: bool,
) -> AllowedFact:
    """Knowledge-state colouring of an allowed row (§10.12).

    `KNOWN` → `certainty = 1.0`, no hedge; `INCORRECT_BELIEF` → the caller's (wrong) value,
    sincerely asserted, no hedge; `UNCERTAIN` → the caller's value with a hedge. In every case the
    released value is `caller_belief.facts[fact_id]` and nothing else.
    """
    certainty = (
        1.0
        if knowledge is KnowledgeState.KNOWN
        else caller_belief.certainty.get(definition.fact_id, definition.certainty)
    )
    value = caller_belief.facts.get(definition.fact_id)
    return AllowedFact(
        fact_id=definition.fact_id,
        label_ru=definition.label_ru,
        value=value,
        value_ru=render_value_ru(value, definition.value_type, definition.enum_name),
        certainty=certainty,
        hedge=knowledge is KnowledgeState.UNCERTAIN,
        spontaneous=spontaneous,
    )


def evaluate_fact_access(
    requests: Sequence[FactRequest],
    definitions: Mapping[str, FactDefinition],
    caller_belief: CallerBelief,
    revealed_fact_ids: frozenset[str],
    now_ms: int,
    condition_ctx: GateConditionContext,
    max_spontaneous_per_turn: int = 2,
) -> tuple[AllowedFactsPackage, tuple[GateDecision, ...]]:
    """Decide which scenario facts the caller may assert this turn (§10.12, SPEC §21).

    Pure: no clock, no randomness, no I/O, no logging of values, and no mutation of any argument.
    The returned decisions are the `FACT_GATE_EVALUATED` payload (INSTRUCTOR only); the package is
    the only thing the caller-response prompt builder is allowed to see.

    `metadata.turn_index` is 0 here because §10.12's signature carries no turn index (see the
    module docstring). `app.application.dialogue.responder.DialogueResponder` — the turn pipeline
    stage that owns the turn counter — stamps the real value with `model_copy(update=…)` on the
    package it emits, immediately after this call and before `FACT_GATE_EVALUATED` is appended.
    """
    allowed: list[AllowedFact] = []
    unavailable: list[UnavailableFact] = []
    decisions: list[GateDecision] = []
    withheld_count = 0

    for request in _collapse(requests):
        definition = definitions.get(request.fact_id)
        knowledge = (
            caller_belief.knowledge.get(request.fact_id, definition.knowledge)
            if definition is not None
            else KnowledgeState.UNKNOWN
        )
        available = definition is not None and _is_available(
            definition.available_after, now_ms, condition_ctx
        )
        outcome, reason = _decide(
            request,
            definition,
            knowledge,
            available,
            request.fact_id in revealed_fact_ids,
        )
        decisions.append(GateDecision(fact_id=request.fact_id, outcome=outcome, reason=reason))

        if definition is not None and outcome in (GateOutcome.ALLOWED, GateOutcome.ALLOWED_REPEAT):
            allowed.append(_colour(definition, caller_belief, knowledge, spontaneous=False))
        elif outcome is GateOutcome.WITHHELD:
            withheld_count += 1
        else:
            unavailable.append(
                UnavailableFact(
                    fact_id=request.fact_id,
                    # An unknown id has no definition and therefore no label; the id is the only
                    # honest thing to name it by (D10 makes an unknown id an interpreter-side
                    # validation failure, so this row is a defence, not a normal path).
                    label_ru=definition.label_ru if definition is not None else request.fact_id,
                    reason=reason,
                )
            )

    # Spontaneous pass (§10.12): scenario declaration order, capped, ids reported in metadata.
    spontaneous_attached: list[str] = []
    already_allowed = {fact.fact_id for fact in allowed}
    for fact_id, definition in definitions.items():
        if len(spontaneous_attached) >= max_spontaneous_per_turn:
            break
        if definition.policy is not DisclosurePolicy.SPONTANEOUS:
            continue
        knowledge = caller_belief.knowledge.get(fact_id, definition.knowledge)
        if knowledge is KnowledgeState.UNKNOWN:
            continue
        if fact_id in revealed_fact_ids or fact_id in already_allowed:
            continue
        if not _is_available(definition.available_after, now_ms, condition_ctx):
            continue
        allowed.append(_colour(definition, caller_belief, knowledge, spontaneous=True))
        decisions.append(
            GateDecision(
                fact_id=fact_id, outcome=GateOutcome.ALLOWED_SPONTANEOUS, reason=GateReason.OK
            )
        )
        spontaneous_attached.append(fact_id)

    package = AllowedFactsPackage(
        allowed=tuple(allowed),
        unavailable=tuple(unavailable),
        withheld_count=withheld_count,
        metadata=GateMetadata(
            turn_index=0,
            evaluated_at_offset_ms=now_ms,
            spontaneous_attached=tuple(spontaneous_attached),
            max_spontaneous_per_turn=max_spontaneous_per_turn,
        ),
    )
    return package, tuple(decisions)
