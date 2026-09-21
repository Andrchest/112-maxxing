"""`SessionReport.truth_vs_card_diff` — SPEC §29 item 9, and the one place `WorldTruth` reaches a
human (D11, D3).

D3 makes WorldTruth structurally invisible: "the DDS application services and API handlers are
constructed **without** a WorldTruth repository: they cannot read it because they are never given
it." D11 names the single, deliberate exception — the post-session diff between what was true and
what the operator typed. This module is that exception, and it is a **display projection**: it
awards nothing, it is never read by `score()`, and nothing it returns feeds a running stage.

**Which fields are compared (E16 R4).** The scenario's own fact↔card-field mapping, not a new one:
every `CARD_FIELD_CORRECT` scoring rule declares `field_path` plus either `expected_from_fact_id`
(a `world_truth.facts` key) or an `expected_literal`, together with the `comparison` and
`tolerance` that rule is graded with. The diff reuses that config verbatim — same fields, same
comparison semantics — so a diff row can never disagree with the rule that scored the same field.
Fields the scenario maps to no fact are simply not in the diff; that is what "the card fields the
scenario maps to facts" means.

**Which values are compared.** `world_value` is read from the *live* `incident_world_states` row
where present, falling back to the scenario's declared `world_value`: the world-event engine may
have mutated the truth during the session (`WORLD_TRUTH_MUTATED`), and a review that showed the
scenario's opening value would be showing something that stopped being true. The card side is the
final trainee-visible `OperatorCard.values`, which D3 guarantees is "written by trainee commands
only".

**Verdicts** are exactly `openapi.yaml`'s enum:

* `MATCH` — the card holds a value and `compare()` accepts it;
* `MISMATCH` — the card holds a value and `compare()` rejects it;
* `MISSING` — the card holds no value for a field there *was* a truth to enter;
* `NOT_COMPARABLE` — there is no truth to compare against (the fact is absent from both the live
  row and the scenario, and the rule declares no literal). Reported rather than hidden: "nothing
  to check here" is a fact about the scenario a reviewer should see.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from app.domain.common.values import FactValue
from app.domain.enums import EvaluatorType
from app.domain.layers.operator_card import CARD_FIELDS, OperatorCard
from app.domain.layers.world_truth import WorldTruth
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.comparisons import compare, is_present
from app.domain.scoring.evaluators.card_field_correct import CardFieldCorrectConfig
from app.domain.scoring.rules import ScoringRule

__all__ = ["TruthVsCardEntry", "Verdict", "truth_vs_card_diff"]

#: `openapi.yaml`'s `TruthVsCardDiffEntry.verdict`.
Verdict = Literal["MATCH", "MISMATCH", "MISSING", "NOT_COMPARABLE"]

_LABELS_RU: Mapping[str, str] = {spec.field_path: spec.label_ru for spec in CARD_FIELDS}


@dataclass(frozen=True, slots=True)
class TruthVsCardEntry:
    """`openapi.yaml`'s `TruthVsCardDiffEntry`."""

    field_path: str
    label_ru: str
    world_fact_id: str | None
    world_value: FactValue
    card_value: FactValue
    verdict: Verdict


def truth_vs_card_diff(
    scenario_version: ScenarioVersion,
    card: OperatorCard | None,
    world_truth: WorldTruth | None,
) -> tuple[TruthVsCardEntry, ...]:
    """One row per `CARD_FIELD_CORRECT` rule, in the scenario's own rule order (R4).

    Pure. A session with no card at all (nothing was ever entered) still produces the rows, all
    `MISSING`: "the operator filled nothing in" is the most important diff there is.
    """
    card_values: Mapping[str, FactValue] = {} if card is None else card.values
    entries: list[TruthVsCardEntry] = []
    seen: set[str] = set()

    for rule in _card_field_correct_rules(scenario_version):
        config = CardFieldCorrectConfig.model_validate(dict(rule.config))
        if config.field_path in seen:
            # Two rules may grade the same field at two cutoffs (`HANDOFF` and `SESSION_END`);
            # the diff is about the field, not about the rule, so it appears once.
            continue
        seen.add(config.field_path)
        world_value = _world_value(config, scenario_version, world_truth)
        card_value = card_values.get(config.field_path)
        entries.append(
            TruthVsCardEntry(
                field_path=config.field_path,
                label_ru=_LABELS_RU.get(config.field_path, config.field_path),
                world_fact_id=config.expected_from_fact_id,
                world_value=world_value,
                card_value=card_value,
                verdict=_verdict(config, world_value, card_value),
            )
        )
    return tuple(entries)


def _card_field_correct_rules(scenario_version: ScenarioVersion) -> Sequence[ScoringRule]:
    """The scenario's `CARD_FIELD_CORRECT` rules, in its own order — the fact↔field mapping."""
    return [
        rule
        for rule in scenario_version.scoring_rules
        if rule.evaluator_type is EvaluatorType.CARD_FIELD_CORRECT
    ]


def _world_value(
    config: CardFieldCorrectConfig,
    scenario_version: ScenarioVersion,
    world_truth: WorldTruth | None,
) -> FactValue:
    """The truth this field should have held: the live fact, else the scenario's, else the
    rule's literal."""
    fact_id = config.expected_from_fact_id
    if fact_id is None:
        return config.expected_literal
    if world_truth is not None and fact_id in world_truth.facts:
        return world_truth.facts[fact_id]
    spec = scenario_version.world_truth.facts.get(fact_id)
    return None if spec is None else spec.world_value


def _verdict(
    config: CardFieldCorrectConfig, world_value: FactValue, card_value: FactValue
) -> Verdict:
    if not is_present(world_value):
        return "NOT_COMPARABLE"
    if not is_present(card_value):
        return "MISSING"
    correct = compare(card_value, world_value, mode=config.comparison, tolerance=config.tolerance)
    return "MATCH" if correct else "MISMATCH"
